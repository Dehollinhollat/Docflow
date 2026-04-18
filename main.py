# main.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import tempfile
import os
from pathlib import Path
from dotenv import load_dotenv

from src.extractor import extract_from_pdf
from src.vision import extract_from_vision
from src.normalizer import normalize
from src.enricher import enrich
from src.airtable_client import push_to_airtable

load_dotenv()

app = FastAPI(
    title="DocFlow API",
    description="Pipeline intelligent de traitement de documents entrants",
    version="1.0.0"
)


@app.get("/")
def health_check():
    return {"status": "ok", "service": "DocFlow API"}


@app.post("/process")
async def process_document(file: UploadFile = File(...)):
    """
    Endpoint principal — reçoit un fichier (PDF ou image),
    exécute le pipeline complet et pousse dans Airtable.
    """

    # Vérification du type de fichier
    allowed_types = [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    ]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Type de fichier non supporté : {file.content_type}"
        )

    # Sauvegarde temporaire du fichier
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Étape 1 — Extraction
        if file.content_type == "application/pdf":
            extracted = extract_from_pdf(tmp_path)

            # Si PDF scanné → délégation à vision
            if extracted.get("status") == "scan_detected":
                extracted = extract_from_vision(tmp_path)
        else:
            extracted = extract_from_vision(tmp_path)

        # Étape 2 — Normalisation
        normalized = normalize(extracted)

        # Étape 3 — Enrichissement
        enriched = enrich(normalized)

        # Étape 4 — Push Airtable
        result = push_to_airtable(enriched)

        return JSONResponse(content={
            "status":       "succes",
            "fichier":      file.filename,
            "type":         enriched.get("type_document"),
            "score":        enriched.get("score_confiance"),
            "airtable":     result,
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Nettoyage du fichier temporaire
        os.unlink(tmp_path)