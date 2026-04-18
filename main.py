# main.py
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import tempfile
import os
import httpx
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


# ──────────────────────────────────────────────
# 1. HEALTH CHECK
# ──────────────────────────────────────────────

@app.get("/")
def health_check():
    return {"status": "ok", "service": "DocFlow API"}


# ──────────────────────────────────────────────
# 2. ENDPOINT UPLOAD DIRECT (PDF ou image)
# ──────────────────────────────────────────────

@app.post("/process")
async def process_document(file: UploadFile = File(...)):
    """
    Endpoint principal — reçoit un fichier (PDF ou image),
    exécute le pipeline complet et pousse dans Airtable.
    """
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

    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        if file.content_type == "application/pdf":
            extracted = extract_from_pdf(tmp_path)
            if extracted.get("status") == "scan_detected":
                extracted = extract_from_vision(tmp_path)
        else:
            extracted = extract_from_vision(tmp_path)

        normalized = normalize(extracted)
        enriched = enrich(normalized)
        result = push_to_airtable(enriched)

        return JSONResponse(content={
            "status":   "succes",
            "fichier":  file.filename,
            "type":     enriched.get("type_document"),
            "score":    enriched.get("score_confiance"),
            "airtable": result,
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        os.unlink(tmp_path)


# ──────────────────────────────────────────────
# 3. ENDPOINT URL (pour n8n — télécharge depuis Gmail)
# ──────────────────────────────────────────────

@app.post("/process_url")
async def process_from_url(data: dict):
    """
    Reçoit une URL de fichier + token Gmail → télécharge et traite.
    Utilisé par n8n qui ne peut pas envoyer de binaires directement.
    
    Body JSON attendu :
    {
        "url": "https://...",
        "filename": "facture.pdf",
        "token": "ya29.xxx"  (optionnel)
    }
    """
    file_url = data.get("url")
    filename = data.get("filename", "document.pdf")
    token = data.get("token")

    if not file_url:
        raise HTTPException(status_code=400, detail="Champ 'url' manquant")

    # Téléchargement du fichier
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(file_url, headers=headers)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Impossible de télécharger le fichier : HTTP {response.status_code}"
                )
            content = response.content
    except httpx.TimeoutException:
        raise HTTPException(status_code=408, detail="Timeout lors du téléchargement")

    # Sauvegarde temporaire
    suffix = Path(filename).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Détection du type par extension
        if suffix.lower() in [".pdf"]:
            extracted = extract_from_pdf(tmp_path)
            if extracted.get("status") == "scan_detected":
                extracted = extract_from_vision(tmp_path)
        elif suffix.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
            extracted = extract_from_vision(tmp_path)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Extension non supportée : {suffix}"
            )

        normalized = normalize(extracted)
        enriched = enrich(normalized)
        result = push_to_airtable(enriched)

        return JSONResponse(content={
            "status":   "succes",
            "fichier":  filename,
            "type":     enriched.get("type_document"),
            "score":    enriched.get("score_confiance"),
            "airtable": result,
        })

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        os.unlink(tmp_path)