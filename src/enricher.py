"""
Enrichissement des données via APIs externes.
- entreprise.data.gouv.fr → informations légales depuis SIRET
- VAT API → validation numéro TVA intracommunautaire
"""

import json
import re
import sys
import requests
from pathlib import Path


# ──────────────────────────────────────────────
# 1. CONFIGURATION
# ──────────────────────────────────────────────

API_SIRENE_URL  = "https://recherche-entreprises.api.gouv.fr/search"
API_SIRET_URL   = "https://recherche-entreprises.api.gouv.fr/search"
TIMEOUT_SECONDS = 10


# ──────────────────────────────────────────────
# 2. ENRICHISSEMENT SIRET → ENTREPRISE
# ──────────────────────────────────────────────

def enrich_from_siret(siret: str) -> dict:
    """
    Appelle l'API entreprise.data.gouv.fr avec le SIRET.
    Retourne les informations légales de l'entreprise.
    Gère proprement les SIRET fictifs ou introuvables.
    """
    if not siret:
        return {"status": "absent", "message": "Aucun SIRET fourni"}

    # Nettoyage
    siret_clean = re.sub(r"\D", "", siret)

    if len(siret_clean) not in (9, 14):
        return {"status": "invalide", "message": f"Format SIRET invalide : {siret}"}

    try:
        response = requests.get(
            API_SIRENE_URL,
            params={"q": siret_clean, "per_page": 1},
            timeout=TIMEOUT_SECONDS,
        )

        if response.status_code == 404:
            return {
                "status":  "non_trouve",
                "message": f"SIRET {siret_clean} introuvable dans la base Sirene",
            }

        if response.status_code != 200:
            return {
                "status":  "erreur_api",
                "message": f"API Sirene : HTTP {response.status_code}",
            }

        data = response.json()
        resultats = data.get("results", [])

        if not resultats:
            return {
                "status":  "non_trouve",
                "message": f"SIRET {siret_clean} introuvable dans la base Sirene",
            }

        entreprise = resultats[0]

        # Extraction des champs utiles
        siege = entreprise.get("siege", {})

        return {
            "status":           "trouve",
            "siret":            siret_clean,
            "siren":            siret_clean[:9],
            "nom_legal":        entreprise.get("nom_raison_sociale"),
            "nom_commercial":   entreprise.get("nom_commercial"),
            "forme_juridique":  entreprise.get("forme_juridique"),
            "tranche_effectif": entreprise.get("tranche_effectif_salarie"),
            "date_creation":    entreprise.get("date_creation"),
            "etat":             entreprise.get("etat_administratif"),  # A=Actif, C=Cessé
            "adresse": {
                "rue":         siege.get("libelle_voie"),
                "code_postal": siege.get("code_postal"),
                "ville":       siege.get("libelle_commune"),
                "pays":        "France",
            },
        }

    except requests.exceptions.Timeout:
        return {"status": "timeout", "message": "API Sirene : délai dépassé"}

    except requests.exceptions.ConnectionError:
        return {"status": "erreur_reseau", "message": "Impossible de joindre l'API Sirene"}

    except Exception as e:
        return {"status": "erreur_inconnue", "message": str(e)}


# ──────────────────────────────────────────────
# 3. VALIDATION NUMÉRO TVA INTRACOMMUNAUTAIRE
# ──────────────────────────────────────────────

def validate_tva_number(numero_tva: str) -> dict:
    """
    Valide un numéro TVA intracommunautaire.
    Format FR : FR + 2 caractères + 9 chiffres SIREN → ex: FR12345678901
    Validation locale (format) — pas d'appel API pour simplifier.
    """
    if not numero_tva:
        return {"status": "absent", "valide": False}

    cleaned = re.sub(r"\s", "", numero_tva).upper()

    # Format FR : FR + 2 chars + 9 chiffres
    if re.match(r"^FR[A-Z0-9]{2}\d{9}$", cleaned):
        return {"status": "valide", "valide": True, "numero": cleaned}

    # Format générique européen : 2 lettres pays + 8-12 chars
    if re.match(r"^[A-Z]{2}[A-Z0-9]{8,12}$", cleaned):
        return {"status": "valide", "valide": True, "numero": cleaned}

    return {"status": "invalide", "valide": False, "numero": cleaned}


# ──────────────────────────────────────────────
# 4. FONCTION PRINCIPALE
# ──────────────────────────────────────────────

def enrich(normalized: dict) -> dict:
    """
    Point d'entrée : reçoit la sortie de normalizer.py.
    Enrichit avec les données légales et retourne l'objet complet.
    """
    champs  = normalized.get("champs", {})
    detail  = normalized.get("detail", {})
    emetteur = detail.get("emetteur", {}) or {}

    siret      = champs.get("siret")
    numero_tva = emetteur.get("numero_tva")

    # Enrichissement
    enrichissement_siret = enrich_from_siret(siret)
    enrichissement_tva   = validate_tva_number(numero_tva)

    # Ajout à l'objet normalisé
    normalized["enrichissement"] = {
        "entreprise": enrichissement_siret,
        "tva":        enrichissement_tva,
    }

    # Si l'entreprise est trouvée, on complète l'émetteur
    if enrichissement_siret.get("status") == "trouve":
        emetteur["nom_legal"]       = enrichissement_siret.get("nom_legal")
        emetteur["forme_juridique"] = enrichissement_siret.get("forme_juridique")
        emetteur["adresse_legale"]  = enrichissement_siret.get("adresse")
        emetteur["etat"]            = enrichissement_siret.get("etat")
        detail["emetteur"] = emetteur
        normalized["detail"] = detail

    return normalized


# ──────────────────────────────────────────────
# 5. POINT D'ENTRÉE POUR TEST RAPIDE
# ──────────────────────────────────────────────

if __name__ == "__main__":
    """
    Usage : python src/enricher.py <fichier_json>
    Le fichier JSON doit être la sortie de normalizer.py.
    """
    if len(sys.argv) < 2:
        print("Usage : python src/enricher.py <fichier_json>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Fichier introuvable : {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    result = enrich(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))