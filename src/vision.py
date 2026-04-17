# src/vision.py
"""
Extraction de données via Claude Vision API.
Gère les PDF scannés et les images (JPG, PNG, WEBP, GIF).
Appelé par extractor.py quand aucun texte natif n'est détecté.
"""

import anthropic
import base64
import json
import re
import sys
from pathlib import Path


# ──────────────────────────────────────────────
# 1. CONFIGURATION
# ──────────────────────────────────────────────

MODEL = "claude-opus-4-5"  # Vision disponible sur tous les modèles récents

SUPPORTED_IMAGE_TYPES = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}

SUPPORTED_PDF_TYPES = {".pdf": "application/pdf"}

# Seuil de confiance minimal pour considérer l'extraction valide
CONFIDENCE_THRESHOLD = 70


# ──────────────────────────────────────────────
# 2. PROMPT D'EXTRACTION STRUCTURÉ
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un expert en extraction de données documentaires.
Tu analyses des documents financiers et commerciaux (factures, bons de commande, contrats).
Tu réponds UNIQUEMENT en JSON valide, sans markdown, sans texte autour."""

def build_extraction_prompt(file_type_hint: str = "inconnu") -> str:
    return f"""Analyse ce document et extrait les informations structurées.

Type de fichier détecté : {file_type_hint}

Réponds avec ce JSON exact (null si le champ est absent ou illisible) :
{{
  "type_document": "facture | bon_de_commande | contrat | inconnu",
  "numero_document": "string ou null",
  "date": "JJ/MM/AAAA ou null",
  "emetteur": {{
    "nom": "string ou null",
    "siret": "14 chiffres sans espaces ou null",
    "adresse": "string ou null",
    "numero_tva": "string ou null"
  }},
  "destinataire": {{
    "nom": "string ou null",
    "adresse": "string ou null"
  }},
  "montant_ht": "nombre décimal string (ex: '1878.99') ou null",
  "taux_tva": "nombre entier string (ex: '20') ou null",
  "montant_tva": "nombre décimal string ou null",
  "montant_ttc": "nombre décimal string ou null",
  "devise": "EUR | USD | GBP | autre ou null",
  "lignes_detail": [
    {{"description": "string", "quantite": "string", "prix_unitaire": "string", "total": "string"}}
  ],
  "problemes_detectes": ["liste des problèmes : mauvaise orientation, qualité faible, texte tronqué, etc."],
  "score_confiance": 0
}}

Pour score_confiance : compte le % de champs non-null parmi [numero_document, date, montant_ttc, emetteur.nom, emetteur.siret].
Attribue 0 si le document est illisible, 100 si tout est présent et clair.
"""


# ──────────────────────────────────────────────
# 3. CHARGEMENT ET ENCODAGE DU FICHIER
# ──────────────────────────────────────────────

def load_file_as_base64(file_path: Path) -> tuple[str, str]:
    """
    Retourne (base64_data, media_type).
    Lève ValueError si le format n'est pas supporté.
    """
    suffix = file_path.suffix.lower()

    if suffix in SUPPORTED_IMAGE_TYPES:
        media_type = SUPPORTED_IMAGE_TYPES[suffix]
    elif suffix in SUPPORTED_PDF_TYPES:
        media_type = SUPPORTED_PDF_TYPES[suffix]
    else:
        raise ValueError(
            f"Format non supporté : '{suffix}'. "
            f"Formats acceptés : {list(SUPPORTED_IMAGE_TYPES) + list(SUPPORTED_PDF_TYPES)}"
        )

    with open(file_path, "rb") as f:
        b64_data = base64.standard_b64encode(f.read()).decode("utf-8")

    return b64_data, media_type


# ──────────────────────────────────────────────
# 4. CONSTRUCTION DU MESSAGE ANTHROPIC
# ──────────────────────────────────────────────

def build_message_content(b64_data: str, media_type: str, file_type_hint: str) -> list:
    """
    Construit le contenu du message selon le type (image vs PDF).
    L'API Anthropic utilise 'document' pour les PDFs et 'image' pour les images.
    """
    prompt_text = build_extraction_prompt(file_type_hint)

    if media_type == "application/pdf":
        return [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64_data,
                },
            },
            {"type": "text", "text": prompt_text},
        ]
    else:
        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64_data,
                },
            },
            {"type": "text", "text": prompt_text},
        ]


# ──────────────────────────────────────────────
# 5. PARSING ET VALIDATION DE LA RÉPONSE
# ──────────────────────────────────────────────

def parse_claude_response(raw_text: str) -> dict:
    """
    Parse la réponse JSON de Claude.
    Gère les cas où le modèle ajoute du markdown malgré les instructions.
    """
    # Nettoyer les éventuelles balises markdown
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Tentative de récupération : extraire le premier bloc JSON trouvé
        json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Réponse Claude non parseable : {e}\n---\n{raw_text[:500]}")


def normalize_extracted_data(raw: dict, file_name: str) -> dict:
    """
    Convertit la réponse Claude au format unifié utilisé par normalizer.py.
    Compatible avec la sortie de extractor.py.
    """
    champs = raw.get("champs_bruts", raw)  # Compatibilité double format

    # Normalisation des montants (virgule → point pour les floats)
    def clean_amount(val):
        if val is None:
            return None
        return str(val).replace(" ", "").replace(",", ".")

    emetteur = raw.get("emetteur", {}) or {}

    return {
        "fichier":         file_name,
        "status":          "extracted" if raw.get("score_confiance", 0) >= CONFIDENCE_THRESHOLD else "low_confidence",
        "source":          "vision",
        "type_document":   raw.get("type_document", "inconnu"),
        "score_confiance": raw.get("score_confiance", 0),
        "champs": {
            "numero_document": raw.get("numero_document"),
            "date":            raw.get("date"),
            "montant_ht":      clean_amount(raw.get("montant_ht")),
            "montant_ttc":     clean_amount(raw.get("montant_ttc")),
            "tva":             raw.get("taux_tva"),
            "siret":           emetteur.get("siret"),
        },
        "detail": {
            "emetteur":         emetteur,
            "destinataire":     raw.get("destinataire", {}),
            "devise":           raw.get("devise", "EUR"),
            "lignes_detail":    raw.get("lignes_detail", []),
            "problemes":        raw.get("problemes_detectes", []),
        },
    }


# ──────────────────────────────────────────────
# 6. FONCTION PRINCIPALE
# ──────────────────────────────────────────────

def extract_from_vision(file_path: str) -> dict:
    """
    Point d'entrée principal.
    Accepte PDF scanné ou image (JPG, PNG, WEBP, GIF).
    Retourne un dict au format normalisé compatible avec normalizer.py.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {file_path}")

    # Chargement et encodage
    b64_data, media_type = load_file_as_base64(path)
    file_type_hint = f"{path.suffix.upper().lstrip('.')} ({'PDF scanné' if media_type == 'application/pdf' else 'image'})"

    # Construction du message
    message_content = build_message_content(b64_data, media_type, file_type_hint)

    # Appel Claude API
    client = anthropic.Anthropic()  # Utilise ANTHROPIC_API_KEY depuis l'environnement

    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": message_content}
        ],
    )

    raw_text = response.content[0].text

    # Parsing et normalisation
    parsed = parse_claude_response(raw_text)
    result = normalize_extracted_data(parsed, path.name)

    # Ajout des méta-informations d'usage API
    result["api_usage"] = {
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "model":         MODEL,
    }

    return result


# ──────────────────────────────────────────────
# 7. POINT D'ENTRÉE POUR TEST RAPIDE
# ──────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage : python src/vision.py <chemin_fichier>")
        print("Formats : .pdf (scanné), .jpg, .jpeg, .png, .gif, .webp")
        sys.exit(1)

    result = extract_from_vision(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))