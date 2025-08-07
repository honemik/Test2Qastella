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

QUESTION_PATTERN = re.compile(r"^(\d+)[\.\s]")
OPTION_PATTERN = re.compile(r"^[A-D][\.|\s]")


def recognize_files(folder: str) -> Dict[str, Optional[str]]:
    """Recognize question, answer and modification PDF files by name."""
    files = [f for f in os.listdir(folder) if f.lower().endswith('.pdf')]
    res = {"question": None, "answer": None, "modification": None}
    for f in files:
        fname = f.lower()
        full_path = os.path.join(folder, f)
        if 'ans' in fname:
            res['answer'] = full_path
        elif 'mod' in fname:
            res['modification'] = full_path
        else:
            res['question'] = full_path
    return res


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
        b64 = base64.b64encode(pix.tobytes()).decode('ascii')
        y_center = (rect.y0 + rect.y1) / 2
        for idx, (y0, y1) in enumerate(q_ranges):
            if y0 <= y_center <= y1:
                images[idx].append(b64)
                break
    return images


def parse_questions(pdf_path: str) -> List[Dict]:
    """Parse question PDF into structured list with images."""
    doc = fitz.open(pdf_path)
    questions = []
    for page in doc:
        blocks = page.get_text("blocks")
        blocks = sorted(blocks, key=lambda b: (b[1], b[0]))
        current = None
        q_ranges = []
        for b in blocks:
            x0, y0, x1, y1, text, *_ = b
            if QUESTION_PATTERN.match(text.strip()):
                if current:
                    current['range'][1] = y0
                    questions.append(current['data'])
                    q_ranges.append(tuple(current['range']))
                qid = int(QUESTION_PATTERN.match(text.strip()).group(1))
                current = {
                    'data': {
                        'id': qid,
                        'question': text.strip(),
                        'options': {},
                        'images': []
                    },
                    'range': [y0, page.rect.y1]
                }
            elif current:
                stripped = text.strip()
                if OPTION_PATTERN.match(stripped):
                    opt_key = stripped[0]
                    current['data']['options'][opt_key] = stripped[2:].strip()
                else:
                    current['data']['question'] += '\n' + stripped
        if current:
            questions.append(current['data'])
            q_ranges.append(tuple(current['range']))
        img_groups = _extract_images(page, q_ranges)
        for q, imgs in zip(questions[-len(img_groups):], img_groups):
            q['images'].extend(imgs)
    return questions


def parse_pdf_with_docling(pdf_path: str) -> Dict:
    """Use docling DocumentConverter to convert PDF to JSON."""
    if DocumentConverter is None:
        raise RuntimeError("docling library not available")
    conv = DocumentConverter()
    res = conv.convert(pdf_path)
    return res.document.model_dump()


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
    ans_map = {m.group(1): m.group(2) for m in re.finditer(r"(\d+)\s*[:\.\-]?\s*([A-D])", ans_text)}
    mod_map = {m.group(1): m.group(2) for m in re.finditer(r"(\d+)\s*[:\.\-]?\s*(.+)", mod_text)}
    for q in questions:
        qid = str(q['id'])
        q['answer'] = ans_map.get(qid, '')
        if qid in mod_map:
            q['modification'] = mod_map[qid]
    return questions


def demo(folder: str) -> None:
    files = recognize_files(folder)
    print('Recognized:', files)
    if files['question']:
        qs = parse_questions(files['question'])
        print(f'Parsed {len(qs)} questions')
    else:
        print('Question file missing')
        qs = []
    try:
        ans_json = parse_pdf_with_docling(files['answer']) if files['answer'] else {}
        mod_json = parse_pdf_with_docling(files['modification']) if files['modification'] else {}
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
