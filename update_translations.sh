#!/bin/bash
# Translate NPC files and commit the results.
# Usage: ./update_translations.sh [--engine ollama] [--ollama-host IP] [--workers N] [--force]

set -e  # stop on first error

ENGINE="google"
OLLAMA_HOST=""
OLLAMA_MODEL="qwen2.5:14b"
WORKERS=3
FORCE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --engine)       ENGINE="$2";       shift 2 ;;
        --ollama-host)  OLLAMA_HOST="$2";  shift 2 ;;
        --ollama-model) OLLAMA_MODEL="$2"; shift 2 ;;
        --workers)      WORKERS="$2";      shift 2 ;;
        --force)        FORCE="--force";   shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== NPC Translation Update ==="
echo "Engine  : $ENGINE"
echo "Workers : $WORKERS"

# Build translate_npc.py arguments
ARGS="--engine $ENGINE --workers $WORKERS $FORCE"
if [[ "$ENGINE" == "ollama" ]]; then
    if [[ -z "$OLLAMA_HOST" ]]; then
        echo "Error: --ollama-host is required with --engine ollama"
        exit 1
    fi
    ARGS="$ARGS --ollama-host $OLLAMA_HOST --ollama-model $OLLAMA_MODEL"
    echo "Host    : $OLLAMA_HOST"
    echo "Model   : $OLLAMA_MODEL"
fi

echo ""
python translate_npc.py $ARGS

echo ""
echo "=== Committing results ==="

# Stage translated files + cache (never stage originals or conf)
git add $(find npc -name '*_fr.txt' 2>/dev/null) translation_cache.json || true

# Only commit if there is something staged
if git diff --staged --quiet; then
    echo "Nothing new to commit."
else
    git commit -m "Update French NPC translations ($(date +%Y-%m-%d))"
    echo "Committed. Run 'git push' when ready."
fi
