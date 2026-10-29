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
from ..text import tokens
from ..values import asof_date

_ID_WORDS = {"nr", "nummer", "id", "no", "number", "code", "kennung"}
_POS_WORDS = {"pos", "position", "zeile", "lfd", "posnr", "line", "positionsnr"}
_VOLATILE = {"info", "status", "valuta", "valutadatum", "vermerk", "saldo", "kategorie"}


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
    """How current a version is: its own 'Stand', then when it arrived."""
    d = asof_date((t.get("meta") or {}).get("title")) or asof_date(t.get("source_name")) or asof_date(t.get("name"))
    return (d.isoformat() if d else "", t.get("added_at") or "", t.get("source_id") or 0, t["id"])


def _unique(ts: list[dict], cols: list[int], volatile: set[int] | None = None) -> bool:
    """A key column: (almost) always filled and unique in every version. A row exported twice
    (the same number with the same content) is an export error, not a second thing; a few
    numbers used twice with different content do not disqualify the column either."""
    volatile = volatile or set()
    for t in ts:
        first: dict[tuple, tuple] = {}
        n = filled = clashes = 0
        for r in t["rows"]:
            n += 1
            kv = tuple(_cell(r[j]) if j < len(r) else "" for j in cols)
            if not all(kv):
                continue
            filled += 1
            sig = _sig(r, volatile)
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


def key_columns(ts: list[dict], columns: list[str], volatile: set[int] | None = None) -> list[int] | None:
    idlike = []
    for j, name in enumerate(columns):
        toks = set(tokens(name))
        if lexicon.header_role(name) == "id" or toks & _ID_WORDS:
            idlike.append(j)
    for j in idlike:
        if _unique(ts, [j], volatile):
            return [j]
    pos = [j for j, name in enumerate(columns) if set(tokens(name)) & _POS_WORDS]
    for j in idlike:
        for k in pos:
            if k != j and _unique(ts, [j, k], volatile):
                return [j, k]
    return None


def _sig(row: list, volatile: set[int]) -> tuple:
    return tuple(_cell(v) for j, v in enumerate(row) if j not in volatile)


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
    key = key_columns(ts, columns, volatile) if len(ts) > 1 else None
    stale: dict[tuple[int, int], str] = {}  # rows the newest version no longer lists -> its file name
    if len(ts) == 1:
        keep = [(0, i) for i in range(len(founder["rows"]))]
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
                sig = _sig(r, volatile)
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
                if _sig(ts[ti]["rows"][ri], volatile) != sig and len(info["changed"]) < 200:
                    info["changed"].append(" / ".join(str(r[j]) for j in key))
        # rows the newest full snapshot no longer contains (an updated export, not the next period)
        newest, second = newest_first[0], newest_first[1]
        kn = {tuple(_cell(r[j]) if j < len(r) else "" for j in key) for r in newest["rows"]}
        ks = {tuple(_cell(r[j]) if j < len(r) else "" for j in key) for r in second["rows"]}
        ks.discard(tuple("" for _ in key))
        if ks and len(ks & kn) >= 0.8 * len(ks) and newest.get("source_id") != second.get("source_id"):
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
            per_source.setdefault(t.get("source_id"), Counter()).update(_sig(r, volatile) for r in t["rows"])
        superseded = _superseded(ts, columns, volatile, info)
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
                h = _sig(r, volatile)
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
    newest = max(ts, key=_rank) if len(ts) > 1 and key else founder
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


def _superseded(ts: list[dict], columns: list[str], volatile: set[int], info: dict) -> set[tuple[int, int]]:
    """Two exports of a list without numbers (time entries, bank lines) that overlap in time:
    for the days it covers, the newer export is right – an entry corrected or deleted in the
    other program is missing there. Only when the overlap shows they really are the same list
    (nine in ten rows identical); two people's time sheets with the same columns are not."""
    from ..values import parse_date
    files = {}
    for n, t in enumerate(ts):
        files.setdefault(t.get("source_id"), []).append(n)
    if len(files) < 2:
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
        sigs[sid] = Counter(_sig(ts[n]["rows"][i], volatile) for n in ns for i in range(len(ts[n]["rows"])))
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
                h = _sig(ts[n]["rows"][i], volatile)
                if left[h] > 0:
                    left[h] -= 1
                    same.append((n, i))
            if len(same) < 0.9 * len(inside):
                continue  # not clearly the same list: both stay
            gone = [x for x in inside if x not in set(same)]
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


def merge_versions(raw: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for t in raw:
        sig = tuple(" ".join(tokens(c)) for c in t["columns"])
        groups.setdefault(sig, []).append(t)
    return [merge_group(ts) for ts in groups.values()]

