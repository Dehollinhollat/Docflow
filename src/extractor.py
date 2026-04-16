# src/extractor.py
import pdfplumber
import re
from pathlib import Path

# ──────────────────────────────────────────────
# 1. DÉTECTION DU TYPE DE DOCUMENT
# ──────────────────────────────────────────────

KEYWORDS = {
    "facture": ["facture", "invoice", "avoir", "note de débit"],
    "bon_de_commande": ["bon de commande", "purchase order", "ordre d'achat"],
    "contrat": ["contrat", "convention", "accord", "agreement"],
}

def detect_document_type(text: str) -> str:
    text_lower = text.lower()
    text_cleaned = re.sub(r"bon de commande\s*:", "", text_lower)
    scores = {doc_type: 0 for doc_type in KEYWORDS}
    first_line = text_cleaned.split("\n")[0]

    for doc_type, keywords in KEYWORDS.items():
        for kw in keywords:
            if kw in text_cleaned:
                scores[doc_type] += 1
            if kw in first_line:
                scores[doc_type] += 3

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "inconnu"


# ──────────────────────────────────────────────
# 2. EXTRACTION DES CHAMPS CLÉS PAR REGEX
# ──────────────────────────────────────────────

def find(pattern: str, text: str, group: int = 1):
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    value = match.group(group)
    if value is None:
        value = next((g for g in match.groups() if g is not None), None)
    return value.strip() if value else None


def extract_fields(text: str) -> dict:
    fields = {
        "numero_document": find(
            r"(?:#|facture|invoice|n°|number)[^\w]*([A-Z]{0,3}\-?\d{4}\-\d{4,6}|[A-Z0-9\-\/]{4,20})",
            text
        ),

        "date": find(
            r"(?:date\s*:?\s*)(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+\w+\s+\d{4})",
            text
        ),

        "montant_ht": find(
            r"(?:total\s*h\.?t\.?|sous[-\s]?total|subtotal|montant\s*ht)\s*:?\s*([\d\s]+[.,]\d{2})\s*€?",
            text
        ),

        "montant_ttc": find(
            r"(?:total\s*t\.?t\.?c\.?|solde\s*[àa]\s*payer|amount\s*due|^total)\s*:?\s*([\d\s]+[.,]\d{2})\s*€?",
            text
        ),

        "tva": find(
            r"(?:tva|imp[oô]t|tax)[^\d]{0,10}(\d{1,2})\s*%",
            text
        ),

        "siret": find(
            r"(?:(?:SIREN|SIRET)[^\d]*(\d{9}(?:\d{5})?))|(?<!\d)(\d{14})(?!\d)",
            text
        ),
    }

    if fields["siret"]:
        fields["siret"] = re.sub(r"\s", "", fields["siret"])

    return fields


# ──────────────────────────────────────────────
# 3. SCORE DE CONFIANCE
# ──────────────────────────────────────────────

CHAMPS_OBLIGATOIRES = ["numero_document", "date", "montant_ttc"]
CHAMPS_SECONDAIRES  = ["montant_ht", "tva", "siret"]

def compute_confidence(fields: dict) -> int:
    score = 0
    max_score = len(CHAMPS_OBLIGATOIRES) * 2 + len(CHAMPS_SECONDAIRES) * 1

    for champ in CHAMPS_OBLIGATOIRES:
        if fields.get(champ):
            score += 2

    for champ in CHAMPS_SECONDAIRES:
        if fields.get(champ):
            score += 1

    return round((score / max_score) * 100)


# ──────────────────────────────────────────────
# 4. FONCTION PRINCIPALE
# ──────────────────────────────────────────────

def extract_from_pdf(pdf_path: str) -> dict:
    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {pdf_path}")

    full_text = ""

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"

    if not full_text.strip():
        return {
            "fichier": path.name,
            "status": "scan_detected",
            "message": "Aucun texte natif détecté — délégation à vision.py",
        }

    doc_type = detect_document_type(full_text)
    fields   = extract_fields(full_text)
    score    = compute_confidence(fields)

    return {
        "fichier":         path.name,
        "status":          "extracted" if score >= 70 else "low_confidence",
        "type_document":   doc_type,
        "score_confiance": score,
        "champs":          fields,
        "texte_brut":      full_text[:1000],
    }


# ──────────────────────────────────────────────
# 5. POINT D'ENTRÉE POUR TEST RAPIDE
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage : python src/extractor.py <chemin_pdf>")
        sys.exit(1)

    result = extract_from_pdf(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))