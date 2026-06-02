#!/usr/bin/env python3
"""
Создаёт отформатированный Google Doc с письмами воронки.

УСТАНОВКА:
    pip install google-api-python-client google-auth-oauthlib google-auth-httplib2 python-dotenv

ИСПОЛЬЗОВАНИЕ:
    # Создать новый документ из .md файла:
    python3 create_voronka_gdoc.py --file ../письма-для-воронки/чат-боты-практикум/2026-03_чат-боты-практикум_voronka_doc.md

    # Обновить текст существующего документа из .md файла (основной режим при правках):
    python3 create_voronka_gdoc.py --file путь/к/файлу.md --doc-id 1FIl7KvSWQKiDoypMqkqsVICOO0UKpfmieqzF_3Ti8bk

    # Переформатировать существующий документ (только стили, текст не трогает):
    python3 create_voronka_gdoc.py --doc-id 1FIl7KvSWQKiDoypMqkqsVICOO0UKpfmieqzF_3Ti8bk

    # Создать новый с кастомным заголовком:
    python3 create_voronka_gdoc.py --file путь/к/файлу.md --title "Название документа"

НАСТРОЙКА credentials.json (один раз):
    1. console.cloud.google.com → создать проект
    2. APIs & Services → Enable: Google Docs API + Google Drive API
    3. Credentials → Create OAuth 2.0 Client ID → Desktop app → скачать JSON
    4. Сохранить как scripts/credentials.json
    5. Запустить скрипт — браузер откроется один раз для авторизации
"""

import os
import re
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

SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']
SCRIPT_DIR = Path(__file__).parent

# Цвета
LIGHT_GREEN_BG = {'red': 0.851, 'green': 0.918, 'blue': 0.827}   # #D9EAD3
GREY_FG        = {'red': 0.6,   'green': 0.6,   'blue': 0.6}
RED_FG         = {'red': 0.8,   'green': 0.0,   'blue': 0.0}
BLACK_FG       = {'red': 0.0,   'green': 0.0,   'blue': 0.0}

# Паттерны классификации абзацев
RE_HEADER = re.compile(
    r'^(?:письмо|ПИСЬМО)\s+[\d\.]+',
    re.IGNORECASE
)
RE_SUBJECT = re.compile(r'^Тема\s*:')
RE_IMPORTANT = re.compile(
    r'^\[Сегодня\]'
    r'|^15 минут до'
    r'|^Не хотим начинать'
    r'|^Мы в эфире'
    r'|^НАЧАЛИ ПРАКТИКУ'
    r'|^Эфир начинается'
    r'|^Уже начинаем эфир'
    r'|^✅\s*ОТПРАВЛЯЕМ'
    r'|^Ты узнаешь и увидишь'
    r'|^🎁\s*ВСЕМ'
    r'|^А также поговорим'
    r'|^Поговорим:'
)
# CTA: вся строка — фраза-кнопка в квадратных скобках (любой регистр):
# [ПЕРЕЙТИ В КОМНАТУ], [Перейти в телеграм], [Перейти в макс] и т.п.
# [Сегодня] перехватывается раньше (RE_IMPORTANT), заглушки [ВСТАВИТЬ … — …] не матчат (тире).
RE_CTA = re.compile(r'^\[[А-ЯЁA-Zа-яёa-z][А-ЯЁA-Zа-яёa-z\s]+\]$')
# CTA в боте: строка-призыв, заканчивающаяся на «👉 ссылка»
RE_CTA_BOT = re.compile(r'👉\s*ссылка\s*[!.?]*\s*$')
RE_AD = re.compile(r'^РЕКЛАМА\s+ООО|^ИНН\s*\d')


def utf16_len(text: str) -> int:
    return sum(2 if ord(c) > 0xFFFF else 1 for c in text)


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
                print("   Google Cloud Console → APIs → Create OAuth Client ID → Desktop app")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())
    return creds


def classify_paragraph(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return 'empty'
    if RE_HEADER.match(stripped):
        return 'header'
    if RE_SUBJECT.match(stripped):
        return 'subject'
    if RE_IMPORTANT.match(stripped):
        return 'important'
    if RE_CTA.match(stripped):
        return 'cta'
    if RE_CTA_BOT.search(stripped):
        return 'cta'
    if RE_AD.match(stripped):
        return 'ad'
    if stripped.endswith(':') and len(stripped) > 2:
        return 'subheading'
    return 'normal'


def build_format_requests(doc: dict) -> list:
    requests = []
    body = doc.get('body', {}).get('content', [])
    if not body:
        return requests

    doc_end = body[-1]['endIndex']

    # Собираем абзацы с их позициями из структуры документа
    paragraphs = []
    for el in body:
        if 'paragraph' not in el:
            continue
        start = el.get('startIndex', 0)
        end = el.get('endIndex', 0)
        text = ''.join(
            run['textRun']['content']
            for run in el['paragraph'].get('elements', [])
            if 'textRun' in run
        )
        paragraphs.append((start, end, text))

    # ── 1. Базовый стиль текста: Arial 11pt, чёрный, без выделения ────────
    requests.append({'updateTextStyle': {
        'range': {'startIndex': 1, 'endIndex': doc_end},
        'textStyle': {
            'weightedFontFamily': {'fontFamily': 'Arial', 'weight': 400},
            'fontSize': {'magnitude': 11, 'unit': 'PT'},
            'foregroundColor': {'color': {'rgbColor': BLACK_FG}},
            'bold': False,
            'italic': False,
            'backgroundColor': {},
        },
        'fields': 'weightedFontFamily,fontSize,foregroundColor,bold,italic,backgroundColor'
    }})

    # ── 2. Базовый стиль абзацев: межстрочный 1.15, отступы 0, по левому ──
    requests.append({'updateParagraphStyle': {
        'range': {'startIndex': 1, 'endIndex': doc_end},
        'paragraphStyle': {
            'lineSpacing': 115,
            'spaceAbove': {'magnitude': 0, 'unit': 'PT'},
            'spaceBelow': {'magnitude': 0, 'unit': 'PT'},
            'alignment': 'START',
        },
        'fields': 'lineSpacing,spaceAbove,spaceBelow,alignment'
    }})

    # ── 3. Форматирование каждого абзаца ──────────────────────────────────
    first_header = True
    after_header = False

    for para_start, para_end, para_text in paragraphs:
        stripped = para_text.strip()
        # text_end: позиция до завершающего \n абзаца
        text_end = para_end - 1
        has_content = text_end > para_start

        if not has_content or not stripped:
            continue

        kind = classify_paragraph(stripped)

        # Первая строка после заголовка письма → 12pt жирный
        if kind != 'header':
            if after_header and kind == 'normal':
                kind = 'important'
            after_header = False

        if kind == 'header':
            # 14pt, жирный, чёрный, светло-зелёный фон
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {
                    'weightedFontFamily': {'fontFamily': 'Arial', 'weight': 700},
                    'fontSize': {'magnitude': 14, 'unit': 'PT'},
                    'bold': True,
                    'foregroundColor': {'color': {'rgbColor': BLACK_FG}},
                    'backgroundColor': {'color': {'rgbColor': LIGHT_GREEN_BG}},
                },
                'fields': 'weightedFontFamily,fontSize,bold,foregroundColor,backgroundColor'
            }})
            first_header = False
            after_header = True

        elif kind in ('subject', 'important'):
            # 12pt, жирный
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {
                    'fontSize': {'magnitude': 12, 'unit': 'PT'},
                    'bold': True,
                },
                'fields': 'fontSize,bold'
            }})

        elif kind == 'subheading':
            # жирный, размер не меняется
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {'bold': True},
                'fields': 'bold'
            }})

        elif kind == 'cta':
            # 12pt, жирный
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {
                    'fontSize': {'magnitude': 12, 'unit': 'PT'},
                    'bold': True,
                },
                'fields': 'fontSize,bold'
            }})

        elif kind == 'ad':
            # 9pt, серый, не жирный
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {
                    'fontSize': {'magnitude': 9, 'unit': 'PT'},
                    'bold': False,
                    'foregroundColor': {'color': {'rgbColor': GREY_FG}},
                },
                'fields': 'fontSize,bold,foregroundColor'
            }})

        # {first_name}: красный + жирный — ищем внутри каждого абзаца
        for m in re.finditer(r'\{first_name\}', para_text):
            offset = utf16_len(para_text[:m.start()])
            fn_start = para_start + offset
            fn_end = fn_start + utf16_len(m.group())
            if fn_end > fn_start:
                requests.append({'updateTextStyle': {
                    'range': {'startIndex': fn_start, 'endIndex': fn_end},
                    'textStyle': {
                        'bold': True,
                        'foregroundColor': {'color': {'rgbColor': RED_FG}},
                    },
                    'fields': 'bold,foregroundColor'
                }})

    return requests


def apply_formatting(docs, doc_id: str) -> int:
    doc = docs.documents().get(documentId=doc_id).execute()
    fmt = build_format_requests(doc)
    total = len(fmt)
    for i in range(0, total, 500):
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': fmt[i:i+500]}
        ).execute()
    print(f"🎨 Форматирование: {total} правил применено")
    return total


def move_to_folder(drive, doc_id: str, folder_id: str):
    drive.files().update(
        fileId=doc_id,
        addParents=folder_id,
        removeParents='root',
        fields='id, parents'
    ).execute()
    print(f"📁 Документ добавлен в папку: {folder_id}")


def create_doc(md_path: str = None, title: str = None, doc_id: str = None, folder_id: str = None) -> str:
    creds = get_credentials()
    docs = build('docs', 'v1', credentials=creds)

    if doc_id and md_path:
        # Обновить текст существующего документа + переформатировать
        src = Path(md_path)
        text = src.read_text(encoding='utf-8')
        print(f"📄 Обновление документа: {doc_id}")

        existing = docs.documents().get(documentId=doc_id).execute()
        body = existing.get('body', {}).get('content', [])
        doc_end = body[-1]['endIndex']

        requests = []
        if doc_end > 2:
            requests.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': doc_end - 1}}})
        requests.append({'insertText': {'location': {'index': 1}, 'text': text}})
        docs.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
        print("✏️  Текст обновлён")

        apply_formatting(docs, doc_id)

    elif doc_id:
        # Переформатировать существующий документ (только стили)
        print(f"📄 Форматирование документа: {doc_id}")
        apply_formatting(docs, doc_id)

    else:
        # Создать новый документ из .md файла
        src = Path(md_path)
        text = src.read_text(encoding='utf-8')
        title = title or src.stem.replace('_', ' ')

        doc = docs.documents().create(body={'title': title}).execute()
        doc_id = doc['documentId']
        print(f"📄 Документ создан: {doc_id}")

        docs.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': [{'insertText': {'location': {'index': 1}, 'text': text}}]}
        ).execute()
        print("✏️  Текст вставлен")

        apply_formatting(docs, doc_id)

        if folder_id:
            drive = build('drive', 'v3', credentials=creds)
            move_to_folder(drive, doc_id, folder_id)

        # Сохранить ссылку рядом с файлом
        link_file = src.parent / 'google-doc-link.txt'
        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        link_file.write_text(f"ID: {doc_id}\nURL: {url}\n", encoding='utf-8')
        print(f"💾 Ссылка сохранена: {link_file}")

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    print(f"\n✅ Готово: {url}")
    return url


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Создать или переформатировать Google Doc с письмами воронки'
    )
    parser.add_argument('--file', default=None,
                        help='Путь к .md файлу с письмами (обязателен при создании нового)')
    parser.add_argument('--title', default=None,
                        help='Название Google Doc (только при создании нового)')
    parser.add_argument('--doc-id', default=None,
                        help='ID существующего Google Doc для переформатирования')
    parser.add_argument('--folder-id', default=None,
                        help='ID Google Drive папки — документ будет перемещён туда после создания')
    args = parser.parse_args()

    if not args.file and not args.doc_id:
        parser.error("Нужно указать --file (создать новый), --doc-id (переформатировать) или оба (обновить текст существующего)")

    create_doc(args.file, args.title, args.doc_id, args.folder_id)
