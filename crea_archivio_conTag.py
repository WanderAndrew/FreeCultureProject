import os
import pickle
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


# === CONFIGURAZIONE ===
# Se modifichi questi scope, elimina il file token.pickle
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
# Nome della cartella da cui partire (case-insensitive)
TARGET_FOLDER_NAME = "Appunti FreeCultureProject"
# Nome del file output
OUTPUT_FILE = "archivio.json"


def authenticate_drive():
    """
    Faccio l'autenticazione per l'API Google Drive usando OAuth2.
    - Se esiste token.pickle e non è scaduto, lo ricarica.
    - Altrimenti avvia il flow di autorizzazione.
    - Salva il token aggiornato in token.pickle.

    """

    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds


def get_drive_service():
    """Crea il servizio per interagire con l'API di Google Drive."""
    creds = authenticate_drive()
    return build('drive', 'v3', credentials=creds)


def build_and_tag_tree(service, folder_id, percorso=None):
    """
    Costruisce un albero ricorsivo di:
      - files: lista di dict {titolo, link, tag}
      - subfolders: dict di sottocartelle
    Aggiunge a ogni file un campo "tag" basato sul percorso (escludendo la root).

    """

    if percorso is None:
        percorso = []

    tree = {"files": [], "subfolders": {}}
    page_token = None

    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            spaces='drive',
            fields="nextPageToken, files(id, name, mimeType)",
            pageToken=page_token
        ).execute()
        for item in resp.get('files', []):
            if item['mimeType'] == 'application/vnd.google-apps.folder':
                # cartella
                tree['subfolders'][item['name']] = build_and_tag_tree(
                    service, item['id'], percorso + [item['name']])
            else:
                # file
                link = f"https://drive.google.com/file/d/{item['id']}/view?usp=sharing"
                # tag escludendo la root
                tag = percorso.copy()
                tree['files'].append({
                    "titolo": item['name'],
                    "link": link,
                    "tag": tag
                })
        page_token = resp.get('nextPageToken')
        if not page_token:
            break

    return tree


def main():
    # Autenticazione e creazione service
    service = get_drive_service()

    # 1) Trovo la cartella principale nella root di Drive (TARGET_FOLDER_NAME)
    query = (
        "mimeType = 'application/vnd.google-apps.folder' and "
        f"name = '{TARGET_FOLDER_NAME}' and 'root' in parents and trashed = false"
    )
    resp = service.files().list(q=query, spaces='drive',
                                fields="files(id,name)").execute()
    folders = resp.get('files', [])
    if not folders:
        print(f"❌ Cartella '{TARGET_FOLDER_NAME}' non trovata.")
        return

    root = folders[0]
    print(f"✅ Cartella trovata: {root['name']} (ID: {root['id']})")

    # 2) Costruisco l’albero con i tag
    tree = build_and_tag_tree(service, root['id'])

    # 3) Lo Incorporo nella chiave principale
    archivio = {root['name']: tree}

    # 4) Salva in "archivio.json"
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(archivio, f, ensure_ascii=False, indent=4)

    print(f"✅ '{OUTPUT_FILE}' generato con successo!")


if __name__ == '__main__':
    main()
