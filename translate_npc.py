import re
import os
import json
from pathlib import Path
from deep_translator import GoogleTranslator

# Cache for translations
cache_file = 'translation_cache.json'
cache = {}

def load_cache():
    global cache
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache = json.load(f)

def save_cache():
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def translate_text(text):
    if not text or len(text) < 3:
        return text

    if text in cache:
        return cache[text]

    try:
        translated = GoogleTranslator(source='en', target='fr').translate(text)
        cache[text] = translated
        return translated
    except Exception as e:
        print(f"Translation error for '{text}': {e}")
        return text

def translate_file(input_file, output_file):
    """Translate all mes strings in a file"""
    try:
        with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        translated_lines = []
        for line in lines:
            # Find mes "text";
            match = re.search(r'mes\s+"([^"]*)";', line)
            if match:
                original_text = match.group(1)
                translated_text = translate_text(original_text)
                new_line = line.replace(f'mes "{original_text}";', f'mes "{translated_text}";')
                translated_lines.append(new_line)
            else:
                translated_lines.append(line)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(translated_lines)

        print(f"✓ {input_file} -> {output_file}")
        return True
    except Exception as e:
        print(f"✗ Error processing {input_file}: {e}")
        return False

def process_folder(folder_path, output_suffix='_fr'):
    """Process all .txt files in a folder"""
    count = 0
    for txt_file in Path(folder_path).glob('*.txt'):
        output_file = str(txt_file.parent / f"{txt_file.stem}{output_suffix}{txt_file.suffix}")
        if translate_file(str(txt_file), output_file):
            count += 1
    return count

if __name__ == "__main__":
    load_cache()

    # Translate files in /npc/other/ (base folder)
    print("Translating /npc/other/...")
    count = process_folder('npc/other')
    print(f"Translated {count} files in /npc/other/\n")

    # Translate files in /npc/cities/
    print("Translating /npc/cities/...")
    count = process_folder('npc/cities')
    print(f"Translated {count} files in /npc/cities/\n")

    # Translate files in /npc/quests/
    print("Translating /npc/quests/...")
    count = process_folder('npc/quests')
    print(f"Translated {count} files in /npc/quests/\n")

    save_cache()
    print("Translation cache saved!")
