import os
import re
import json
import base64
from typing import List, Dict, Optional

import fitz  # PyMuPDF

try:
    from docling.document_converter import DocumentConverter
except Exception:  # pragma: no cover - library optional at runtime
    DocumentConverter = None

# mapping for private-use option symbols
OPT_MAP = {
    "\ue18c": "A",
    "\ue18d": "B",
    "\ue18e": "C",
    "\ue18f": "D",
    "Ａ": "A",
    "Ｂ": "B",
    "Ｃ": "C",
    "Ｄ": "D",
}

# patterns to locate questions / options in text lines
QUESTION_START = re.compile(r"^(\d{1,3})[\.．]\s*(.*)")
OPTION_PATTERN = re.compile(r"^[A-D][\.|\s]")


def recognize_files(folder: str) -> Dict[str, Dict[str, Optional[str]]]:
    """Recognize question, answer and modification PDF files grouped by prefix."""
    files = [f for f in os.listdir(folder) if f.lower().endswith('.pdf')]
    grouped: Dict[str, Dict[str, Optional[str]]] = {}
    for f in files:
        key = f.split('_')[0]
        fname = f.lower()
        full_path = os.path.join(folder, f)
        slot = grouped.setdefault(key, {"question": None, "answer": None, "modification": None})
        if 'ans' in fname:
            slot['answer'] = full_path
        elif 'mod' in fname:
            slot['modification'] = full_path
        else:
            slot['question'] = full_path
    return grouped


def _extract_images(page: fitz.Page, q_ranges: List[tuple]) -> List[List[str]]:
    """Return images (base64) grouped per question using vertical ranges."""
    images = [[] for _ in q_ranges]
    for img in page.get_images(full=True):
        xref = img[0]
        rects = page.get_image_rects(xref)
        if not rects:
            continue
        rect = rects[0]
        pix = fitz.Pixmap(page.parent, xref)
        b64 = base64.b64encode(pix.tobytes("png")).decode('ascii')
        y_center = (rect.y0 + rect.y1) / 2
        for idx, (y0, y1) in enumerate(q_ranges):
            if y0 <= y_center <= y1:
                images[idx].append(b64)
                break
    return images


def parse_questions(pdf_path: str) -> List[Dict]:
    """Parse question PDF into structured list with images."""
    doc = fitz.open(pdf_path)
    questions: List[Dict] = []
    expected = 1
    for page in doc:
        data = page.get_text("dict")
        lines = []
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                text = ''.join(span["text"] for span in line.get("spans", []))
                x0, y0, *_ = line["bbox"]
                lines.append((x0, y0, text))
        lines.sort(key=lambda l: (l[1], l[0]))
        current = None
        q_ranges: List[tuple] = []
        for x0, y0, text in lines:
            stripped = text.strip()
            if stripped.isdigit():
                qid = int(stripped)
                if qid == expected:
                    if current:
                        current['range'][1] = y0
                        questions.append(current['data'])
                        q_ranges.append(tuple(current['range']))
                    current = {
                        'data': {'id': qid, 'question': '', 'options': {}, 'images': []},
                        'range': [y0, page.rect.y1],
                    }
                    expected += 1
                elif current:
                    # treat as normal text
                    if current['data']['question']:
                        current['data']['question'] += '\n' + stripped
                    else:
                        current['data']['question'] = stripped
            else:
                m = QUESTION_START.match(stripped)
                if m and int(m.group(1)) == expected:
                    if current:
                        current['range'][1] = y0
                        questions.append(current['data'])
                        q_ranges.append(tuple(current['range']))
                    current = {
                        'data': {'id': expected, 'question': m.group(2).strip(), 'options': {}, 'images': []},
                        'range': [y0, page.rect.y1],
                    }
                    expected += 1
                elif current:
                    if stripped and stripped[0] in OPT_MAP:
                        opt_key = OPT_MAP[stripped[0]]
                        current['data']['options'][opt_key] = stripped[1:].strip()
                    elif OPTION_PATTERN.match(stripped):
                        opt_key = stripped[0]
                        current['data']['options'][opt_key] = stripped[2:].strip()
                    else:
                        if current['data']['question']:
                            current['data']['question'] += '\n' + stripped
                        else:
                            current['data']['question'] = stripped
        if current:
            questions.append(current['data'])
            q_ranges.append(tuple(current['range']))
        img_groups = _extract_images(page, q_ranges)
        for q, imgs in zip(questions[-len(img_groups):], img_groups):
            q['images'].extend(imgs)
    return questions


def parse_pdf_with_docling(pdf_path: str) -> Dict:
    """Use docling DocumentConverter to convert PDF to JSON with fallback."""
    if DocumentConverter is None:
        doc = fitz.open(pdf_path)
        text = "\n".join(page.get_text() for page in doc)
        return {"text": text}
    try:
        conv = DocumentConverter()
        res = conv.convert(pdf_path)
        return res.document.model_dump()
    except Exception:
        doc = fitz.open(pdf_path)
        text = "\n".join(page.get_text() for page in doc)
        return {"text": text}


def _gather_text(obj) -> str:
    if isinstance(obj, dict):
        return '\n'.join(_gather_text(v) for v in obj.values())
    if isinstance(obj, list):
        return '\n'.join(_gather_text(i) for i in obj)
    if isinstance(obj, str):
        return obj
    return ''


def combine(questions: List[Dict], ans_json: Dict, mod_json: Dict) -> List[Dict]:
    """Combine questions with answers and modifications."""
    ans_text = _gather_text(ans_json)
    mod_text = _gather_text(mod_json)
    ans_map: Dict[str, str] = {}
    for line in ans_text.splitlines():
        m = re.match(r"^(\d+)\s*[\.、:：-]?\s*([A-DＡＢＣＤ\ue18c-\ue18f])", line.strip())
        if m:
            key = m.group(2)
            ans_map[m.group(1)] = OPT_MAP.get(key, key)
    if not ans_map:
        letters = re.findall(r"[A-DＡＢＣＤ\ue18c-\ue18f]", ans_text)
        for idx, ch in enumerate(letters, 1):
            ans_map[str(idx)] = OPT_MAP.get(ch, ch)
    mod_map: Dict[str, str] = {}
    for line in mod_text.splitlines():
        m = re.match(r"^(\d+)\s*[#＃]\s*(.+)$", line.strip())
        if m:
            mod_map[m.group(1)] = m.group(2).strip()
    for q in questions:
        qid = str(q['id'])
        q['answer'] = ans_map.get(qid, '')
        if qid in mod_map:
            q['modification'] = mod_map[qid]
    return questions


def demo(folder: str) -> None:
    sets = recognize_files(folder)
    print('Recognized:', sets)
    for key, files in sets.items():
        print(f'Processing set {key}')
        if files.get('question'):
            qs = parse_questions(files['question'])
            print(f'Parsed {len(qs)} questions')
        else:
            print('Question file missing')
            qs = []
        try:
            ans_json = parse_pdf_with_docling(files.get('answer')) if files.get('answer') else {}
            mod_json = parse_pdf_with_docling(files.get('modification')) if files.get('modification') else {}
            combined = combine(qs, ans_json, mod_json)
            print('Combined sample:', json.dumps(combined[:1], ensure_ascii=False, indent=2))
        except Exception as e:
            print('Docling processing failed:', e)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='PDF question tool')
    parser.add_argument('--demo', help='run demo on folder')
    args = parser.parse_args()
    if args.demo:
        demo(args.demo)
