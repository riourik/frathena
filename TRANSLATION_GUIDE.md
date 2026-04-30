# Translation System for rAthena NPC Scripts

## Overview
Ce projet inclut un système automatisé pour traduire les scripts NPC de rAthena en français tout en conservant les fichiers originaux intacts.

## Features
- ✓ Traduction automatique des dialogs NPC en français
- ✓ Cache de traduction pour éviter les doublons
- ✓ Synchronisation automatique avec le repository upstream rAthena
- ✓ Workflow GitHub Actions pour les mises à jour quotidiennes
- ✓ Préservation des fichiers originaux

## Structure
- `npc/other/*_fr.txt` - Fichiers de base traduits
- `npc/cities/*_fr.txt` - Dialogs des villes traduits
- `npc/quests/*_fr.txt` - Quêtes traduites
- `translate_npc.py` - Script de traduction principal
- `translation_cache.json` - Cache des traductions

## Usage

### Translation locale
```bash
python translate_npc.py
```

### Script de mise à jour
```bash
bash update_translations.sh
```

## Workflow Automatique
Le workflow GitHub Actions s'exécute automatiquement :
- **Tous les jours à 00:00 UTC** : Synchronisation avec upstream + traduction
- **Sur demande** : Déclencher manuellement via GitHub Actions

## Implementation Details

### Script Python (translate_npc.py)
1. Charge la cache de traductions
2. Traduit tous les messages `mes "text";` en français
3. Utilise l'API Google Translate via deep-translator
4. Génère des fichiers `_fr.txt`
5. Sauvegarde la cache pour futures exécutions

### GitHub Actions Workflow (.github/workflows/sync.yml)
1. Merge les changements de upstream rAthena
2. Exécute le script de traduction
3. Commit et push les fichiers traduits

## Merging upstream sans casser vos changements
- Les fichiers traduits (`*_fr.txt`) sont séparés des originaux
- Les changements locaux ne sont pas affectés par les fusions
- Les traductions sont appliquées après la fusion upstream

## Notes importantes
- La traduction est en anglais vers français
- Chaque traduction est cachée pour performances
- Les fichiers originaux restent inchangés
- Vous pouvez éditer manuellement les fichiers traduits si needed
