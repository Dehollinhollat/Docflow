# src/airtable_client.py
"""
Push des données enrichies vers Airtable.
Gère : sélection de la bonne table, détection de doublons, push entreprise.
"""

import json
import os
import sys
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# 1. CONFIGURATION
# ──────────────────────────────────────────────

AIRTABLE_TOKEN   = os.getenv("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_API_URL = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"

HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    "Content-Type":  "application/json",
}

TABLE_MAP = {
    "facture":         "Table 1 - Factures",
    "bon_de_commande": "Table 2 - Bons_de_commande",
}


# ──────────────────────────────────────────────
# 2. DÉTECTION DE DOUBLON
# ──────────────────────────────────────────────

def check_duplicate(table_name: str, document_hash: str) -> bool:
    """
    Vérifie si un document avec ce hash existe déjà dans Airtable.
    Retourne True si doublon détecté.
    """
    if not document_hash:
        return False

    url = f"{AIRTABLE_API_URL}/{table_name}"
    params = {
        "filterByFormula": f'{{document_hash}}="{document_hash}"',
        "maxRecords": 1,
    }

    response = requests.get(url, headers=HEADERS, params=params)

    if response.status_code != 200:
        print(f"⚠️  Erreur vérification doublon : HTTP {response.status_code}")
        return False

    records = response.json().get("records", [])
    return len(records) > 0


# ──────────────────────────────────────────────
# 3. PUSH DOCUMENT PRINCIPAL
# ──────────────────────────────────────────────

def push_document(enriched: dict) -> dict:
    """
    Pousse le document dans la bonne table selon son type.
    Vérifie les doublons avant insertion.
    """
    type_doc = enriched.get("type_document", "inconnu")
    table    = TABLE_MAP.get(type_doc)

    if not table:
        return {
            "status":  "ignore",
            "message": f"Type de document non géré : '{type_doc}'",
        }

    champs          = enriched.get("champs", {})
    document_hash   = enriched.get("document_hash")

    # Vérification doublon
    if check_duplicate(table, document_hash):
        return {
            "status":  "doublon",
            "message": f"Document déjà présent dans {table} (hash: {document_hash})",
        }

    # Construction du payload Airtable
    fields = {
        "numero_document": champs.get("numero_document"),
        "date":            champs.get("date"),
        "montant_ht":      champs.get("montant_ht"),
        "montant_ttc":     champs.get("montant_ttc"),
        "tva":             str(champs["tva"]) if champs.get("tva") else None,
        "siret":           champs.get("siret"),
        "document_hash":   document_hash,
        "score_confiance": enriched.get("score_confiance"),
        "source":          enriched.get("source", "pdfplumber"),
        "fichier":         enriched.get("fichier"),
        "status":          enriched.get("status", "pret"),
    }

    # Retirer les champs None — Airtable rejette les valeurs null
    fields = {k: v for k, v in fields.items() if v is not None}

    url      = f"{AIRTABLE_API_URL}/{table}"
    payload  = {"fields": fields}
    response = requests.post(url, headers=HEADERS, json=payload)

    if response.status_code == 200:
        record_id = response.json().get("id")
        return {
            "status":    "succes",
            "table":     table,
            "record_id": record_id,
            "message":   f"Document inséré dans {table} (ID: {record_id})",
        }
    else:
        return {
            "status":  "erreur",
            "message": f"Airtable HTTP {response.status_code} : {response.text}",
        }


# ──────────────────────────────────────────────
# 4. PUSH ENTREPRISE
# ──────────────────────────────────────────────

def push_entreprise(enriched: dict) -> dict:
    """
    Si l'enrichissement SIRET a réussi, pousse l'entreprise dans la table Entreprises.
    Vérifie d'abord si le SIRET existe déjà.
    """
    entreprise = enriched.get("enrichissement", {}).get("entreprise", {})

    if entreprise.get("status") != "trouve":
        return {
            "status":  "ignore",
            "message": f"Entreprise non enrichie : {entreprise.get('status')}",
        }

    siret = entreprise.get("siret")

    # Vérification doublon sur SIRET
    url = f"{AIRTABLE_API_URL}/Table 3 - Entreprises"
    params = {
        "filterByFormula": f'{{siret}}="{siret}"',
        "maxRecords": 1,
    }
    check = requests.get(url, headers=HEADERS, params=params)
    if check.status_code == 200 and check.json().get("records"):
        return {"status": "doublon", "message": f"Entreprise SIRET {siret} déjà présente"}

    adresse = entreprise.get("adresse", {}) or {}
    fields  = {
        "siret":           siret,
        "siren":           entreprise.get("siren"),
        "nom_legal":       entreprise.get("nom_legal"),
        "forme_juridique": entreprise.get("forme_juridique"),
        "adresse_rue":     adresse.get("rue"),
        "code_postal":     adresse.get("code_postal"),
        "ville":           adresse.get("ville"),
        "etat":            entreprise.get("etat"),
    }
    fields = {k: v for k, v in fields.items() if v is not None}

    response = requests.post(url, headers=HEADERS, json={"fields": fields})

    if response.status_code == 200:
        return {
            "status":    "succes",
            "record_id": response.json().get("id"),
            "message":   f"Entreprise {siret} insérée",
        }
    else:
        return {
            "status":  "erreur",
            "message": f"Airtable HTTP {response.status_code} : {response.text}",
        }


# ──────────────────────────────────────────────
# 5. FONCTION PRINCIPALE
# ──────────────────────────────────────────────

def push_to_airtable(enriched: dict) -> dict:
    """
    Point d'entrée : reçoit la sortie de enricher.py.
    Pousse document + entreprise dans Airtable.
    """
    if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID:
        raise EnvironmentError("AIRTABLE_TOKEN ou AIRTABLE_BASE_ID manquant dans .env")

    result_doc        = push_document(enriched)
    result_entreprise = push_entreprise(enriched)

    return {
        "document":   result_doc,
        "entreprise": result_entreprise,
    }


# ──────────────────────────────────────────────
# 6. POINT D'ENTRÉE POUR TEST RAPIDE
# ──────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python src/airtable_client.py <fichier_json>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Fichier introuvable : {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    result = push_to_airtable(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))