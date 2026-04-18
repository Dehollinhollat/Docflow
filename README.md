# 🗂️ DocFlow — Traitement intelligent de documents entrants

**Auteur :** Déhollin HOLLAT, Chef de Projet Data IA

> Pipeline automatisé qui surveille une boîte mail, extrait les données clés des factures et bons de commande, les enrichit via API et les consolide dans Airtable — sans intervention humaine.

---

## 🎯 Pitch en une phrase

**DocFlow transforme chaque email avec pièce jointe en donnée structurée, validée et archivée — en moins de 30 secondes.**

---

## 🖼️ Aperçu

![Architecture DocFlow](docs/images/architecture.png)

---

## ⚙️ Stack technique

| Couche | Outil |
|---|---|
| Surveillance Gmail | Python + API Google Gmail |
| Extraction PDF natif | pdfplumber |
| Extraction PDF scanné / images | Claude API (claude-haiku) |
| Normalisation & validation | Python |
| Enrichissement SIRET | API entreprise.data.gouv.fr |
| Stockage | Airtable |
| API | FastAPI |
| Déploiement | Render |

---

## 📁 Structure du projet
```
docflow/
│
├── src/
│   ├── extractor.py        # Extraction PDF natif (pdfplumber)
│   ├── vision.py           # Extraction PDF scanné / images (Claude API)
│   ├── normalizer.py       # Normalisation, validation, score, hash
│   ├── enricher.py         # Enrichissement SIRET (API gouvernementale)
│   └── airtable_client.py  # Push vers Airtable + déduplication
│
├── docs/
│   └── images/             # Visuels pour la documentation
│
├── data/
│   ├── raw/                # Documents bruts reçus
│   ├── processed/          # Documents traités
│   └── processed_ids.json  # IDs des emails déjà traités
│
├── tests/
│   ├── sample_facture.pdf
│   └── sample_image.jpg
│
├── main.py                 # API FastAPI (endpoints /process, /process_b64)
├── gmail_watcher.py        # Surveillance Gmail automatique
├── METHODOLOGIE.md         # Documentation complète du projet
├── requirements.txt
├── Procfile
└── .env                    # Variables d'environnement (non versionné)
```
---

## 🔢 Les 5 phases du pipeline

**Phase 1 — Extraction PDF natif** (`extractor.py`)
Lecture du texte avec pdfplumber, détection du type de document, extraction des champs clés par regex, calcul du score de confiance.

**Phase 2 — Extraction par vision IA** (`vision.py`)
Pour les PDF scannés et images — envoi à Claude API, prompt structuré, réponse JSON normalisée.

**Phase 3 — Normalisation** (`normalizer.py`)
Format uniforme quel que soit la source, validation des champs obligatoires, déduplication par hash SHA256.

**Phase 4 — Enrichissement** (`enricher.py`)
Appel API entreprise.data.gouv.fr pour récupérer les informations légales depuis le SIRET.

**Phase 5 — Push Airtable** (`airtable_client.py`)
Sélection de la bonne table selon le type de document, vérification doublon, insertion.

---

## 🚀 Installation

```bash
# Cloner le repo
git clone https://github.com/Dehollinhollat/Docflow.git
cd Docflow

# Créer et activer le venv
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Mac/Linux

# Installer les dépendances
pip install -r requirements.txt

# Configurer les variables d'environnement
cp .env.example .env
# Remplir ANTHROPIC_API_KEY, AIRTABLE_TOKEN, AIRTABLE_BASE_ID
```

---

## ▶️ Utilisation

### Lancer l'API en local

```bash
uvicorn main:app --port 8000
```

### Tester le pipeline sur un fichier

```bash
python src/extractor.py tests/sample_facture.pdf
```

### Lancer la surveillance Gmail

```bash
python gmail_watcher.py
```

### Tester l'API avec un fichier

```python
import requests
with open('tests/sample_facture.pdf', 'rb') as f:
    r = requests.post('http://localhost:8000/process',
                      files={'file': ('facture.pdf', f, 'application/pdf')})
    print(r.json())
```

---

## 📊 Résultats

| Document | Source | Score | Statut |
|---|---|---|---|
| Facture PDF native | pdfplumber | 100% ✅ | Extrait |
| Facture PDF scannée | Claude Vision | 100% ✅ | Extrait |
| Bon de commande artisan | Claude Vision | 100% ✅ | Extrait |
| Facture atelier poterie | Claude Vision | 80% ⚠️ | SIRET absent |

---

## 💬 Questions

| Question | Réponse clé |
|---|---|
| Pourquoi deux méthodes d'extraction ? | pdfplumber est déterministe et gratuit sur PDF natif — Claude Vision gère les cas complexes (scans, images) |
| C'est quoi le score de confiance ? | % de champs obligatoires correctement extraits — en dessous de 70% le document passe en revue manuelle |
| Comment tu gères les doublons ? | Hash SHA256 sur numéro + montant + date — si le hash existe dans Airtable on rejette avec notification |
| Pourquoi Airtable ? | Interface no-code immédiatement utilisable par les équipes métier sans compétences techniques |
| Pourquoi FastAPI ? | Expose le pipeline Python comme une API REST — permet à n'importe quel outil (n8n, Make, Zapier) de l'appeler |

---

## 📖 Documentation complète

👉 [Voir la méthodologie complète](METHODOLOGIE.md)

---

## 🔑 Variables d'environnement

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Clé API Anthropic (Claude) |
| `AIRTABLE_TOKEN` | Token personnel Airtable |
| `AIRTABLE_BASE_ID` | ID de la base Airtable (appXXXXXXXX) |
| `DOCFLOW_API_URL` | URL de l'API (défaut : http://localhost:8000) |