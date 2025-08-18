
<h1 align="center">
  <img src="icons/app.svg" alt="Concatenator logo" width="48" height="48" style="vertical-align: middle;"> oncatenator
</h1>

[![CI](https://github.com/Molesox/Concatenator/actions/workflows/python-ci.yml/badge.svg)](https://github.com/Molesox/Concatenator/actions/workflows/python-ci.yml)
[![Release](https://github.com/Molesox/Concatenator/actions/workflows/release-multi-os.yml/badge.svg)](https://github.com/Molesox/Concatenator/actions/workflows/release-multi-os.yml)


**Concatenator** est une application graphique  en **PySide6** pour rassembler le contenu de plusieurs fichiers texte en un seul, avec style et efficacité.  
Idéal pour développeurs, analystes ou toute personne travaillant avec de gros ensembles de fichiers.

✨ **Points forts** :
- Interface simple et intuitive
- Filtrage par extensions (`.py`, `.cpp`, `.java`, …)
- Exclusion de dossiers indésirables (`.git`, `node_modules`, …)
- Ignorer automatiquement les fichiers binaires
- Normaliser les fins de ligne (`\n`)
- Ajouter un en-tête avec le chemin source
- Sauvegarder et recharger vos profils de paramètres
- Barre de progression + copie directe dans le presse-papiers
- Nettoyage optionnel de fichiers **C#** via Roslyn (suppression des commentaires et `using`)

---

## 🖼️ Captures d’écran

![Interface principale](assets/screenshot.png)

---

## 📥 Téléchargement

➡ **Dernière version (Windows / macOS / Linux)** :  
https://github.com/Molesox/Concatenator/releases/latest

| Système | Fichier | Notes |
|---|---|---|
| **Windows** | `Concatenator-<version>-windows.zip` ou `.exe` | Si SmartScreen s’affiche : “Plus d’infos” → “Exécuter quand même”. |
| **macOS** | `Concatenator-<version>-macos.zip` (contient `Concatenator.app`) | 1er lancement : clic droit → “Ouvrir” (app non signée). |
| **Linux** | `Concatenator-<version>-linux.tar.gz` ou binaire brut | Rendre exécutable : `chmod +x Concatenator-*` |

---

## ⚡ Utilisation rapide depuis les sources

```bash
git clone https://github.com/Molesox/Concatenator.git
cd Concatenator
pip install -r requirements.txt
python main.py
````

Ou installation directe comme package :

```bash
pip install .
concatenator
```

### Dépendance .NET/Roslyn

Un utilitaire C# (`RoslynCleaner`) est utilisé pour nettoyer les fichiers `.cs`.
Le **.NET SDK 8.0** est requis pour compiler cet outil; le binaire est généré automatiquement lors du packaging.

---

## 📦 Build local de l’exécutable

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name Concatenator main.py
# L'exécutable sera dans dist/
```



## 📜 Licence

[MIT](LICENSE) — Utilisation libre, y compris commerciale.

 
