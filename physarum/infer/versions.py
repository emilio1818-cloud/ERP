"""Versions of the same list: next month's export, an updated invoice book, overlapping bank
statements, the same file dropped in once more inside a zip.

Tables with identical columns are one list. A row that appears in several versions is one
row: with a key column (invoice number, customer number) the newest version speaks for it;
without a key (bank statements) a row counts as often as in the version that has it most
often, so overlapping statements do not double any booking. The founder of a list (the
first version that arrived) gives it its stable name; later versions never rename it.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime

from .. import lexicon
from ..text import fold, tokens
from ..values import asof_date

_ID_WORDS = {"nr", "nummer", "id", "no", "number", "code", "kennung"}
_POS_WORDS = {"pos", "position", "zeile", "lfd", "posnr", "line", "positionsnr"}
_VOLATILE = {"info", "status", "valuta", "valutadatum", "vermerk", "saldo", "kategorie"}
_NAME_WORDS = {"firma", "name", "firmenname", "lieferant", "kunde", "company", "supplier", "customer", "bezeichnung"}
# sa-26-001, re-2026-0042, 2026-0042 – with a separator: an IBAN or a mail address is no number of the thing
_CODE = re.compile(r"[a-z]{1,6}[-/.]\d[\w\-/.]*|\d{2,6}[-/]\d{2,6}")


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return repr(round(float(v), 6))
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return " ".join(str(v).split()).casefold()


def _rank(t: dict) -> tuple:
    """How current a version is: its own 'Stand', else the latest date it contains (an export made later
    knows later invoices), then when it arrived – an old file dropped in today does not become new."""
    d = asof_date((t.get("meta") or {}).get("title")) or asof_date(t.get("source_name")) or asof_date(t.get("name"))
    return (d.isoformat() if d else _latest(t), t.get("added_at") or "", t.get("source_id") or 0, t["id"])


def _latest(t: dict) -> str:
    """The latest date in a table's cells (not in the future), cached on the table."""
    if "_latest" in t:
        return t["_latest"]
    best = ""
    today = date.today().isoformat()
    for r in t["rows"][:5000]:
        for v in r:
            if isinstance(v, datetime):
                v = v.date()
            if isinstance(v, date):
                x = v.isoformat()
            elif isinstance(v, str) and 8 <= len(v) <= 10 and _DATE_LIKE.match(v):
                x = _iso(v)
            else:
                continue
            if x and best < x <= today:
                best = x
    t["_latest"] = best
    return best


_DATE_LIKE = re.compile(r"^(\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2})$")  # unambiguous only: not 09/01/2026


def _iso(v: str) -> str:
    from ..values import parse_date
    d = parse_date(v)
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat() if isinstance(d, date) else ""


def _unique(ts: list[dict], cols: list[int], volatile: set[int] | None = None, sig_of=None) -> bool:
    """A key column: (almost) always filled and unique in every version. A row exported twice
    (the same number with the same content) is an export error, not a second thing; a few
    numbers used twice with different content do not disqualify the column either."""
    volatile = volatile or set()
    sig_of = sig_of or _Sigs(volatile)
    for t in ts:
        first: dict[tuple, tuple] = {}
        n = filled = clashes = 0
        for r in t["rows"]:
            n += 1
            kv = tuple(_cell(r[j]) if j < len(r) else "" for j in cols)
            if not all(kv):
                continue
            filled += 1
            sig = sig_of(r)
            if kv in first:
                if first[kv] != sig:
                    clashes += 1
                continue
            first[kv] = sig
        if n and filled < 0.9 * n:
            return False
        if clashes > filled // 100:
            return False
    return True


def key_columns(ts: list[dict], columns: list[str], volatile: set[int] | None = None, sig_of=None) -> list[int] | None:
    idlike = []
    for j, name in enumerate(columns):
        toks = set(tokens(name))
        if lexicon.header_role(name) == "id" or toks & _ID_WORDS:
            idlike.append(j)
    for j in idlike:
        if _unique(ts, [j], volatile, sig_of):
            return [j]
    pos = [j for j, name in enumerate(columns) if set(tokens(name)) & _POS_WORDS]
    for j in idlike:
        for k in pos:
            if k != j and _unique(ts, [j, k], volatile, sig_of):
                return [j, k]
    # a number its heading does not call one: "Auftrag" SA-26-001, "Beleg" RE-2026-0042 – coded in every row
    for j in range(len(columns)):
        vals = [c for t in ts for r in t["rows"] if j < len(r) and (c := _cell(r[j]))]
        if j not in idlike and j not in (volatile or set()) and vals and \
                sum(1 for v in vals if _CODE.fullmatch(v)) >= 0.9 * len(vals) and _unique(ts, [j], volatile, sig_of):
            return [j]
    # a list of suppliers or customers without numbers is kept by name: in the next version, the row
    # with the same name is the same supplier (with a new bank account), not a second one
    concept = lexicon.concept_of(str(ts[0].get("name") or ""))
    if concept and lexicon.CONCEPTS[concept]["kind"] == "master" and len(ts) > 1:
        for j, name in enumerate(columns):
            if lexicon.header_role(name) == "name" or set(tokens(name)) & _NAME_WORDS:
                if _unique(ts, [j], volatile, sig_of):
                    return [j]
    return None


def _sig(row: list, volatile: set[int]) -> tuple:
    return tuple(_cell(v) for j, v in enumerate(row) if j not in volatile)


class _Sigs(dict):
    """Row signatures, computed once per merge (a 300.000-row export is compared several times)."""

    def __init__(self, volatile: set[int]):
        super().__init__()
        self.volatile = volatile

    def __call__(self, row: list) -> tuple:
        s = self.get(id(row))
        if s is None:
            s = self[id(row)] = _sig(row, self.volatile)
        return s


def merge_group(ts: list[dict]) -> dict:
    """One list from several versions. Returns the merged table dict (rows, lines as
    (table id, line), the founder's name as stable signature) plus what happened."""
    ts = sorted(ts, key=lambda t: (t.get("source_id") or 0, t["id"]))
    founder = ts[0]
    columns = founder["columns"]
    volatile = {j for j, c in enumerate(columns) if set(tokens(c)) & _VOLATILE}
    info = dict(versions=len(ts), files=len({t.get("source_id") for t in ts}), dropped=0, changed=[], vanished=[])
    keep: list[tuple[int, int]] = []  # (index of table in ts, row index)
    pos = {id(t): n for n, t in enumerate(ts)}
    sig_of = _Sigs(volatile)
    key = key_columns(ts, columns, volatile, sig_of)
    stale: dict[tuple[int, int], str] = {}  # rows the newest version no longer lists -> its file name
    if len(ts) == 1:
        seen_rows: set = set()
        for i, r in enumerate(founder["rows"]):
            kv = tuple(_cell(r[j]) if j < len(r) else "" for j in key) if key else None
            if kv and all(kv):
                sig = (kv, sig_of(r))
                if sig in seen_rows:
                    info["dropped"] += 1  # the same numbered row exported twice
                    continue
                seen_rows.add(sig)
            keep.append((0, i))
    elif key:
        newest_first = sorted(ts, key=_rank, reverse=True)
        owner: dict[tuple, int] = {}            # key -> the version that speaks for it
        first: dict[tuple, tuple[int, int]] = {}
        sigs: dict[tuple, set] = {}
        for t in newest_first:
            p = pos[id(t)]
            for i, r in enumerate(t["rows"]):
                kv = tuple(_cell(r[j]) if j < len(r) else "" for j in key)
                if not all(kv):
                    keep.append((p, i))
                    continue
                sig = sig_of(r)
                if kv not in owner:
                    owner[kv], first[kv], sigs[kv] = p, (p, i), {sig}
                    keep.append((p, i))
                    continue
                if owner[kv] == p:
                    # the same number twice in one version: a row exported twice is one row,
                    # a different row under the same number stays (and is reported elsewhere)
                    if sig in sigs[kv]:
                        info["dropped"] += 1
                    else:
                        sigs[kv].add(sig)
                        keep.append((p, i))
                    continue
                info["dropped"] += 1
                ti, ri = first[kv]
                if sig_of(ts[ti]["rows"][ri]) != sig and len(info["changed"]) < 200:
                    info["changed"].append(" / ".join(str(r[j]) for j in key))
        # rows the newest full snapshot no longer contains (an updated export, not the next period); an
        # invoice that came as a file of its own is no snapshot of anything – the next file is another invoice
        newest, second = newest_first[0], newest_first[1]
        kn = {tuple(_cell(r[j]) if j < len(r) else "" for j in key) for r in newest["rows"]}
        ks = {tuple(_cell(r[j]) if j < len(r) else "" for j in key) for r in second["rows"]}
        ks.discard(tuple("" for _ in key))
        documents = all((t.get("meta") or {}).get("structured") for t in ts)
        if ks and len(ks & kn) >= 0.8 * len(ks) and newest.get("source_id") != second.get("source_id") and not documents:
            gone = []
            src = newest.get("source_name") or newest.get("name")
            for t in newest_first[1:]:
                for i, r in enumerate(t["rows"]):
                    kv = tuple(_cell(r[j]) if j < len(r) else "" for j in key)
                    if all(kv) and kv not in kn:
                        gone.append(" / ".join(str(r[j]) for j in key))
                        stale[(t["id"], t["lines"][i] if i < len(t["lines"]) else i + 1)] = src
            info["vanished"] = sorted(set(gone))[:200]
            info["vanished_n"] = len(set(gone))
            info["vanished_from"] = src
    else:
        # sheets of one workbook are parts of one list, not versions of it: count per file
        per_source: dict = {}
        for t in ts:
            per_source.setdefault(t.get("source_id"), Counter()).update(sig_of(r) for r in t["rows"])
        superseded = _superseded(ts, columns, volatile, info, sig_of)
        most: Counter = Counter()
        for cnt in per_source.values():
            for h, n in cnt.items():
                most[h] = max(most[h], n)
        used: Counter = Counter()
        for n, t in enumerate(ts):  # oldest first: rows keep the provenance they already had
            for i, r in enumerate(t["rows"]):
                if (n, i) in superseded:
                    info["dropped"] += 1
                    continue
                h = sig_of(r)
                if used[h] < most[h]:
                    used[h] += 1
                    keep.append((n, i))
                else:
                    info["dropped"] += 1
    keep.sort()
    extra = _sheet_column(ts)
    if extra:
        header, per_table = extra
        columns = list(columns) + [header]
        rows = [list(ts[n]["rows"][i]) + [per_table[n]] for n, i in keep]
    else:
        rows = [ts[n]["rows"][i] for n, i in keep]
    lines = [(ts[n]["id"], ts[n]["lines"][i] if i < len(ts[n]["lines"]) else i + 1) for n, i in keep]
    names = [t["name"] for t in ts]
    stems = {nm.split(" › ")[0] for nm in names}
    if len(set(names)) == 1:
        label = names[0]
    elif len(stems) == 1 and all(t.get("sheet") for t in ts):
        label = f"{names[0].split(' › ')[0]} › " + " + ".join(dict.fromkeys(t["sheet"] for t in ts))
    else:
        label = founder["name"]
    srcs = list(dict.fromkeys(t.get("source_name") for t in ts))
    # the list is as current as its newest version: its "Stand", its title (the founder only names it)
    newest = max(ts, key=_rank) if len(ts) > 1 else founder  # also a statement without numbers
    meta = dict(founder.get("meta") or {})
    if newest is not founder:
        meta["title"] = (newest.get("meta") or {}).get("title") or meta.get("title")
        if asof_date((newest.get("meta") or {}).get("title")) is None and asof_date(newest.get("source_name")):
            meta["title"] = f"{meta.get('title') or ''} Stand {asof_date(newest.get('source_name')).strftime('%d.%m.%Y')}".strip()
    return dict(founder, meta=meta, name=label, sig_name=founder["name"], columns=columns, rows=rows, lines=lines,
                tables=[t["id"] for t in ts],
                source_id=max(t.get("source_id") or 0 for t in ts), sources=srcs,
                source_name=srcs[0] if len(srcs) == 1 else f"{srcs[0]} + {len(srcs) - 1} weitere",
                added_at=max(t.get("added_at") or "" for t in ts), versions=info, key_cols=key, stale=stale)


def _date_col(ts: list[dict], columns: list[str]) -> int | None:
    """The column that says when a row happened (booking day, start of a time entry)."""
    from ..values import parse_date
    best, best_share = None, 0.0
    rows = [r for t in ts for r in t["rows"][:300]]
    if not rows:
        return None
    for j, name in enumerate(columns):
        role = lexicon.header_role(name)
        vals = [r[j] for r in rows if j < len(r) and r[j] not in (None, "")]
        if len(vals) < 0.9 * len(rows):
            continue
        ok = sum(1 for v in vals if parse_date(v, "mdy" if "/" in str(v) else "dmy") is not None)
        share = ok / len(vals)
        if share >= 0.95 and (share > best_share or role in ("date",) and best is not None and share >= best_share):
            best, best_share = j, share
    return best


def _superseded(ts: list[dict], columns: list[str], volatile: set[int], info: dict, sig_of=None) -> set[tuple[int, int]]:
    """Two exports of a list without numbers (time entries, bank lines) that overlap in time:
    for the days it covers, the newer export is right – an entry corrected or deleted in the
    other program is missing there. Only when the overlap shows they really are the same list
    (three in four rows identical); two people's time sheets with the same columns are not. Bank
    statements are left alone: a booking never changes, a missing one means a shorter export."""
    from ..values import parse_date
    sig_of = sig_of or _Sigs(volatile)
    files = {}
    for n, t in enumerate(ts):
        files.setdefault(t.get("source_id"), []).append(n)
    if len(files) < 2 or lexicon.concept_of(str(ts[0].get("name") or "")) == "kontobewegung":
        return set()
    j = _date_col(ts, columns)
    if j is None:
        return set()

    def day(v):
        d = parse_date(v, "mdy" if isinstance(v, str) and "/" in v else "dmy")
        return d.date() if isinstance(d, datetime) else d

    span, sigs = {}, {}
    for sid, ns in files.items():
        ds = [day(ts[n]["rows"][i][j]) for n in ns for i in range(len(ts[n]["rows"])) if j < len(ts[n]["rows"][i])]
        ds = [d for d in ds if d is not None]
        if not ds:
            continue
        span[sid] = (min(ds), max(ds))
        sigs[sid] = Counter(sig_of(ts[n]["rows"][i]) for n in ns for i in range(len(ts[n]["rows"])))
    order = sorted(span, key=lambda sid: max(_rank(ts[n]) for n in files[sid]), reverse=True)
    out: set[tuple[int, int]] = set()
    for k, newer in enumerate(order):
        lo, hi = span[newer]
        for older in order[k + 1:]:
            inside = [(n, i) for n in files[older] for i, r in enumerate(ts[n]["rows"])
                      if (n, i) not in out and j < len(r) and (d := day(r[j])) is not None and lo <= d <= hi]
            if len(inside) < 3:
                continue
            left = Counter(sigs[newer])
            same = []
            for n, i in inside:
                h = sig_of(ts[n]["rows"][i])
                if left[h] > 0:
                    left[h] -= 1
                    same.append((n, i))
            if len(same) < 0.75 * len(inside):
                continue  # not clearly the same list: both stay
            kept = set(same)
            gone = [x for x in inside if x not in kept]
            out.update(gone)
            if gone:
                info.setdefault("superseded", 0)
                info["superseded"] += len(gone)
                info["superseded_by"] = ts[files[newer][0]].get("source_name")
    return out


_PERIOD = re.compile(r"^(?:\d{4}|\d{1,2}[./-]?\d{2,4}|q[1-4]|kw\s?\d{1,2}|"
                     r"jan\w*|feb\w*|m[aä]r\w*|apr\w*|mai|may|jun\w*|jul\w*|aug\w*|sep\w*|okt\w*|oct\w*|"
                     r"nov\w*|dez\w*|dec\w*)(?:\s+\d{2,4})?$", re.I)


def _sheet_column(ts: list[dict]) -> tuple[str, list[str]] | None:
    """Sheets of one workbook that differ by *who* or *what* (one sheet per fitter, per branch)
    carry that information in their name or title. Merged into one list, it becomes a column;
    sheets that are only periods (2025, 2026, Januar) need none, the dates say it."""
    if len(ts) < 2 or len({t.get("source_id") for t in ts}) != 1 or not all(t.get("sheet") for t in ts):
        return None
    sheets = [str(t["sheet"]).strip() for t in ts]
    if all(_PERIOD.match(x) for x in sheets) or len(set(sheets)) < len(sheets):
        return None
    titles = [str((t.get("meta") or {}).get("title") or "") for t in ts]
    values = sheets
    if all(titles):
        pre = _common_prefix(titles)
        suf = _common_prefix([x[::-1] for x in titles])[::-1]
        var = [x[len(pre):len(x) - len(suf) if suf else None].strip(" -–—:|,") for x in titles]
        if all(var) and len(set(var)) == len(var):
            values = var
    values = [re.sub(r"\s*\([^)]*\)", "", v).strip() or v for v in values]
    people = sum(1 for v in values if lexicon.looks_like_person(v))
    wordy = all(1 <= len(v.split()) <= 3 and not any(ch.isdigit() for ch in v) for v in values)
    return ("Mitarbeiter" if wordy and people >= 0.5 * len(values) else "Blatt"), values


def _common_prefix(xs: list[str]) -> str:
    if not xs:
        return ""
    p = xs[0]
    for x in xs[1:]:
        while not x.startswith(p):
            p = p[:-1]
            if not p:
                return ""
    # do not cut inside a word
    return p if not p or p[-1] in " -–—:|,(" else p[:max(p.rfind(" "), 0) + 1] if " " in p else ""


def _list_name(t: dict) -> str:
    """'Projektliste_2025-2026 › Aktiv', 'hubspot-crm-exports-all-contacts-2026-10-27': the list, without dates."""
    return re.sub(r"[^a-zäöüß›]+", "", str(t.get("name") or "").casefold())


def _align(ts: list[dict], columns: list[str]) -> list[dict]:
    """Versions whose columns differ a little (an empty column left out, one added): one layout."""
    out = []
    for t in ts:
        if t["columns"] == columns:
            out.append(t)
            continue
        pos = {" ".join(tokens(c)): j for j, c in enumerate(t["columns"])}
        idx = [pos.get(" ".join(tokens(c))) for c in columns]
        rows = [[(r[j] if j is not None and j < len(r) else None) for j in idx] for r in t["rows"]]
        out.append(dict(t, columns=list(columns), rows=rows))
    return out


_SHEET_STATES = {"aktiv", "aktive", "laufend", "offen", "inaktiv", "archiv", "archiviert", "abgeschlossen",
                 "abgeschlossene", "erledigt", "storniert", "geplant", "pausiert", "beendet", "gekuendigt",
                 "abgelehnt", "angenommen", "done", "active", "closed", "open"}


def _sheet_status(t: dict) -> dict:
    """A sheet called "Abgeschlossen" says the status of every row on it."""
    sheet = fold(str(t.get("sheet") or "")).strip()
    if sheet not in _SHEET_STATES and sheet not in lexicon.DONE_STATES and sheet not in lexicon.NEGATIVE_STATES:
        return t
    if any(lexicon.header_role(c) == "status" for c in t["columns"]):
        return t
    name = str(t["sheet"]).strip()
    return dict(t, columns=list(t["columns"]) + ["Status"], rows=[list(r) + [name] for r in t["rows"]])


def merge_versions(raw: list[dict]) -> list[dict]:
    raw = [_sheet_status(t) for t in raw]
    groups: dict[tuple, list[dict]] = {}
    for t in raw:
        sig = tuple(" ".join(tokens(c)) for c in t["columns"])
        groups.setdefault(sig, []).append(t)
    # the same list from another delivery, with a column more or less: still a version of it
    sigs = list(groups)
    for i, a in enumerate(sigs):
        if a not in groups:
            continue
        for b in sigs[i + 1:]:
            if b not in groups or a == b:
                continue
            sa, sb = set(a), set(b)
            names_a = {_list_name(t) for t in groups[a]}
            names_b = {_list_name(t) for t in groups[b]}
            if not (names_a & names_b) or len(sa & sb) < max(3, 0.8 * max(len(sa), len(sb))):
                continue
            if {t.get("source_id") for t in groups[a]} & {t.get("source_id") for t in groups[b]}:
                continue  # two blocks of one file are two lists, not two versions
            cols = list(groups[a][0]["columns"]) + [c for c in groups[b][0]["columns"]
                                                    if " ".join(tokens(c)) not in sa]
            groups[a] = _align(groups[a] + groups.pop(b), cols)
    return [merge_group(ts) for ts in groups.values()]

