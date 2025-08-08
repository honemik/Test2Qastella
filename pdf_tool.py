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

# default output folder for debug artifacts
OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT_DIR, exist_ok=True)

# patterns to locate questions / options in text lines
QUESTION_START = re.compile(r"^(\d{1,3})[\.．]\s*(.*)")
OPTION_PATTERN = re.compile(r"^[A-D][\.|\s]")


def recognize_files(folder: str) -> Dict[str, Dict[str, Optional[str]]]:
    """Recognize question, answer and modification PDF files grouped by set.

    Each set is keyed by the exam prefix and subject code (e.g. 104030_0104)
    so that different subjects within the same year are separated correctly.
    """
    files = [f for f in os.listdir(folder) if f.lower().endswith('.pdf')]
    grouped: Dict[str, Dict[str, Optional[str]]] = {}
    for f in files:
        parts = f.split('_')
        prefix = parts[0]
        code_part = parts[1] if len(parts) > 1 else ''
        m_code = re.search(r"(?:ANS|MOD)?(\d+)", code_part, re.IGNORECASE)
        subj_code = m_code.group(1) if m_code else code_part
        key = f"{prefix}_{subj_code}" if subj_code else prefix

        fname = f.lower()
        full_path = os.path.join(folder, f)
        m = re.search(r"醫學[\(（]([一二三四五六])", f)
        subject = f"醫學({m.group(1)})" if m else "Unknown"

        slot = grouped.setdefault(key, {
            "question": None,
            "answer": None,
            "modification": None,
            "subject": subject,
        })
        if slot.get("subject") == "Unknown" and subject != "Unknown":
            slot["subject"] = subject
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
        # prefix the base64 string with a data URI so JSON consumers know the
        # encoding and image type
        b64 = "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode('ascii')
        y_center = (rect.y0 + rect.y1) / 2
        for idx, (y0, y1) in enumerate(q_ranges):
            if y0 <= y_center <= y1:
                images[idx].append(b64)
                break
    return images


def parse_questions(pdf_path: str) -> List[Dict]:
    """Parse question PDF into structured list with images and save debug JSON."""
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

        # attach page-start lines to previous question if needed
        idx = 0
        if questions:
            prev = questions[-1]
            while idx < len(lines):
                stripped = lines[idx][2].strip()
                if stripped.isdigit() and int(stripped) == expected:
                    break
                m = QUESTION_START.match(stripped)
                if m and int(m.group(1)) == expected:
                    break
                if stripped and stripped[0] in OPT_MAP:
                    opt_key = OPT_MAP[stripped[0]]
                    prev['options'][opt_key] = stripped[1:].strip()
                elif OPTION_PATTERN.match(stripped):
                    opt_key = stripped[0]
                    prev['options'][opt_key] = stripped[2:].strip()
                else:
                    if prev['question']:
                        prev['question'] += '\n' + stripped
                    else:
                        prev['question'] = stripped
                idx += 1
        lines = lines[idx:]

        current = None
        q_ranges: List[tuple] = []
        last_opt: Optional[str] = None
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
                    last_opt = None
                elif current:
                    if last_opt and stripped:
                        opt_text = current['data']['options'][last_opt]
                        current['data']['options'][last_opt] = opt_text + '\n' + stripped
                    else:
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
                    last_opt = None
                elif current:
                    if stripped and stripped[0] in OPT_MAP:
                        opt_key = OPT_MAP[stripped[0]]
                        current['data']['options'][opt_key] = stripped[1:].strip()
                        last_opt = opt_key
                    elif OPTION_PATTERN.match(stripped):
                        opt_key = stripped[0]
                        current['data']['options'][opt_key] = stripped[2:].strip()
                        last_opt = opt_key
                    else:
                        if last_opt and stripped:
                            opt_text = current['data']['options'][last_opt]
                            current['data']['options'][last_opt] = opt_text + '\n' + stripped
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
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    out_path = os.path.join(OUT_DIR, f"questions_{base}.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    return questions


def parse_pdf_with_docling(pdf_path: str) -> str:
    """Convert PDF to Markdown using docling when possible and save for debugging."""
    if DocumentConverter is None:
        doc = fitz.open(pdf_path)
        md = "\n".join(page.get_text() for page in doc)
    else:
        try:
            conv = DocumentConverter()
            res = conv.convert(pdf_path)
            if hasattr(res.document, "export_to_markdown"):
                md = res.document.export_to_markdown()
            else:
                md = res.document.model_dump_json()
        except Exception:
            doc = fitz.open(pdf_path)
            md = "\n".join(page.get_text() for page in doc)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    out_path = os.path.join(OUT_DIR, f"{base}.md")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(md)
    return md


def _extract_md_tables(md: str) -> List[List[List[str]]]:
    tables: List[List[List[str]]] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i])
                i += 1
            rows = []
            for line in table_lines:
                cells = [c.strip() for c in line.strip().strip('|').split('|')]
                rows.append(cells)
            tables.append(rows)
        else:
            i += 1
    return tables


def _parse_answer_map(md: str) -> Dict[str, str]:
    best: Dict[str, str] = {}
    tables = _extract_md_tables(md)
    for rows in tables:
        mapping: Dict[str, str] = {}
        for cells in rows[1:]:  # skip header if any
            if len(cells) < 2:
                continue
            num, val = cells[0].strip(), cells[1].strip()
            if num.isdigit() and val:
                mapping[num] = OPT_MAP.get(val, val)
        if len(mapping) > len(best):
            best = mapping
    if best:
        return best
    letters = [OPT_MAP.get(ch, ch) for ch in re.findall(r'[A-DＡ-Ｄ]', md)]
    return {str(i + 1): letters[i] for i in range(len(letters))}


def _parse_mod_map(md: str) -> Dict[str, str]:
    """Parse modification markdown into a mapping of question id -> corrected answer.

    The modification files are expected to contain answers as letters as well. We
    therefore reuse the same logic as parsing the answer tables but take the
    last non-empty cell as the corrected letter.
    """
    best: Dict[str, str] = {}
    tables = _extract_md_tables(md)
    for rows in tables:
        mapping: Dict[str, str] = {}
        for cells in rows[1:]:
            if len(cells) < 2:
                continue
            num = cells[0].strip()
            if not num.isdigit():
                continue
            # take last non-empty cell as the corrected answer
            vals = [c.strip() for c in cells[1:] if c.strip()]
            if vals:
                letter = OPT_MAP.get(vals[-1], vals[-1])
                mapping[num] = letter
        if len(mapping) > len(best):
            best = mapping
    if best:
        return best
    mapping: Dict[str, str] = {}
    for m in re.finditer(r"(\d+)\s*[\.．]\s*([A-DＡ-Ｄ])", md):
        mapping[m.group(1)] = OPT_MAP.get(m.group(2), m.group(2))
    return mapping


def _is_valid_map(mapping: Dict[str, str], count: int) -> bool:
    """Return True if mapping has answers for all questions and only A-D."""
    if len(mapping) != count:
        return False
    return all(v in {'A', 'B', 'C', 'D'} for v in mapping.values())


def validate_output_structure(data: Dict) -> bool:
    """Validate combined output structure against README schema."""
    if not isinstance(data, dict):
        return False
    subjects = data.get('subjects')
    if not isinstance(subjects, dict) or not subjects:
        return False
    for subj, sources in subjects.items():
        if not isinstance(sources, dict) or not sources:
            return False
        for src, questions in sources.items():
            if not isinstance(questions, list) or not questions:
                return False
            for q in questions:
                if not isinstance(q, dict):
                    return False
                if 'id' not in q or 'answer' not in q or 'question' not in q:
                    return False
                if not isinstance(q['id'], int):
                    return False
                if q['answer'] not in {'A', 'B', 'C', 'D'}:
                    return False
                if 'options' in q and not isinstance(q['options'], dict):
                    return False
                if 'images' in q and not isinstance(q['images'], list):
                    return False
    return True


def combine(questions: List[Dict], ans_md: str, mod_md: str, *, subject: str, source: str, logger=None) -> Dict:
    """Combine questions with answers (and optional corrections).

    The answer and modification markdown are first parsed into mappings. Each
    mapping is validated to ensure it covers all questions and that every value
    is a letter A-D. If the answer mapping passes validation it is used alone.
    Otherwise the modification mapping is applied. A merge of both is attempted
    if needed. The final questions contain only the resolved `answer` field.
    """
    ans_map = _parse_answer_map(ans_md) if ans_md else {}
    mod_map = _parse_mod_map(mod_md) if mod_md else {}
    q_count = len(questions)

    ans_ok = _is_valid_map(ans_map, q_count)
    if logger:
        logger(f"Answer mapping {'valid' if ans_ok else 'invalid'} ({len(ans_map)}/{q_count})")
    mod_ok = _is_valid_map(mod_map, q_count)
    if logger:
        logger(f"Modification mapping {'valid' if mod_ok else 'invalid'} ({len(mod_map)}/{q_count})")

    if ans_ok:
        mapping = ans_map
        if logger:
            logger('Using answer mapping')
    elif mod_ok:
        mapping = mod_map
        if logger:
            logger('Using modification mapping')
    elif ans_map or mod_map:
        mapping = ans_map.copy()
        mapping.update(mod_map)
        if not _is_valid_map(mapping, q_count):
            raise ValueError('Answer and modification mapping incomplete or invalid')
        if logger:
            logger('Merged answer and modification mapping')
    else:
        raise ValueError('No analyzable tables in answer or modification PDFs')

    for q in questions:
        qid = str(q['id'])
        if qid not in mapping:
            raise ValueError(f'Missing answer for question {qid}')
        q['answer'] = mapping[qid]
        # ensure images are stored with data URI prefixes for downstream use
        if 'images' in q and q['images']:
            q['images'] = [img if img.startswith('data:image') else 'data:image/png;base64,' + img for img in q['images']]

    out = {"subjects": {subject: {source: questions}}}
    if not validate_output_structure(out):
        raise ValueError('Combined output failed validation')
    out_path = os.path.join(OUT_DIR, f"combined_{source}.json")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(out_path, 'r', encoding='utf-8') as f:
        loaded = json.load(f)
    if not validate_output_structure(loaded):
        raise ValueError('Written output failed validation')
    if logger:
        logger('Output structure validation succeeded')
    return out, out_path


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
            ans_md = parse_pdf_with_docling(files.get('answer')) if files.get('answer') else ''
            mod_md = parse_pdf_with_docling(files.get('modification')) if files.get('modification') else ''
            combined, _ = combine(qs, ans_md, mod_md, subject=files.get('subject', 'Unknown'), source=key)
            sample = combined['subjects'][files.get('subject', 'Unknown')][key][:1]
            print('Combined sample:', json.dumps(sample, ensure_ascii=False, indent=2))
        except Exception as e:
            print('Docling processing failed:', e)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='PDF question tool')
    parser.add_argument('--demo', help='run demo on folder')
    args = parser.parse_args()
    if args.demo:
        demo(args.demo)
