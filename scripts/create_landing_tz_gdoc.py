#!/usr/bin/env python3
"""
Создаёт отформатированный Google Doc с ТЗ на лендинг для дизайнера.

ИСПОЛЬЗОВАНИЕ:
    # Создать новый документ:
    python3 create_landing_tz_gdoc.py --file путь/к/файлу.md --title "Название"

    # Обновить существующий:
    python3 create_landing_tz_gdoc.py --file путь/к/файлу.md --doc-id [ID]

    # Переформатировать (только стили):
    python3 create_landing_tz_gdoc.py --doc-id [ID]
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
YELLOW_BG = {'red': 1.0, 'green': 1.0, 'blue': 0.0}
BLACK_FG  = {'red': 0.0, 'green': 0.0, 'blue': 0.0}

# Маркер таблицы тарифов
TARIFF_MARKER = '__TARIFF_TABLE__'

# Разделяем блок тарифов на две колонки.
# «БЕСПЛАТНЫЙ» матчим только как отдельную строку (^...$ с MULTILINE),
# чтобы не цеплять «БЕСПЛАТНЫЙ ПРАКТИКУМ» и т.п. на первом экране.
TARIFF_RE = re.compile(
    r'(^БЕСПЛАТНЫЙ$.*?\(ЗАРЕГИСТРИРОВАТЬСЯ БЕСПЛАТНО\))\s*\n+\s*(БИЗНЕС.*?\(ЗАРЕГИСТРИРОВАТЬСЯ ЗА 499.?\))',
    re.DOTALL | re.MULTILINE
)

# Заголовки разделов → 14pt жирный
SECTION_HEADERS = {
    'ПРОГРАММА:', 'ЧТО ТЕБЯ ЖДЕТ В ЭФИРЕ?', 'ЧТО БУДЕТ В ЭФИРЕ?',
    'СПИКЕР', 'СПИКЕРЫ', 'КОМУ ТОЧНО СТОИТ БЫТЬ?',
    'КТО МЫ?', 'ВАРИАНТЫ УЧАСТИЯ',
    'ГЛОССАРИЙ ТЕРМИНОВ', 'ГЛОССАРИЙ:',
}

# Строки → всегда жирный 11pt
BOLD_PHRASES = {
    'Всем, кто придет на эфир, расскажем, как получить:',
    'БЕСПЛАТНЫЙ', 'БИЗНЕС',
    'Все, что входит в тариф БЕСПЛАТНЫЙ',
    '+',
}

# Строка-коннектор перед списком программы (заканчивается на ':',
# не является заголовком раздела) → жирный 11pt.
# Лимит 120 — чтобы цеплять и длинные вводные фразы программы из концепта.
RE_CONNECTOR = re.compile(r'^[А-ЯЁа-яёA-Za-z][^.!?]{2,120}:$')

RE_CTA     = re.compile(r'^\([А-ЯЁA-Z0-9][А-ЯЁA-Z0-9\s₽]+\)$')
RE_DATE    = re.compile(r'^\d{1,2}\s+\w+\s+в\s+\d{1,2}[:.]\d{2}')
RE_SNOSKA  = re.compile(r'^\*')
RE_DIVIDER = re.compile(r'^_{5,}$')
RE_ALLCAPS = re.compile(r'^[А-ЯЁA-Z0-9\s\-:!?,\.\«\»\"\'\/\(\)]+$')


def utf16_len(text: str) -> int:
    return sum(2 if ord(c) > 0xFFFF else 1 for c in text)


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


def parse_text(text: str):
    """Заменяет блок тарифов маркером, возвращает (текст, левая_колонка, правая_колонка)."""
    m = TARIFF_RE.search(text)
    if not m:
        return text, None, None
    left  = m.group(1).strip()
    right = m.group(2).strip()
    cleaned = text[:m.start()] + TARIFF_MARKER + '\n' + text[m.end():]
    return cleaned, left, right


def collect_paragraphs(content, in_table=False):
    """Рекурсивно собирает все абзацы; in_table=True для ячеек таблиц."""
    result = []
    for el in content:
        if 'paragraph' in el:
            start = el.get('startIndex', 0)
            end   = el.get('endIndex', 0)
            text  = ''.join(
                r['textRun']['content']
                for r in el['paragraph'].get('elements', [])
                if 'textRun' in r
            )
            result.append((start, end, text, in_table))
        elif 'table' in el:
            for row in el['table'].get('tableRows', []):
                for cell in row.get('tableCells', []):
                    result.extend(collect_paragraphs(cell.get('content', []), in_table=True))
    return result


def classify(text: str, is_first: bool) -> str:
    s = text.strip()
    if not s:                              return 'empty'
    if is_first:                           return 'design_line'
    if RE_DIVIDER.match(s):               return 'divider'
    if RE_SNOSKA.match(s):                return 'snoska'
    if RE_DATE.match(s):                  return 'date'
    if s in SECTION_HEADERS:             return 'section_header'
    if s in BOLD_PHRASES:                return 'bold_phrase'
    if RE_CONNECTOR.match(s) and s not in SECTION_HEADERS: return 'bold_phrase'
    if RE_CTA.match(s):                   return 'cta'
    if ' — ' in s and not s.startswith('—') and len(s.split(' — ')[0].split()) <= 5:
        return 'glossary'
    if RE_ALLCAPS.match(s) and len(s) >= 4 and ' ' in s:
        return 'title'
    return 'normal'


def build_format_requests(doc: dict) -> list:
    requests = []
    body = doc.get('body', {}).get('content', [])
    if not body:
        return requests

    doc_end = body[-1]['endIndex']

    # 1. Базовый стиль
    requests.append({'updateTextStyle': {
        'range': {'startIndex': 1, 'endIndex': doc_end},
        'textStyle': {
            'weightedFontFamily': {'fontFamily': 'Arial', 'weight': 400},
            'fontSize': {'magnitude': 11, 'unit': 'PT'},
            'foregroundColor': {'color': {'rgbColor': BLACK_FG}},
            'bold': False, 'italic': False, 'backgroundColor': {},
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

    # 2. Форматирование абзацев
    paragraphs = collect_paragraphs(body)
    first_seen = False

    for para_start, para_end, para_text, para_in_table in paragraphs:
        s = para_text.strip()
        text_end = para_end - 1
        if text_end <= para_start or not s:
            continue

        is_first = not first_seen
        kind = classify(s, is_first)
        first_seen = True

        if kind == 'design_line':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {'backgroundColor': {'color': {'rgbColor': YELLOW_BG}}, 'bold': False},
                'fields': 'backgroundColor,bold'
            }})

        elif kind == 'title':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {'fontSize': {'magnitude': 18, 'unit': 'PT'}, 'bold': True},
                'fields': 'fontSize,bold'
            }})

        elif kind == 'section_header':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {'fontSize': {'magnitude': 14, 'unit': 'PT'}, 'bold': True},
                'fields': 'fontSize,bold'
            }})

        elif kind == 'cta':
            # CTAs внутри таблицы тарифов — 12pt; страничные CTAs — 16pt
            cta_size = 12 if para_in_table else 16
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {'fontSize': {'magnitude': cta_size, 'unit': 'PT'}, 'bold': True},
                'fields': 'fontSize,bold'
            }})

        elif kind in ('date', 'bold_phrase'):
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {'bold': True},
                'fields': 'bold'
            }})

        elif kind == 'snoska':
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': text_end},
                'textStyle': {'fontSize': {'magnitude': 9, 'unit': 'PT'}, 'italic': True, 'bold': False},
                'fields': 'fontSize,italic,bold'
            }})

        elif kind == 'glossary':
            term = s.split(' — ', 1)[0]
            t_len = utf16_len(term)
            d_len = utf16_len(' — ')
            requests.append({'updateTextStyle': {
                'range': {'startIndex': para_start, 'endIndex': para_start + t_len},
                'textStyle': {'bold': True},
                'fields': 'bold'
            }})
            rest = para_start + t_len + d_len
            if rest < text_end:
                requests.append({'updateTextStyle': {
                    'range': {'startIndex': rest, 'endIndex': text_end},
                    'textStyle': {'bold': False},
                    'fields': 'bold'
                }})

    return requests


def find_marker(doc: dict):
    """Находит позицию маркера таблицы тарифов."""
    for el in doc.get('body', {}).get('content', []):
        if 'paragraph' in el:
            txt = ''.join(
                r['textRun']['content']
                for r in el['paragraph'].get('elements', [])
                if 'textRun' in r
            )
            if TARIFF_MARKER in txt:
                return el.get('startIndex', 0), el.get('endIndex', 0)
    return None, None


def get_cell_starts(doc: dict, after_idx: int):
    """Находит startIndex первых абзацев в двух ячейках таблицы."""
    for el in doc.get('body', {}).get('content', []):
        if 'table' in el and el.get('startIndex', 0) >= after_idx - 3:
            rows = el['table'].get('tableRows', [])
            if not rows:
                continue
            cells = rows[0].get('tableCells', [])
            if len(cells) < 2:
                continue
            def first_para(cell):
                for c in cell.get('content', []):
                    if 'paragraph' in c:
                        return c.get('startIndex', 0)
                return None
            l = first_para(cells[0])
            r = first_para(cells[1])
            if l is not None and r is not None:
                return l, r
    return None, None


def insert_tariff_table(docs, doc_id: str, left: str, right: str):
    """Заменяет маркер реальной двухколоночной таблицей."""
    doc = docs.documents().get(documentId=doc_id).execute()
    ms, me = find_marker(doc)
    if ms is None:
        print("⚠️  Маркер таблицы тарифов не найден")
        return

    # Удаляем маркер
    docs.documents().batchUpdate(documentId=doc_id, body={'requests': [
        {'deleteContentRange': {'range': {'startIndex': ms, 'endIndex': me}}}
    ]}).execute()

    # Вставляем таблицу 1×2 на место маркера
    docs.documents().batchUpdate(documentId=doc_id, body={'requests': [
        {'insertTable': {'rows': 1, 'columns': 2, 'location': {'index': ms}}}
    ]}).execute()

    # Получаем позиции ячеек
    doc = docs.documents().get(documentId=doc_id).execute()
    left_idx, right_idx = get_cell_starts(doc, ms)
    if left_idx is None:
        print("⚠️  Ячейки таблицы не найдены")
        return

    # Вставляем правую колонку первой (она стоит позже по индексу)
    docs.documents().batchUpdate(documentId=doc_id, body={'requests': [
        {'insertText': {'location': {'index': right_idx}, 'text': right}}
    ]}).execute()

    # Левая колонка — индекс не сдвинулся (она раньше правой)
    docs.documents().batchUpdate(documentId=doc_id, body={'requests': [
        {'insertText': {'location': {'index': left_idx}, 'text': left}}
    ]}).execute()

    print("✅ Таблица тарифов создана")


def apply_formatting(docs, doc_id: str):
    doc = docs.documents().get(documentId=doc_id).execute()
    fmt = build_format_requests(doc)
    for i in range(0, len(fmt), 500):
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': fmt[i:i+500]}
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
    docs = build('docs', 'v1', credentials=creds)

    if doc_id and md_path:
        # Обновить существующий документ
        src = Path(md_path)
        text = src.read_text(encoding='utf-8')
        print(f"📄 Обновление документа: {doc_id}")

        existing = docs.documents().get(documentId=doc_id).execute()
        body = existing.get('body', {}).get('content', [])
        doc_end = body[-1]['endIndex']

        reqs = []
        if doc_end > 2:
            reqs.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': doc_end - 1}}})
        reqs.append({'insertText': {'location': {'index': 1}, 'text': text}})
        docs.documents().batchUpdate(documentId=doc_id, body={'requests': reqs}).execute()
        print("✏️  Текст обновлён")

        cleaned, left, right = parse_text(text)
        if left:
            # Нужно переписать текст с маркером
            existing2 = docs.documents().get(documentId=doc_id).execute()
            body2 = existing2.get('body', {}).get('content', [])
            doc_end2 = body2[-1]['endIndex']
            reqs2 = []
            if doc_end2 > 2:
                reqs2.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': doc_end2 - 1}}})
            reqs2.append({'insertText': {'location': {'index': 1}, 'text': cleaned}})
            docs.documents().batchUpdate(documentId=doc_id, body={'requests': reqs2}).execute()
            insert_tariff_table(docs, doc_id, left, right)

        apply_formatting(docs, doc_id)

    elif doc_id:
        print(f"📄 Форматирование документа: {doc_id}")
        apply_formatting(docs, doc_id)

    else:
        src = Path(md_path)
        raw_text = src.read_text(encoding='utf-8')
        title = title or src.stem.replace('_', ' ')

        cleaned, left, right = parse_text(raw_text)

        doc = docs.documents().create(body={'title': title}).execute()
        doc_id = doc['documentId']
        print(f"📄 Документ создан: {doc_id}")

        docs.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': [{'insertText': {'location': {'index': 1}, 'text': cleaned}}]}
        ).execute()
        print("✏️  Текст вставлен")

        if left:
            insert_tariff_table(docs, doc_id, left, right)

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
    parser = argparse.ArgumentParser(description='ТЗ на лендинг → Google Doc')
    parser.add_argument('--file', default=None)
    parser.add_argument('--title', default=None)
    parser.add_argument('--doc-id', default=None)
    parser.add_argument('--folder-id', default=None,
                        help='ID Google Drive папки — документ будет перемещён туда после создания')
    args = parser.parse_args()
    if not args.file and not args.doc_id:
        parser.error("Нужно --file и/или --doc-id")
    create_doc(args.file, args.title, args.doc_id, args.folder_id)
