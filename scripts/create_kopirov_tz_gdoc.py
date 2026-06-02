#!/usr/bin/env python3
"""
Создаёт отформатированный Google Doc с ТЗ для копирайтера.

ИСПОЛЬЗОВАНИЕ:
    # Создать новый документ:
    python3 create_kopirov_tz_gdoc.py --file путь/к/файлу.md --title "Название"

    # Обновить существующий:
    python3 create_kopirov_tz_gdoc.py --file путь/к/файлу.md --doc-id [ID]

    # Переформатировать (только стили):
    python3 create_kopirov_tz_gdoc.py --doc-id [ID]
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

SCOPES     = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']
SCRIPT_DIR = Path(__file__).parent

# Цвета
RED_COLOR   = {'red': 0.8,   'green': 0.0,   'blue': 0.0}
GREEN_COLOR = {'red': 0.118, 'green': 0.482, 'blue': 0.204}
YELLOW_BG      = {'red': 1.0,   'green': 1.0,   'blue': 0.0}     # яркий — для Драфт
YELLOW_SOFT_BG = {'red': 1.0,   'green': 0.949, 'blue': 0.8}     # мягкий — для описаний писем
BLACK_FG    = {'red': 0.0,   'green': 0.0,   'blue': 0.0}

MAIN_HEADERS = {'ОБЩИЕ ВВОДНЫЕ', 'КАКИЕ ПИСЬМА НУЖНЫ'}

RE_DEADLINE    = re.compile(r'^Дедлайн\b')
RE_DESIGN_RED  = re.compile(r'^Важные поинты по дизайну')
RE_DRAFT_GREEN = re.compile(r'^Драфт нового письма')
RE_IMPORTANT   = re.compile(r'^Важно!!!')
RE_SEGMENT     = re.compile(r'^Сегмент (НЕЙРО|Технари)')
RE_TZ_LETTER   = re.compile(r'^\d+\.\s*ТЗ по письму')   # «1. ТЗ по письму» → красный
RE_ADAPT       = re.compile(r'^\+\s*адаптировать для канала')  # → жирный
RE_ONECLICK    = re.compile(r'1 клик', re.IGNORECASE)   # «все письма анонсы 1 клик» → жирный
RE_LETTER_DESC = re.compile(r'^\(')
RE_SUBSECTION  = re.compile(r'^Анонсы (платного продукта|воронки|бесплатника)')
RE_FIELD_LABEL = re.compile(r'^(Сайт:|Презы:|Что продаём,|Что продаем,|Спикер[ы]?:)')
RE_ALLCAPS     = re.compile(r'^[А-ЯЁA-Z\s\-:,!?\.«»\(\)\/\+\*✅🎯⚡]+$')


def classify(s: str) -> str:
    if not s:                          return 'empty'
    if s in MAIN_HEADERS:              return 'main_header'
    if RE_DEADLINE.match(s):           return 'deadline'
    if RE_DESIGN_RED.match(s):         return 'design_red'
    if RE_DRAFT_GREEN.match(s):        return 'draft_green'
    if RE_IMPORTANT.match(s):          return 'important'
    if RE_TZ_LETTER.match(s):          return 'tz_red'
    if RE_ADAPT.match(s):              return 'adapt_bold'
    if RE_ONECLICK.search(s):          return 'adapt_bold'
    if RE_SEGMENT.match(s):            return 'segment'
    if RE_LETTER_DESC.match(s):        return 'letter_desc'
    if RE_SUBSECTION.match(s):         return 'subsection'
    if RE_FIELD_LABEL.match(s):        return 'field_label'
    if RE_ALLCAPS.match(s) and any(c.isalpha() for c in s) and len(s) >= 2:
        return 'allcaps_bold'
    return 'normal'


def get_credentials():
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


def build_format_requests(doc: dict) -> list:
    requests = []
    body = doc.get('body', {}).get('content', [])
    if not body:
        return requests

    doc_end = body[-1]['endIndex']

    # Базовый стиль: Arial 11pt, выравнивание по левому краю
    requests.append({'updateTextStyle': {
        'range': {'startIndex': 1, 'endIndex': doc_end},
        'textStyle': {
            'weightedFontFamily': {'fontFamily': 'Arial', 'weight': 400},
            'fontSize': {'magnitude': 11, 'unit': 'PT'},
            'foregroundColor': {'color': {'rgbColor': BLACK_FG}},
            'bold': False, 'italic': False,
            'backgroundColor': {},
        },
        'fields': 'weightedFontFamily,fontSize,foregroundColor,bold,italic,backgroundColor'
    }})
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

    # Форматирование по абзацам
    for el in body:
        if 'paragraph' not in el:
            continue
        start    = el.get('startIndex', 0)
        end      = el.get('endIndex', 0)
        text     = ''.join(
            r['textRun']['content']
            for r in el['paragraph'].get('elements', [])
            if 'textRun' in r
        )
        s        = text.strip()
        text_end = end - 1
        if not s or text_end <= start:
            continue

        kind = classify(s)

        if kind == 'main_header':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': text_end},
                'textStyle': {'fontSize': {'magnitude': 14, 'unit': 'PT'}, 'bold': True},
                'fields': 'fontSize,bold'
            }})
            requests.append({'updateParagraphStyle': {
                'range': {'startIndex': start, 'endIndex': end},
                'paragraphStyle': {'alignment': 'CENTER'},
                'fields': 'alignment'
            }})

        elif kind == 'deadline':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': text_end},
                'textStyle': {
                    'bold': True,
                    'foregroundColor': {'color': {'rgbColor': RED_COLOR}},
                },
                'fields': 'bold,foregroundColor'
            }})

        elif kind == 'design_red':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': text_end},
                'textStyle': {'foregroundColor': {'color': {'rgbColor': RED_COLOR}}},
                'fields': 'foregroundColor'
            }})

        elif kind == 'draft_green':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': text_end},
                'textStyle': {
                    'foregroundColor': {'color': {'rgbColor': GREEN_COLOR}},
                    'backgroundColor': {'color': {'rgbColor': YELLOW_BG}},
                },
                'fields': 'foregroundColor,backgroundColor'
            }})

        elif kind == 'important':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': text_end},
                'textStyle': {'bold': True},
                'fields': 'bold'
            }})

        elif kind == 'tz_red':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': text_end},
                'textStyle': {
                    'bold': True,
                    'foregroundColor': {'color': {'rgbColor': RED_COLOR}},
                },
                'fields': 'bold,foregroundColor'
            }})

        elif kind == 'adapt_bold':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': text_end},
                'textStyle': {'bold': True},
                'fields': 'bold'
            }})

        elif kind in ('segment', 'letter_desc'):
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': text_end},
                'textStyle': {
                    'italic': True,
                    'backgroundColor': {'color': {'rgbColor': YELLOW_SOFT_BG}},
                },
                'fields': 'italic,backgroundColor'
            }})

        elif kind == 'subsection':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': text_end},
                'textStyle': {'fontSize': {'magnitude': 12, 'unit': 'PT'}, 'bold': True},
                'fields': 'fontSize,bold'
            }})

        elif kind in ('field_label', 'allcaps_bold'):
            requests.append({'updateTextStyle': {
                'range': {'startIndex': start, 'endIndex': text_end},
                'textStyle': {'bold': True},
                'fields': 'bold'
            }})

    return requests


def apply_formatting(docs, doc_id: str):
    doc = docs.documents().get(documentId=doc_id).execute()
    fmt = build_format_requests(doc)
    for i in range(0, len(fmt), 500):
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': fmt[i:i + 500]}
        ).execute()
    print(f"🎨 Форматирование: {len(fmt)} правил применено")


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
    docs  = build('docs', 'v1', credentials=creds)

    if doc_id and md_path:
        # Обновить существующий документ
        text = Path(md_path).read_text(encoding='utf-8')
        print(f"📄 Обновление документа: {doc_id}")

        existing = docs.documents().get(documentId=doc_id).execute()
        body     = existing.get('body', {}).get('content', [])
        doc_end  = body[-1]['endIndex']

        reqs = []
        if doc_end > 2:
            reqs.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': doc_end - 1}}})
        reqs.append({'insertText': {'location': {'index': 1}, 'text': text}})
        docs.documents().batchUpdate(documentId=doc_id, body={'requests': reqs}).execute()
        print("✏️  Текст обновлён")
        apply_formatting(docs, doc_id)

    elif doc_id:
        print(f"📄 Форматирование документа: {doc_id}")
        apply_formatting(docs, doc_id)

    else:
        src   = Path(md_path)
        text  = src.read_text(encoding='utf-8')
        title = title or src.stem.replace('_', ' ')

        doc    = docs.documents().create(body={'title': title}).execute()
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

        link_file = src.parent / 'google-doc-link.txt'
        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        link_file.write_text(f"ID: {doc_id}\nURL: {url}\n", encoding='utf-8')
        print(f"💾 Ссылка сохранена: {link_file}")

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    print(f"\n✅ Готово: {url}")
    return url


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ТЗ для копирайтера → Google Doc')
    parser.add_argument('--file',      default=None)
    parser.add_argument('--title',     default=None)
    parser.add_argument('--doc-id',    default=None)
    parser.add_argument('--folder-id', default=None,
                        help='ID Google Drive папки — документ будет перемещён туда после создания')
    args = parser.parse_args()
    if not args.file and not args.doc_id:
        parser.error("Нужно --file и/или --doc-id")
    create_doc(args.file, args.title, args.doc_id, args.folder_id)
