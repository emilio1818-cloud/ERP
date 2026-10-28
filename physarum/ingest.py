"""Digestion: turn any file into tables (grids with a header) and documents (prose).

Handles the usual mess: title rows above the header, blank rows, section rows
("ESPRESSO" between articles), sum rows at the bottom, repeated headers, cp1252 CSVs
with semicolons, key/value text blocks, e-mails with attachments, PDFs, Word files,
JSON with nested arrays and ZIP archives.
"""
from __future__ import annotations

import csv
import io
import itertools
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import PurePath

from . import lexicon
from .values import is_empty, parse_date, parse_number

MAX_ZIP_TOTAL = 300 * 1024 * 1024
MAX_ZIP_MEMBERS = 3000


@dataclass
class RawTable:
    name: str
    columns: list[str]
    rows: list[list]
    lines: list[int]
    sheet: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class RawDoc:
    kind: str
    title: str
    text: str
    sender: str | None = None
    recipients: str | None = None
    date: datetime | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class Digest:
    tables: list[RawTable] = field(default_factory=list)
    docs: list[RawDoc] = field(default_factory=list)
    attachments: list[tuple[str, bytes]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


TEXT_EXT = {".csv", ".tsv", ".txt", ".dat", ".tab", ".prn", ".md", ".log", ".text"}
SHEET_EXT = {".xlsx", ".xlsm", ".xltx", ".xltm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".heic", ".webp"}


def decode_text(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8"


def read_file(name: str, data: bytes) -> Digest:
    ext = PurePath(name).suffix.lower()
    stem = PurePath(name).stem
    d = Digest()
    try:
        if ext in SHEET_EXT:
            _read_xlsx(stem, data, d)
        elif ext == ".xls":
            d.notes.append("Altes Excel-Format (.xls): bitte als .xlsx speichern – Datei wurde aufbewahrt.")
        elif ext == ".ods":
            d.notes.append("OpenDocument-Tabellen (.ods) werden noch nicht gelesen – bitte als .xlsx speichern.")
        elif ext == ".json":
            _read_json(stem, data, d)
        elif ext == ".xml":
            _read_xml(stem, data, d)
        elif ext == ".eml":
            _read_eml(stem, data, d)
        elif ext == ".pdf":
            _read_pdf(stem, data, d)
        elif ext == ".docx":
            _read_docx(stem, data, d)
        elif ext == ".zip":
            _read_zip(data, d)
        elif ext in (".html", ".htm"):
            text, _ = decode_text(data)
            _read_html(stem, text, d)
        elif ext in IMAGE_EXT:
            d.docs.append(RawDoc("bild", stem, "", meta={"note": "Bild ohne Texterkennung"}))
        else:
            text, enc = decode_text(data)
            if "\x00" in text[:2000]:
                d.notes.append(f"Unbekanntes Binärformat ({ext or 'ohne Endung'}) – Datei wurde aufbewahrt.")
            else:
                _read_text(stem, text, enc, ext, d)
    except Exception as e:  # a broken file must never break the whole dump
        d.notes.append(f"Konnte {name} nicht lesen: {type(e).__name__}: {e}")
    return d


# --- text / csv ---------------------------------------------------------------------------------

def _sniff_delimiter(text: str) -> str | None:
    """The delimiter that gives the longest run of equally wide records. Records, not lines:
    bank exports put line breaks inside quoted purposes, and many files start with a preamble
    (bank name, account, period) that has fewer fields than the table below it."""
    best, best_score = None, 0.0
    head = text[:300000]
    for delim in (";", "\t", ",", "|"):
        try:
            recs = [r for r in itertools.islice(csv.reader(io.StringIO(head), delimiter=delim), 600)
                    if any(c.strip() for c in r)]
        except csv.Error:
            continue
        if len(recs) < 2:
            continue
        counts = Counter(len(r) for r in recs)
        cands = [(w, f) for w, f in counts.items() if w >= 2]
        if not cands:
            continue
        width, freq = max(cands, key=lambda x: (x[1] * min(x[0], 12), x[0]))
        run = longest = 0
        for r in recs:
            run = run + 1 if width - 1 <= len(r) <= width + 1 else 0
            longest = max(longest, run)
        if longest < 2 or (longest < 5 and freq / len(recs) < 0.6):
            continue
        score = longest * min(width, 12)
        if score > best_score:
            best, best_score = delim, score
    return best


_DEBIT_CREDIT = {"s": -1, "soll": -1, "h": 1, "haben": 1}


def _apply_debit_credit(t: "RawTable"):
    """Bank exports with positive amounts and a separate S/H column: Soll is money going out."""
    if not t.rows:
        return
    width = len(t.columns)
    for j in range(width):
        vals = [str(r[j]).strip().casefold() for r in t.rows if j < len(r) and r[j] not in (None, "")]
        if len(vals) < max(3, 0.9 * len(t.rows)) or not all(v in _DEBIT_CREDIT for v in vals):
            continue
        amount = None
        for k in list(range(j - 1, -1, -1)) + list(range(j + 1, width)):
            nums = [r[k] for r in t.rows if k < len(r) and r[k] not in (None, "")]
            ok = sum(1 for v in nums if (isinstance(v, (int, float)) and not isinstance(v, bool))
                     or parse_number(str(v)) is not None)
            if nums and ok >= 0.9 * len(nums):
                amount = k
                break
        if amount is None:
            return
        for r in t.rows:
            if j < len(r) and amount < len(r) and _DEBIT_CREDIT.get(str(r[j]).strip().casefold()) == -1:
                v = r[amount]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    r[amount] = -abs(v)
                elif isinstance(v, str) and v.strip() and not v.strip().startswith("-"):
                    r[amount] = "-" + v.strip()
        if not str(t.columns[j]).strip():
            t.columns[j] = "Soll/Haben"
        return


_KV = re.compile(r"^\s*([A-Za-zÄÖÜäöüß][\wÄÖÜäöüß .\-/()&]{0,40}?)\s*:\s+(.*\S)?\s*$")


def _kv_blocks(text: str) -> RawTable | None:
    blocks, cur, line_no, starts = [], [], 0, []
    for i, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            if cur:
                blocks.append(cur)
                starts.append(line_no)
                cur = []
            continue
        if not cur:
            line_no = i
        cur.append(raw)
    if cur:
        blocks.append(cur)
        starts.append(line_no)
    recs, rec_lines, titles = [], [], []
    for b, start in zip(blocks, starts):
        kv = []
        for l in b:
            m = _KV.match(l)
            if m and not re.match(r"^\s*(https?|www)", l):
                kv.append([m.group(1).strip(), (m.group(2) or "").strip()])
            elif kv:
                kv[-1][1] = (kv[-1][1] + " " + l.strip()).strip()
        if len(kv) >= 2:
            recs.append(kv)
            rec_lines.append(start)
        else:
            titles.append(" ".join(x.strip() for x in b))
    if len(recs) < 2:
        return None
    key_freq = Counter(k for r in recs for k, _ in {(k, 0) for k, _ in r})
    recurring = [k for k, c in key_freq.items() if c >= 2]
    if len(recurring) < 2:
        return None
    columns = []
    for r in recs:
        for k, _ in r:
            if k not in columns:
                columns.append(k)
    rows = []
    for r in recs:
        d = {}
        for k, v in r:
            d[k] = v if k not in d else d[k] + "; " + v
        rows.append([d.get(c) for c in columns])
    return RawTable(name="", columns=columns, rows=rows, lines=rec_lines,
                    meta={"format": "Schlüssel: Wert", "title": " · ".join(titles)[:300], "locale": "de"})


def _read_text(stem: str, text: str, enc: str, ext: str, d: Digest):
    delim = _sniff_delimiter(text) if ext != ".md" else None
    if delim:
        grid = list(csv.reader(io.StringIO(text), delimiter=delim))
        locale = "de" if delim == ";" else None
        tabs = detect_tables(grid, stem, {"delimiter": delim, "encoding": enc, "locale": locale})
        if tabs:
            d.tables.extend(tabs)
            return
    kv = _kv_blocks(text)
    if kv:
        kv.name = stem
        d.tables.append(kv)
        return
    if text.strip():
        d.docs.append(RawDoc("text", stem, text.strip()))


def _read_html(stem: str, html: str, d: Digest):
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover
        d.docs.append(RawDoc("text", stem, re.sub(r"<[^>]+>", " ", html)))
        return
    soup = BeautifulSoup(html, "html.parser")
    for i, t in enumerate(soup.find_all("table")):
        grid = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in t.find_all("tr")]
        d.tables.extend(detect_tables(grid, f"{stem} Tabelle {i + 1}" if i else stem, {}))
    text = soup.get_text("\n", strip=True)
    if text:
        d.docs.append(RawDoc("text", soup.title.get_text(strip=True) if soup.title else stem, text))


# --- spreadsheets ---------------------------------------------------------------------------

def _read_xlsx(stem: str, data: bytes, d: Digest):
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheets = [ws for ws in wb.worksheets if getattr(ws, "sheet_state", "visible") == "visible"] or wb.worksheets
    for ws in sheets:
        grid, formats = [], {}
        for r_idx, row in enumerate(ws.iter_rows()):
            vals = []
            for c_idx, cell in enumerate(row):
                v = getattr(cell, "value", None)
                vals.append(v)
                if v is not None and r_idx < 300 and c_idx not in formats:
                    nf = getattr(cell, "number_format", None)
                    if nf and nf != "General" and isinstance(v, (int, float)):
                        formats[c_idx] = nf
            grid.append(vals)
            if r_idx > 200000:
                d.notes.append(f"Blatt {ws.title}: nur die ersten 200.000 Zeilen gelesen.")
                break
        name = stem if len(sheets) == 1 else f"{stem} › {ws.title}"
        for t in detect_tables(grid, name, {"number_formats_by_col": formats, "locale": "de"}):
            t.sheet = ws.title
            d.tables.append(t)
    wb.close()


# --- table detection -----------------------------------------------------------------------

def _is_label(v) -> bool:
    if not isinstance(v, str):
        return False
    s = v.strip()
    if not s or len(s) > 60:
        return False
    if parse_number(s, "de") is not None or parse_number(s, "en") is not None:
        return False
    if parse_date(s) is not None:
        return False
    if "@" in s:
        return False
    return True


def _clean_grid(grid: list[list]) -> list[list]:
    out = []
    for row in grid:
        r = []
        for v in row:
            if isinstance(v, str):
                v = v.replace(" ", " ").strip()
                if v == "":
                    v = None
            r.append(v)
        out.append(r)
    width = 0
    for r in out:
        for j in range(len(r) - 1, -1, -1):
            if r[j] is not None:
                width = max(width, j + 1)
                break
    return [r[:width] + [None] * (width - len(r[:width])) for r in out]


def _nonempty(row) -> int:
    return sum(1 for v in row if v is not None)


def detect_tables(grid: list[list], name: str, meta: dict) -> list[RawTable]:
    rows = _clean_grid(grid)
    if not rows or not rows[0]:
        return []
    # split into blocks at runs of >= 2 empty rows
    blocks, cur, empty_run = [], [], 0
    for i, r in enumerate(rows):
        if _nonempty(r) == 0:
            empty_run += 1
            if empty_run >= 2 and cur:
                blocks.append(cur)
                cur = []
            continue
        empty_run = 0
        cur.append((i + 1, r))
    if cur:
        blocks.append(cur)
    tables = []
    pending_title: list[str] = []
    for bi, block in enumerate(blocks):
        t = _block_to_table(block, name, meta, pending_title)
        if t is None:
            # a block without a table (e.g. a title block) gives its text to the next table
            pending_title = [" ".join(str(v) for v in r if v is not None) for _, r in block][:5]
            continue
        pending_title = []
        tables.append(t)
    if len(tables) > 1:
        for k, t in enumerate(tables):
            if t.name == name:
                t.name = f"{name} ({k + 1})"
    for t in tables:
        _apply_debit_credit(t)
        if _is_crosstab(t.columns):
            t.meta["report"] = "Auswertung"  # months as columns: a pivot of other data, not records
    return tables


_PERIOD_HEAD = re.compile(r"^(jan\w*|feb\w*|m[aä]r\w*|apr\w*|mai|may|jun\w*|jul\w*|aug\w*|sep\w*|okt\w*|oct\w*|"
                          r"nov\w*|dez\w*|dec\w*|q[1-4]|kw\s?\d{1,2}|\d{4}|\d{1,2}/\d{2,4})\.?$", re.I)


def _is_crosstab(columns: list) -> bool:
    heads = [str(c).strip() for c in columns if c is not None and str(c).strip()]
    periods = sum(1 for h in heads if _PERIOD_HEAD.match(h))
    return periods >= 3 and periods >= 0.5 * len(heads)


def _block_to_table(block, name, meta, pending_title) -> RawTable | None:
    width = max(len(r) for _, r in block)
    if width < 2:
        return None
    best_i, best_score = None, 0.0
    for i, (_, r) in enumerate(block[:15]):
        ne = _nonempty(r)
        if ne < 2:
            continue
        labels = sum(1 for v in r if _is_label(v))
        label_share = labels / ne
        fill = ne / width
        nxt = [x for _, x in block[i + 1:i + 6]]
        if not nxt:
            continue
        nxt_fill = sum(_nonempty(x) for x in nxt) / (len(nxt) * width)
        # rows below a header are usually *not* all labels
        nxt_label = sum(sum(1 for v in x if _is_label(v)) / max(1, _nonempty(x)) for x in nxt) / len(nxt)
        score = label_share * (0.4 + 0.6 * fill) * (0.5 + 0.5 * min(1.0, nxt_fill / max(fill, 0.01)))
        score *= 1.0 if nxt_label < 0.95 else 0.85
        if label_share >= 0.7 and fill >= 0.34 and score > best_score + 1e-9:
            best_i, best_score = i, score
    title_lines = list(pending_title)
    if best_i is None:
        # no header: invent column names, everything is data
        first = block[0][1]
        if _nonempty(first) < 2:
            return None
        header = [None] * width
        data_rows = block
    else:
        title_lines += [" ".join(str(v) for v in r if v is not None) for _, r in block[:best_i]]
        header = block[best_i][1]
        data_rows = block[best_i + 1:]
    # data rows: sections, sums, repeated headers
    norm_header = [str(h).strip().lower() if h is not None else None for h in header]
    rows, lines, sections, totals = [], [], [], 0
    current_section = None
    for line, r in data_rows:
        ne = _nonempty(r)
        if ne == 0:
            continue
        if [str(v).strip().lower() if v is not None else None for v in r] == norm_header:
            continue
        first_val = next((v for v in r if v is not None), None)
        if lexicon.is_total_label(first_val) and ne <= max(2, int(0.75 * width)):
            totals += 1
            continue
        if ne <= max(3, int(0.5 * width)) and any(lexicon.is_balance_label(v) for v in r):
            totals += 1  # "Anfangssaldo", "Endsaldo", "Übertrag": a statement's balance, not a booking
            continue
        if ne == 1 and width >= 3 and isinstance(r[0], str) and r[0] is first_val and _is_label(r[0]):
            current_section = r[0].strip()
            sections.append(current_section)
            continue
        rows.append(list(r) + ([current_section] if sections else []))
        lines.append(line)
    if sections:
        header = list(header) + ["Gruppe"]
        width += 1
        # rows collected before the first section: pad
    if not rows:
        return None
    rows = [r + [None] * (width - len(r)) for r in rows]
    # column names
    names, seen = [], Counter()
    keep = []
    for j in range(width):
        has_data = any(r[j] is not None for r in rows)
        h = header[j] if j < len(header) else None
        h = str(h).strip() if h is not None else ""
        h = re.sub(r"\s+", " ", h).rstrip(":").strip()
        if isinstance(header[j] if j < len(header) else None, (datetime, date)):
            h = header[j].strftime("%d.%m.%Y")
        if not has_data:
            continue
        if not h:
            h = f"Spalte {j + 1}"
        seen[h] += 1
        if seen[h] > 1:
            h = f"{h} ({seen[h]})"
        names.append(h)
        keep.append(j)
    if len(keep) < 1:
        return None
    rows = [[r[j] for j in keep] for r in rows]
    nf_by_col = meta.get("number_formats_by_col") or {}
    number_formats = {str(k): nf_by_col[j] for k, j in enumerate(keep) if j in nf_by_col}
    tmeta = {k: v for k, v in meta.items() if k != "number_formats_by_col"}
    tmeta.update({"title": " · ".join(x for x in title_lines if x)[:300], "number_formats": number_formats,
                  "sections": len(sections), "skipped_totals": totals, "header_row": block[best_i][0] if best_i is not None else None})
    return RawTable(name=name, columns=names, rows=rows, lines=lines, meta=tmeta)


# --- json ------------------------------------------------------------------------------------

def _flatten(obj, prefix="", depth=0) -> tuple[dict, dict]:
    flat, nested = {}, {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and depth < 3:
            f2, n2 = _flatten(v, key + ".", depth + 1)
            flat.update(f2)
            nested.update(n2)
        elif isinstance(v, list):
            if v and all(isinstance(x, dict) for x in v):
                nested[key] = v
            else:
                flat[key] = ", ".join(str(x) for x in v if x is not None)
        else:
            flat[key] = v
    return flat, nested


_ID_FIELDS = ("id", "number", "nummer", "nr", "no", "key", "code", "uuid")


def _json_rows(items: list[dict], name: str, d: Digest, parent: tuple[str, list] | None = None):
    rows, cols, children = [], [], {}
    for idx, it in enumerate(items):
        flat, nested = _flatten(it)
        if parent:
            flat = {parent[0]: parent[1][idx], **flat}
        rows.append(flat)
        for k in flat:
            if k not in cols:
                cols.append(k)
        for k, v in nested.items():
            children.setdefault(k, []).append((idx, v))
    if not rows:
        return
    grid_rows = [[r.get(c) for c in cols] for r in rows]
    d.tables.append(RawTable(name=name, columns=cols, rows=grid_rows, lines=list(range(1, len(rows) + 1)),
                             meta={"format": "JSON"}))
    if children:
        id_col = next((c for c in cols if c.lower() in _ID_FIELDS or c.lower().endswith(("_id", "id", "number"))),
                      cols[0])
        parent_vals = [r.get(id_col) for r in rows]
        sg = name.rstrip("s")
        for k, lst in children.items():
            sub_items, keys = [], []
            for idx, v in lst:
                for x in v:
                    sub_items.append(x)
                    keys.append(parent_vals[idx])
            _json_rows(sub_items, f"{name}.{k}", d, parent=(f"{sg}_{id_col}", keys))


def _read_json(stem: str, data: bytes, d: Digest):
    text, _ = decode_text(data)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # JSON lines
        objs = [json.loads(l) for l in text.splitlines() if l.strip().startswith("{")]
        obj = objs
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            _json_rows(obj, stem, d)
        elif obj:
            d.tables.append(RawTable(stem, ["Wert"], [[x] for x in obj], list(range(1, len(obj) + 1)), meta={}))
    elif isinstance(obj, dict):
        found = False
        for k, v in obj.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                _json_rows(v, f"{stem}.{k}" if len(obj) > 1 else stem, d)
                found = True
            elif isinstance(v, dict) and v and all(isinstance(x, dict) for x in v.values()):
                items = [{"id": kk, **vv} for kk, vv in v.items()]
                _json_rows(items, f"{stem}.{k}", d)
                found = True
        if not found:
            flat, _ = _flatten(obj)
            d.tables.append(RawTable(stem, list(flat), [list(flat.values())], [1], meta={"format": "JSON"}))


# --- email / pdf / docx / zip ---------------------------------------------------------------

def _read_eml(stem: str, data: bytes, d: Digest):
    msg = BytesParser(policy=policy.default).parsebytes(data)
    subject = str(msg.get("subject") or stem)
    when = None
    try:
        if msg.get("date"):
            when = parsedate_to_datetime(str(msg.get("date")))
            when = when.replace(tzinfo=None)
    except (TypeError, ValueError):
        when = None
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        try:
            text = body.get_content()
        except (LookupError, KeyError):
            text = body.get_payload(decode=True).decode("utf-8", errors="replace")
        if body.get_content_type() == "text/html":
            try:
                from bs4 import BeautifulSoup
                text = BeautifulSoup(text, "html.parser").get_text("\n", strip=True)
            except ImportError:  # pragma: no cover
                text = re.sub(r"<[^>]+>", " ", text)
    for part in msg.iter_attachments():
        fn = part.get_filename()
        payload = part.get_payload(decode=True)
        if fn and payload:
            d.attachments.append((fn, payload))
    d.docs.append(RawDoc("email", subject, text.strip(), sender=str(msg.get("from") or "") or None,
                         recipients=str(msg.get("to") or "") or None, date=when,
                         meta={"attachments": [a for a, _ in d.attachments]}))


def _read_xml(stem: str, data: bytes, d: Digest):
    try:
        from defusedxml.ElementTree import fromstring  # no entity expansion, no external entities
    except ImportError:  # pragma: no cover
        from xml.etree.ElementTree import fromstring
    from .einvoice import parse, to_tables

    root = fromstring(data)
    inv = parse(root)
    if inv and inv.get("number"):
        head, lines, doc = to_tables(inv, stem)
        d.tables.append(head)
        if lines is not None:
            d.tables.append(lines)
        d.docs.append(doc)
        return
    text = " ".join(t.strip() for t in root.itertext() if t and t.strip())
    if text:
        d.docs.append(RawDoc("xml", stem, text[:200000]))


def _pdf_attachments(data: bytes, d: Digest):
    """ZUGFeRD/Factur-X: the structured invoice travels inside the PDF."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        for name, contents in (reader.attachments or {}).items():
            for content in contents:
                if name.lower().endswith(".xml") and content:
                    d.attachments.append((name, content))
    except Exception:
        pass


def _read_pdf(stem: str, data: bytes, d: Digest):
    _pdf_attachments(data, d)
    texts, grids = [], []
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages[:200]:
                texts.append(page.extract_text() or "")
                for t in page.extract_tables() or []:
                    if t and len(t) >= 3 and max(len(r) for r in t) >= 2:
                        grids.append(t)
    except ImportError:  # pragma: no cover
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        texts = [p.extract_text() or "" for p in reader.pages[:200]]
    for i, g in enumerate(grids):
        d.tables.extend(detect_tables(g, f"{stem} Tabelle {i + 1}", {"locale": "de"}))
    text = "\n".join(texts).strip()
    first = next((l.strip() for l in text.splitlines() if l.strip()), stem)
    d.docs.append(RawDoc("pdf", stem, text, meta={"first_line": first[:120]}))
    if not text:
        d.notes.append(f"{stem}.pdf enthält keinen Text (gescannt?) – aufbewahrt, aber nicht ausgelesen.")


def _read_docx(stem: str, data: bytes, d: Digest):
    import docx

    doc = docx.Document(io.BytesIO(data))
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    for i, t in enumerate(doc.tables):
        grid = [[c.text for c in row.cells] for row in t.rows]
        d.tables.extend(detect_tables(grid, f"{stem} Tabelle {i + 1}" if i else stem, {"locale": "de"}))
    if paras:
        d.docs.append(RawDoc("docx", stem, "\n".join(paras)))


def _read_zip(data: bytes, d: Digest):
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist()[:MAX_ZIP_MEMBERS]:
            if info.is_dir() or "__MACOSX" in info.filename or PurePath(info.filename).name.startswith("."):
                continue
            total += info.file_size
            if total > MAX_ZIP_TOTAL:
                d.notes.append("ZIP zu groß – nur ein Teil wurde gelesen.")
                break
            d.attachments.append((info.filename, z.read(info)))
