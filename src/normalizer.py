# src/normalizer.py
"""
Normalisation et validation des données extraites.
Reçoit la sortie de extractor.py ou vision.py → produit un objet uniforme pour Airtable.
Gère aussi la détection de doublons via hash.
"""

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path


# ──────────────────────────────────────────────
# 1. NORMALISATION DES MONTANTS
# ──────────────────────────────────────────────

def normalize_amount(value) -> float | None:
    """
    Convertit n'importe quel format de montant en float.
    Exemples : "1 878,99" → 1878.99 | "2 146.04" → 2146.04 | None → None
    """
    if value is None:
        return None
    cleaned = str(value).replace(" ", "").replace("\xa0", "")  # espaces insécables
    cleaned = cleaned.replace(",", ".")
    cleaned = re.sub(r"[^\d.]", "", cleaned)  # retire €, lettres, etc.
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


# ──────────────────────────────────────────────
# 2. NORMALISATION DES DATES
# ──────────────────────────────────────────────

DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",   # 16/04/2026
    "%Y-%m-%d",                             # 2026-04-16
    "%d/%m/%y", "%d-%m-%y",                # 16/04/26
    "%b %d, %Y", "%B %d, %Y",              # Apr 16, 2026
    "%d %B %Y", "%d %b %Y",               # 16 avril 2026
]

def normalize_date(value: str | None) -> str | None:
    """
    Normalise toute date en format ISO : YYYY-MM-DD.
    Retourne None si non parseable.
    """
    if not value:
        return None
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None  # Format non reconnu → revue manuelle


# ──────────────────────────────────────────────
# 3. NORMALISATION DU SIRET
# ──────────────────────────────────────────────

def normalize_siret(value: str | None) -> str | None:
    """
    Nettoie et valide un SIRET (14 chiffres) ou SIREN (9 chiffres).
    Retourne None si invalide.
    """
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) in (9, 14):
        return digits
    return None


# ──────────────────────────────────────────────
# 4. DÉTECTION DE DOUBLONS PAR HASH
# ──────────────────────────────────────────────

def compute_document_hash(numero: str, montant_ttc: float, date: str) -> str:
    """
    Génère un hash unique basé sur les 3 champs clés du document.
    Si le hash existe déjà dans Airtable → doublon détecté → rejet.
    Stratégie : SHA256 sur la concaténation normalisée des 3 valeurs.
    """
    raw = f"{str(numero).upper().strip()}|{montant_ttc}|{date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]  # 16 chars suffisent


# ──────────────────────────────────────────────
# 5. VALIDATION DES CHAMPS OBLIGATOIRES
# ──────────────────────────────────────────────

CHAMPS_OBLIGATOIRES = ["numero_document", "date", "montant_ttc"]

def validate_fields(champs: dict) -> list[str]:
    """
    Retourne la liste des champs obligatoires manquants.
    Liste vide = document valide pour push Airtable.
    """
    manquants = []
    for champ in CHAMPS_OBLIGATOIRES:
        if not champs.get(champ):
            manquants.append(champ)
    return manquants


# ──────────────────────────────────────────────
# 6. FONCTION PRINCIPALE
# ──────────────────────────────────────────────

def normalize(extracted: dict) -> dict:
    """
    Point d'entrée : reçoit la sortie brute de extractor.py ou vision.py.
    Retourne un objet normalisé prêt pour Airtable.
    """
    champs = extracted.get("champs", {})

    # Normalisation de chaque champ
    numero      = str(champs.get("numero_document", "")).strip() or None
    date_norm   = normalize_date(champs.get("date"))
    montant_ht  = normalize_amount(champs.get("montant_ht"))
    montant_ttc = normalize_amount(champs.get("montant_ttc"))
    tva         = champs.get("tva")
    siret       = normalize_siret(champs.get("siret"))

    # Validation
    champs_normalises = {
        "numero_document": numero,
        "date":            date_norm,
        "montant_ht":      montant_ht,
        "montant_ttc":     montant_ttc,
        "tva":             tva,
        "siret":           siret,
    }
    champs_manquants = validate_fields(champs_normalises)

    # Hash de déduplication (seulement si les 3 champs clés sont présents)
    document_hash = None
    if numero and montant_ttc and date_norm:
        document_hash = compute_document_hash(numero, montant_ttc, date_norm)

    # Statut final
    if champs_manquants:
        status = "incomplet"
    elif extracted.get("score_confiance", 0) < 70:
        status = "low_confidence"
    else:
        status = "pret"  # Prêt pour push Airtable

    return {
        "fichier":          extracted.get("fichier"),
        "status":           status,
        "source":           extracted.get("source", "pdfplumber"),
        "type_document":    extracted.get("type_document", "inconnu"),
        "score_confiance":  extracted.get("score_confiance", 0),
        "document_hash":    document_hash,
        "champs_manquants": champs_manquants,
        "champs": champs_normalises,
        "detail":           extracted.get("detail", {}),
    }


# ──────────────────────────────────────────────
# 7. POINT D'ENTRÉE POUR TEST RAPIDE
# ──────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python src/normalizer.py <fichier_json>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Fichier introuvable : {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    result = normalize(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))