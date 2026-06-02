#!/usr/bin/env python3
"""
Создаёт папку в Google Drive для мероприятия.
Сохраняет ID и ссылку в google-drive-folder.txt рядом с указанной папкой.

ИСПОЛЬЗОВАНИЕ:
    python3 scripts/create_drive_folder.py --name "Практикум по презентациям с ИИ — 3 марта"
    python3 scripts/create_drive_folder.py --name "..." --save-to письма-для-воронки/Зерокодер/название/
"""

import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("❌ pip install google-api-python-client google-auth-oauthlib google-auth-httplib2")
    sys.exit(1)

SCOPES     = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']
SCRIPT_DIR = Path(__file__).resolve().parent


def get_credentials() -> Credentials:
    creds = None
    token_path = SCRIPT_DIR / 'token.json'
    creds_path = Path(os.getenv('GOOGLE_CREDENTIALS_PATH', str(SCRIPT_DIR / 'credentials.json')))

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                print(f"❌ credentials.json не найден: {creds_path}")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())
    return creds


def create_folder(name: str, save_to: str = None) -> tuple:
    creds  = get_credentials()
    drive  = build('drive', 'v3', credentials=creds)

    folder = drive.files().create(
        body={'name': name, 'mimeType': 'application/vnd.google-apps.folder'},
        fields='id'
    ).execute()
    folder_id = folder.get('id')
    url = f"https://drive.google.com/drive/folders/{folder_id}"

    print(f"📁 Папка создана: {name}")
    print(f"✅ Готово: {url}")

    if save_to:
        link_file = Path(save_to) / 'google-drive-folder.txt'
        link_file.parent.mkdir(parents=True, exist_ok=True)
        link_file.write_text(f"ID: {folder_id}\nURL: {url}\n", encoding='utf-8')
        print(f"💾 Ссылка сохранена: {link_file}")

    return folder_id, url


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Создать папку в Google Drive для мероприятия')
    parser.add_argument('--name',    required=True, help='Название папки')
    parser.add_argument('--save-to', default=None,  help='Путь для сохранения google-drive-folder.txt')
    args = parser.parse_args()

    folder_id, url = create_folder(args.name, args.save_to)
    print(f"\nFolder ID: {folder_id}")
