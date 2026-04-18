# gmail_watcher.py
"""
Surveillance Gmail — détecte les nouveaux emails avec pièces jointes
et déclenche le pipeline DocFlow automatiquement.
"""

import os
import base64
import time
import json
import requests
from pathlib import Path
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

# ──────────────────────────────────────────────
# 1. CONFIGURATION
# ──────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
API_URL = os.getenv("DOCFLOW_API_URL", "http://localhost:8000")
CHECK_INTERVAL = 60
PROCESSED_IDS_FILE = "data/processed_ids.json"


# ──────────────────────────────────────────────
# 2. AUTHENTIFICATION GMAIL
# ──────────────────────────────────────────────

def get_gmail_service():
    creds = None
    if Path("token.json").exists():
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=8080)
        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ──────────────────────────────────────────────
# 3. GESTION DES IDS TRAITÉS
# ──────────────────────────────────────────────

def load_processed_ids() -> set:
    path = Path(PROCESSED_IDS_FILE)
    if path.exists():
        with open(path, "r") as f:
            return set(json.load(f))
    return set()


def save_processed_ids(ids: set):
    Path("data").mkdir(exist_ok=True)
    with open(PROCESSED_IDS_FILE, "w") as f:
        json.dump(list(ids), f)


# ──────────────────────────────────────────────
# 4. TRAITEMENT DES PIÈCES JOINTES
# ──────────────────────────────────────────────

EXTENSIONS_SUPPORTEES = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}


def process_attachment(service, message_id: str, attachment_id: str, filename: str) -> dict:
    attachment = service.users().messages().attachments().get(
        userId="me",
        messageId=message_id,
        id=attachment_id
    ).execute()

    file_data = base64.urlsafe_b64decode(attachment["data"])

    response = requests.post(
        f"{API_URL}/process_b64",
        json={
            "filename": filename,
            "data": base64.b64encode(file_data).decode()
        },
        timeout=300
    )

    return response.json()


# ──────────────────────────────────────────────
# 5. SURVEILLANCE GMAIL
# ──────────────────────────────────────────────

def check_new_emails(service, processed_ids: set) -> set:
    results = service.users().messages().list(
        userId="me",
        q="has:attachment is:unread",
        maxResults=10
    ).execute()

    messages = results.get("messages", [])

    for msg in messages:
        msg_id = msg["id"]
        if msg_id in processed_ids:
            continue

        message = service.users().messages().get(
            userId="me",
            id=msg_id
        ).execute()

        subject = next(
            (h["value"] for h in message["payload"]["headers"] if h["name"] == "Subject"),
            "Sans objet"
        )

        print(f"\n📧 Nouveau email : {subject}")

        parts = message["payload"].get("parts", [])
        for part in parts:
            filename = part.get("filename", "")
            if not filename:
                continue

            ext = Path(filename).suffix.lower()
            if ext not in EXTENSIONS_SUPPORTEES:
                print(f"  ⏭️  Ignoré : {filename} (extension non supportée)")
                continue

            attachment_id = part.get("body", {}).get("attachmentId")
            if not attachment_id:
                continue

            print(f"  📎 Traitement : {filename}")
            try:
                result = process_attachment(service, msg_id, attachment_id, filename)
                print(f"  ✅ Résultat : {result.get('status')} | type={result.get('type')} | score={result.get('score')}")
                print(f"  📊 Airtable : {result.get('airtable', {}).get('document', {}).get('status')}")
            except Exception as e:
                print(f"  ❌ Erreur : {e}")

        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()

        processed_ids.add(msg_id)

    return processed_ids


# ──────────────────────────────────────────────
# 6. BOUCLE PRINCIPALE
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("🚀 DocFlow Gmail Watcher démarré")
    print(f"📡 API : {API_URL}")
    print(f"⏱️  Vérification toutes les {CHECK_INTERVAL} secondes")
    print("Ctrl+C pour arrêter\n")

    service = get_gmail_service()
    processed_ids = load_processed_ids()

    try:
        while True:
            print("🔍 Vérification en cours...")
            processed_ids = check_new_emails(service, processed_ids)
            save_processed_ids(processed_ids)
            print(f"✓ Prochain check dans {CHECK_INTERVAL}s")
            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\n⏹️  Arrêt du watcher")
        save_processed_ids(processed_ids)