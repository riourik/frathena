import re
import os
import json
import time
import argparse
import threading
import urllib.request
import urllib.error
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from deep_translator import GoogleTranslator
from deep_translator.exceptions import TranslationNotFound

CACHE_FILE = 'translation_cache.json'
SAVE_EVERY = 100

cache = {}
new_translations = 0
_cache_lock = threading.Lock()

# Engine config — set from CLI args in __main__
_engine          = 'google'
_ollama_host     = 'localhost'
_ollama_model    = 'qwen2.5:14b'
_ollama_batch    = 20  # strings per Ollama request
_lmstudio_host   = 'localhost'
_lmstudio_model  = 'local-model'
_lmstudio_batch  = 20  # strings per LM Studio request

# keyword "text"; — first string arg
KEYWORDS = ('mes', 'dispbottom', 'npctalk')
_PATTERN = re.compile(r'(' + '|'.join(KEYWORDS) + r')(\s+")([^"]*)(";\s*)')

# announce "text", flags;
_ANNOUNCE_PATTERN = re.compile(r'(announce\s+")([^"]*)(",)')

# mapannounce "map","text", flags; — second arg is the text
_MAPANNOUNCE_PATTERN = re.compile(r'(mapannounce\s+"[^"]*"\s*,\s*")([^"]*)(")')

# rAthena color codes like ^FF0000
_COLOR_RE = re.compile(r'\^[0-9A-Fa-f]{6}')

_IMPORT_RE = re.compile(r'^(\s*(?:npc|import):\s*)([^\s/][^\n]*\.(txt|conf))(\s*)$')


def load_cache():
    global cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
    print(f"Cache: {len(cache)} entries loaded")


def save_cache():
    with _cache_lock:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)


def _should_translate(text: str) -> bool:
    s = text.strip() if text else ''
    return len(s) >= 3 and len(_COLOR_RE.sub('', s).strip()) >= 3


def _extract(line):
    """Return (match, group_index) for the first translatable pattern, or None."""
    m = _MAPANNOUNCE_PATTERN.search(line)
    if m:
        return m, 2
    m = _ANNOUNCE_PATTERN.search(line)
    if m:
        return m, 2
    m = _PATTERN.search(line)
    if m:
        return m, 3
    return None


def _ollama_request(prompt: str, force_json: bool = False) -> str:
    """Send a chat prompt to the Ollama server and return the response text."""
    body = {
        "model": _ollama_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    if force_json:
        body["format"] = "json"  # forces the model to output valid JSON
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://{_ollama_host}:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["message"]["content"]


def _ollama_translate_one(text: str) -> str:
    """Translate a single string via Ollama. Fallback for when batch fails."""
    prompt = (
        "Translate this Ragnarok Online NPC dialog from English to French.\n"
        "Return ONLY the French translation, nothing else.\n"
        "Preserve color codes like ^FF0000 and NPC names in [brackets] exactly.\n\n"
        f"{text}"
    )
    for attempt in range(3):
        try:
            result = _ollama_request(prompt).strip()
            if result:
                return result
        except Exception:
            if attempt < 2:
                time.sleep(attempt + 1)
    return text


def _batch_translate_ollama(uncached: list[str]) -> dict[str, str]:
    """Translate strings via Ollama in batches. Returns {original: translated}."""
    global new_translations
    results = {}

    for i in range(0, len(uncached), _ollama_batch):
        chunk = uncached[i:i + _ollama_batch]
        numbered = "\n".join(f"{j + 1}. {t}" for j, t in enumerate(chunk))
        prompt = (
            "You are a translator for a French Ragnarok Online game server.\n"
            "Translate each numbered NPC dialog line from English to French.\n"
            "Rules:\n"
            "- Output a JSON object mapping each number to its French translation\n"
            "- Preserve exactly: color codes (^FF0000), NPC names in [brackets]\n"
            "- Keep city/item proper nouns unchanged\n\n"
            f"Lines to translate:\n{numbered}"
        )
        translated_chunk = False
        for attempt in range(3):
            try:
                # force_json=True tells Ollama to guarantee valid JSON output
                content = _ollama_request(prompt, force_json=True)
                content = re.sub(r"```(?:json)?\s*|\s*```", "", content).strip()
                start, end = content.find("{"), content.rfind("}")
                if start == -1 or end == -1:
                    raise ValueError("No JSON in response")
                translations = json.loads(content[start:end + 1])
                with _cache_lock:
                    for k, v in translations.items():
                        if k.isdigit():
                            idx = int(k) - 1
                            if 0 <= idx < len(chunk) and v:
                                orig = chunk[idx]
                                cache[orig] = str(v)
                                results[orig] = str(v)
                                new_translations += 1
                if new_translations % SAVE_EVERY == 0:
                    save_cache()
                translated_chunk = True
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(attempt + 1)
                else:
                    print(f"  [warn] ollama batch failed ({e}), falling back to individual")

        # Fallback: translate one by one if batch failed
        if not translated_chunk:
            for text in chunk:
                tr = _ollama_translate_one(text)
                if tr and tr != text:
                    with _cache_lock:
                        cache[text] = tr
                        results[text] = tr
                        new_translations += 1

    return results


def _lmstudio_request(prompt: str) -> str:
    """Send a chat prompt to the LM Studio server and return the response text."""
    body = {
        "model": _lmstudio_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "stream": False,
    }
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://{_lmstudio_host}:1234/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


def _lmstudio_translate_one(text: str) -> str:
    """Translate a single string via LM Studio. Fallback for when batch fails."""
    prompt = (
        "Translate this Ragnarok Online NPC dialog from English to French.\n"
        "Return ONLY the French translation, nothing else.\n"
        "Preserve color codes like ^FF0000 and NPC names in [brackets] exactly.\n\n"
        f"{text}"
    )
    for attempt in range(3):
        try:
            result = _lmstudio_request(prompt).strip()
            if result:
                return result
        except Exception:
            if attempt < 2:
                time.sleep(attempt + 1)
    return text


def _batch_translate_lmstudio(uncached: list[str]) -> dict[str, str]:
    """Translate strings via LM Studio in batches. Returns {original: translated}."""
    global new_translations
    results = {}

    for i in range(0, len(uncached), _lmstudio_batch):
        chunk = uncached[i:i + _lmstudio_batch]
        numbered = "\n".join(f"{j + 1}. {t}" for j, t in enumerate(chunk))
        prompt = (
            "You are a translator for a French Ragnarok Online game server.\n"
            "Translate each numbered NPC dialog line from English to French.\n"
            "Rules:\n"
            "- Output a JSON object mapping each number to its French translation\n"
            "- Preserve exactly: color codes (^FF0000), NPC names in [brackets]\n"
            "- Keep city/item proper nouns unchanged\n\n"
            f"Lines to translate:\n{numbered}"
        )
        translated_chunk = False
        for attempt in range(3):
            try:
                content = _lmstudio_request(prompt)
                content = re.sub(r"```(?:json)?\s*|\s*```", "", content).strip()
                start, end = content.find("{"), content.rfind("}")
                if start == -1 or end == -1:
                    raise ValueError("No JSON in response")
                translations = json.loads(content[start:end + 1])
                with _cache_lock:
                    for k, v in translations.items():
                        if k.isdigit():
                            idx = int(k) - 1
                            if 0 <= idx < len(chunk) and v:
                                orig = chunk[idx]
                                cache[orig] = str(v)
                                results[orig] = str(v)
                                new_translations += 1
                if new_translations % SAVE_EVERY == 0:
                    save_cache()
                translated_chunk = True
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(attempt + 1)
                else:
                    print(f"  [warn] lmstudio batch failed ({e}), falling back to individual")

        if not translated_chunk:
            for text in chunk:
                tr = _lmstudio_translate_one(text)
                if tr and tr != text:
                    with _cache_lock:
                        cache[text] = tr
                        results[text] = tr
                        new_translations += 1

    return results


def _batch_translate(texts: list[str]) -> dict[str, str]:
    """Translate a list of texts, dispatching to the configured engine."""
    global new_translations

    uncached = [t for t in texts if t not in cache and _should_translate(t)]
    if not uncached:
        return {}

    if _engine == "ollama":
        return _batch_translate_ollama(uncached)

    if _engine == "lmstudio":
        return _batch_translate_lmstudio(uncached)

    # Google Translate — batches of 50
    results = {}
    for i in range(0, len(uncached), 50):
        chunk = uncached[i:i + 50]
        for attempt in range(3):
            try:
                translated = GoogleTranslator(source="en", target="fr").translate_batch(chunk)
                with _cache_lock:
                    for orig, tr in zip(chunk, translated):
                        if tr and tr != orig:
                            cache[orig] = tr
                            results[orig] = tr
                            new_translations += 1
                if new_translations % SAVE_EVERY == 0:
                    save_cache()
                break
            except TranslationNotFound:
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(attempt + 1)
                else:
                    print(f"  [warn] google batch failed: {e}")
    return results


def translate_file(input_path: Path, output_path: Path) -> bool:
    try:
        lines = input_path.read_text(encoding='utf-8', errors='ignore').splitlines(keepends=True)
    except Exception as e:
        print(f"  [error] read {input_path}: {e}")
        return False

    # Phase 1: extract all translatable positions
    hits = []  # (line_idx, match, group_idx, text)
    for i, line in enumerate(lines):
        r = _extract(line)
        if r:
            m, g = r
            text = m.group(g)
            if _should_translate(text):
                hits.append((i, m, g, text))

    # Phase 2: batch translate all uncached strings in one API call
    if hits:
        _batch_translate([text for _, _, _, text in hits])

    # Phase 3: apply cached translations
    for i, m, g, text in hits:
        translated = cache.get(text, text)
        lines[i] = lines[i][:m.start(g)] + translated + lines[i][m.end(g):]

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(''.join(lines), encoding='utf-8')
        return True
    except Exception as e:
        print(f"  [error] write {output_path}: {e}")
        return False


def process_folder(folder: str, output_suffix: str = '_fr',
                   recursive: bool = True, force: bool = False,
                   workers: int = 1):
    root = Path(folder)
    if not root.is_dir():
        print(f"[skip] {folder} is not a directory")
        return 0, 0, 0

    pattern = '**/*.txt' if recursive else '*.txt'
    files = [f for f in root.glob(pattern)
             if f.is_file() and '_fr' not in f.stem]

    # Group by subdirectory for display
    by_subdir = defaultdict(list)
    for f in files:
        by_subdir[f.parent.relative_to(root)].append(f)

    # Build work list
    work = []
    for subdir in sorted(by_subdir):
        for src in by_subdir[subdir]:
            dst = src.parent / f"{src.stem}{output_suffix}{src.suffix}"
            work.append((src, dst))

    total = len(work)
    done = skipped = failed = 0
    lock = threading.Lock()

    def process_one(args):
        nonlocal done, skipped, failed
        src, dst = args
        if not force and dst.exists():
            with lock:
                skipped += 1
            return 'skip', src
        ok = translate_file(src, dst)
        with lock:
            if ok:
                done += 1
            else:
                failed += 1
        return ('ok' if ok else 'fail'), src

    # Display subdir headers while tracking progress
    subdir_state = {}
    for subdir in sorted(by_subdir):
        files_in = by_subdir[subdir]
        pending = sum(1 for f in files_in
                      if force or not (f.parent / f"{f.stem}{output_suffix}{f.suffix}").exists())
        already = len(files_in) - pending
        label = f"{folder}/{subdir}" if str(subdir) != '.' else folder
        note = f"  ({already} already translated)" if already else ""
        subdir_state[subdir] = label
        print(f"\n-- {label}/ [{len(files_in)} files{note}]")

    if workers > 1:
        print(f"\n[parallel: {workers} workers]")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(process_one, w): w for w in work}
            completed = 0
            for future in as_completed(futures):
                status, src = future.result()
                completed += 1
                if status != 'skip':
                    rel = src.relative_to(root)
                    print(f"  [{completed}/{total}] {rel} ... {status.upper()}", flush=True)
    else:
        for i, (src, dst) in enumerate(work, 1):
            status, _ = process_one((src, dst))
            if status != 'skip':
                print(f"  [{i}/{total}] {src.name} ... {status.upper()}", flush=True)

    return done, skipped, total


def generate_conf(source: str, output: str, suffix: str = '_fr') -> int:
    src = Path(source)
    if not src.exists():
        return 0
    lines = src.read_text(encoding='utf-8').splitlines(keepends=True)
    out, replaced = [], 0
    for line in lines:
        m = _IMPORT_RE.match(line)
        if m:
            prefix, path, _, tail = m.groups()
            p = Path(path)
            fr = p.parent / f"{p.stem}{suffix}{p.suffix}"
            if fr.exists():
                out.append(f"{prefix}{fr}{tail}\n")
                replaced += 1
                continue
        out.append(line)
    Path(output).write_text(''.join(out), encoding='utf-8')
    return replaced


def generate_all_confs(suffix: str = '_fr'):
    print("\n=== Generating French script confs ===")
    for conf in sorted(Path('npc').glob('scripts_*.conf')):
        if suffix in conf.stem:
            continue
        out = conf.parent / f"{conf.stem}{suffix}{conf.suffix}"
        n = generate_conf(str(conf), str(out), suffix)
        if n:
            print(f"  {out.name}: {n} paths updated")
    for sub in ('re', 'pre-re'):
        for conf in sorted(Path(f'npc/{sub}').glob('scripts_*.conf')):
            if suffix in conf.stem or conf.name == 'scripts_main.conf':
                continue
            out = conf.parent / f"{conf.stem}{suffix}{conf.suffix}"
            n = generate_conf(str(conf), str(out), suffix)
            if n:
                print(f"  {sub}/{out.name}: {n} paths updated")
    for main in ('npc/re/scripts_main.conf', 'npc/pre-re/scripts_main.conf'):
        p = Path(main)
        if not p.exists():
            continue
        patched = generate_conf(main, main, suffix)
        print(f"  {main}: {patched} imports patched")
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Translate rAthena NPC .txt files (en → fr)"
    )
    parser.add_argument(
        'folders', nargs='*', default=['npc'],
        help="Folders to process (default: npc)"
    )
    parser.add_argument(
        '--force', action='store_true',
        help="Re-translate even if output file already exists"
    )
    parser.add_argument(
        '--no-recursive', action='store_true',
        help="Only process top-level directory, not subdirectories"
    )
    parser.add_argument(
        '--suffix', default='_fr',
        help="Output file suffix (default: _fr)"
    )
    parser.add_argument(
        '--workers', type=int, default=3,
        help="Parallel file workers (default: 3, raise to 8+ with Ollama)"
    )
    parser.add_argument(
        '--engine', choices=['google', 'ollama', 'lmstudio'], default='google',
        help="Translation engine (default: google)"
    )
    parser.add_argument(
        '--ollama-host',
        help="Ollama server IP or hostname (e.g. 192.168.1.42)"
    )
    parser.add_argument(
        '--ollama-model', default='qwen2.5:14b',
        help="Ollama model to use (default: qwen2.5:14b)"
    )
    parser.add_argument(
        '--ollama-batch', type=int, default=20,
        help="Strings per Ollama request (default: 20)"
    )
    parser.add_argument(
        '--lmstudio-host', default='localhost',
        help="LM Studio server IP or hostname (default: localhost)"
    )
    parser.add_argument(
        '--lmstudio-model', default='local-model',
        help="LM Studio model identifier (default: local-model)"
    )
    parser.add_argument(
        '--lmstudio-batch', type=int, default=20,
        help="Strings per LM Studio request (default: 20)"
    )
    parser.add_argument(
        '--gen-conf', action='store_true',
        help="Generate French .conf files and patch scripts_main.conf"
    )
    args = parser.parse_args()

    # Apply engine config
    _engine = args.engine
    if args.engine == 'ollama':
        if not args.ollama_host:
            parser.error("--ollama-host is required when using --engine ollama")
        _ollama_host  = args.ollama_host
        _ollama_model = args.ollama_model
        _ollama_batch = args.ollama_batch
        print(f"Engine: Ollama  host={_ollama_host}  model={_ollama_model}  batch={_ollama_batch}")
    elif args.engine == 'lmstudio':
        _lmstudio_host  = args.lmstudio_host
        _lmstudio_model = args.lmstudio_model
        _lmstudio_batch = args.lmstudio_batch
        print(f"Engine: LM Studio  host={_lmstudio_host}  model={_lmstudio_model}  batch={_lmstudio_batch}")
    else:
        print("Engine: Google Translate")

    load_cache()

    total_done = total_skipped = total_files = 0

    for folder in args.folders:
        print(f"\n=== Processing {folder}/ ===")
        done, skipped, total = process_folder(
            folder,
            output_suffix=args.suffix,
            recursive=not args.no_recursive,
            force=args.force,
            workers=args.workers,
        )
        total_done += done
        total_skipped += skipped
        total_files += total
        print(f"\n  -> {done} translated, {skipped} skipped, {total} total")

    save_cache()
    print(f"\nFinished: {total_done} translated, {total_skipped} skipped, {total_files} total")
    print(f"Cache: {len(cache)} entries ({new_translations} new)")

    if args.gen_conf:
        generate_all_confs(args.suffix)
