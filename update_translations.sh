#!/bin/bash
# Script pour maintenir les traductions à jour automatiquement

echo "=== NPC Translation Update Script ==="
echo "Updating translations for /npc/ files..."

# Exécuter le script de traduction
python translate_npc.py

if [ $? -eq 0 ]; then
    echo "✓ Translation complete!"

    # Optionnel : commiter les changements
    git add npc/**/*_fr.txt
    git commit -m "Auto-update NPC French translations" || true
    git push origin master || true
else
    echo "✗ Translation failed!"
    exit 1
fi
