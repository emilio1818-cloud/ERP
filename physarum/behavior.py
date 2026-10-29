"""Behaviour learned from the records: formulas, defaults, numbering, thresholds.

Nothing here is configured. "Brutto = Netto + MwSt", "kg = Säcke × 60", "next invoice
number RE-2026-0165" and "Bestand must stay above Mindestbestand" are read off the data
and only kept if they hold for (almost) every record. Each rule carries its evidence.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from .text import fold, tokens
from .values import add_months, as_date, as_number, interval_months, next_occurrence, parse_duration, parse_period

NUMERIC = ("number", "money", "percent", "duration")
NICE = [0.07, 0.19, 0.16, 0.05, 1.07, 1.19, 1.16, 0.5, 2, 3, 4, 5, 6, 10, 12, 20, 24, 25, 30, 50, 60, 100, 1000, 0.01, 0.1]


def _close(x: float, y: float) -> bool:
    return abs(x - y) <= max(0.011, 0.0005 * abs(y))


def _holds(rows: list[tuple], f) -> tuple[int, int]:
    ok = n = 0
    for r in rows:
        try:
            pred = f(*r[:-1])
        except (ZeroDivisionError, OverflowError):
            continue
        if pred is None:
            continue
        n += 1
        if _close(pred, r[-1]):
            ok += 1
    return ok, n


def _nice(k: float) -> float:
    for c in NICE:
        if abs(k - c) <= 1e-6 * max(1, abs(c)):
            return c
    return round(k, 4)


_MAX_FORMULA_ATTRS = 16


def find_formulas(spec: dict, recs: list[dict]) -> list[dict]:
    attrs = [a for a in spec["attrs"] if a["kind"] in NUMERIC and not a.get("constant")]
    out = []
    if len(recs) < 8 or len(attrs) < 2:
        return out
    sample = recs[:800]
    if len(attrs) > _MAX_FORMULA_ATTRS:  # a wide export (a measurement grid, a pivot): look at the money first
        filled = Counter(a["id"] for r in sample for a in attrs if r["data"].get(a["id"]) is not None)
        attrs = sorted(attrs, key=lambda a: (a["kind"] != "money", -filled[a["id"]]))[:_MAX_FORMULA_ATTRS]
    col = {a["id"]: [as_number(r["data"].get(a["id"])) for r in sample] for a in attrs}
    attrs = _without_twins(attrs, col)
    used_targets = set()

    def rows_for(*ids):
        rr = []
        for i in range(len(sample)):
            vs = [col[x][i] for x in ids]
            if any(v is None for v in vs):
                continue
            rr.append(tuple(vs))
        return rr

    def accept(target, ok, n):
        return n >= 8 and ok / n >= 0.97 and target not in used_targets

    # c = a * b, a + b, a - b  (one formula per triple; the total is the target)
    covered: set[frozenset] = set()

    def total_like(a) -> int:
        return 1 if set(tokens(a["name"])) & {"brutto", "gesamt", "total", "summe", "gesamtpreis", "betrag"} else 0

    for c in sorted(attrs, key=lambda a: -total_like(a)):
        cid = c["id"]
        found = None
        for i, a in enumerate(attrs):
            for b in attrs[i + 1:]:
                if cid in (a["id"], b["id"]) or frozenset((a["id"], b["id"], cid)) in covered:
                    continue
                rows = rows_for(a["id"], b["id"], cid)
                if len(rows) < 8:
                    continue
                if any(r[0] == 0 for r in rows) and all(r[0] == 0 for r in rows):
                    continue
                for op, fn, sym in (("mul", lambda x, y: x * y, "×"), ("add", lambda x, y: x + y, "+")):
                    ok, n = _holds(rows, fn)
                    if accept(cid, ok, n):
                        # avoid "x + 0": the second term must vary
                        if op == "add" and len({r[1] for r in rows}) <= 1:
                            continue
                        if op == "mul" and (len({r[0] for r in rows}) <= 1 or len({r[1] for r in rows}) <= 1):
                            continue
                        found = dict(attr=cid, op=op, args=[a["id"], b["id"]], ok=ok, n=n,
                                     text=f"{c['name']} = {a['name']} {sym} {b['name']}")
                        break
                if found:
                    break
                for x, y in ((a, b), (b, a)):
                    rows2 = rows_for(x["id"], y["id"], cid)
                    ok, n = _holds(rows2, lambda p, q: p - q)
                    if accept(cid, ok, n) and len({r[1] for r in rows2}) > 1:
                        found = dict(attr=cid, op="sub", args=[x["id"], y["id"]], ok=ok, n=n,
                                     text=f"{c['name']} = {x['name']} − {y['name']}")
                        break
                if found:
                    break
            if found:
                break
        if found:
            out.append(found)
            used_targets.add(cid)
            covered.add(frozenset([found["attr"]] + found["args"]))
    # c = k * a, as long as the formulas stay free of cycles (Netto = Brutto × 0,93 would be one)
    deps = {f["attr"]: set(f["args"]) for f in out}

    def depends_on(x, y, seen=None) -> bool:
        seen = seen or set()
        for d in deps.get(x, ()):
            if d == y or (d not in seen and depends_on(d, y, seen | {d})):
                return True
        return False

    for c in attrs:
        cid = c["id"]
        if cid in used_targets:
            continue
        for a in attrs:
            if a["id"] == cid or depends_on(a["id"], cid):
                continue
            rows = [r for r in rows_for(a["id"], cid) if r[0] not in (0, None)]
            if len(rows) < 8:
                continue
            ratios = [r[1] / r[0] for r in rows]
            k = _nice(statistics.median(ratios))
            if k in (0, 1):
                continue
            ok, n = _holds(rows, lambda x: x * k)
            if (_tax_like(c) and not (k in _VAT_RATES and not _total_like(a))) or _tax_like(a):
                continue  # VAT is a legal rate of the net amount, not "Zahlbetrag × 0,1597" or "Netto = USt × 5,26"
            if accept(cid, ok, n):
                out.append(dict(attr=cid, op="scale", args=[a["id"]], k=k, ok=ok, n=n,
                                text=f"{c['name']} = {a['name']} × {_fmt_k(k)}"))
                used_targets.add(cid)
                deps[cid] = {a["id"]}
                break
    for f in out:
        f["share"] = round(f["ok"] / f["n"], 4)
    return out


_VAT_RATES = {0.19, 0.07, 0.16, 0.05}
_TAX_WORDS = {"ust", "mwst", "umsatzsteuer", "mehrwertsteuer", "vat", "tax", "steuer", "steuerbetrag"}
_TOTAL_WORDS = {"brutto", "gesamt", "total", "summe", "gesamtpreis", "betrag", "zahlbetrag", "endbetrag", "gross"}


def _tax_like(a: dict) -> bool:
    return bool(set(tokens(a["name"])) & _TAX_WORDS)


def _total_like(a: dict) -> bool:
    return bool(set(tokens(a["name"])) & _TOTAL_WORDS)


def _without_twins(attrs: list[dict], col: dict) -> list[dict]:
    """Two columns that say the same in nearly every row ("Zahlbetrag" is "Brutto" unless down payments
    were deducted) are one quantity for the arithmetic: the formulas are learned on the one that names
    the total, else on the first. Otherwise "USt = Zahlbetrag × 0,1597" would be learned."""
    drop = set()
    for i, a in enumerate(attrs):
        for b in attrs[i + 1:]:
            if a["id"] in drop or b["id"] in drop:
                continue
            pairs = [(x, y) for x, y in zip(col[a["id"]], col[b["id"]]) if x is not None and y is not None]
            if len(pairs) < 8 or sum(1 for x, y in pairs if _close(x, y)) < 0.9 * len(pairs):
                continue
            keep_b = ("brutto" in tokens(b["name"]) or _total_like(b) and not _total_like(a)) and \
                "brutto" not in tokens(a["name"])
            drop.add(a["id"] if keep_b else b["id"])
    return [a for a in attrs if a["id"] not in drop]


def _fmt_k(k: float) -> str:
    s = f"{k:.4f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def find_aggregates(model: dict, records: dict) -> list[dict]:
    """parent.total = Σ child.amount (× k): order totals from their lines."""
    out = []
    specs = {t["id"]: t for t in model["types"]}
    for rel in model["relations"]:
        if rel["kind"] not in ("parent", "ref"):
            continue
        child, parent = specs.get(rel["src"]), specs.get(rel["dst"])
        if not child or not parent or child["kind"] != "line":
            continue
        crecs = records.get(child["id"], [])
        precs = records.get(parent["id"], [])
        if len(precs) < 8:
            continue
        sums = defaultdict(lambda: defaultdict(float))
        cattrs = [a for a in child["attrs"] if a["kind"] in ("money",)]
        for r in crecs:
            p = r["data"].get(rel["attr"])
            if not isinstance(p, int):
                continue
            for a in cattrs:
                v = as_number(r["data"].get(a["id"]))
                if v is not None:
                    sums[a["id"]][p] += v
        for pa in [a for a in parent["attrs"] if a["kind"] == "money" and not a.get("constant")]:
            for ca in cattrs:
                rows = []
                for r in precs:
                    pv = as_number(r["data"].get(pa["id"]))
                    if pv is None or r["id"] not in sums[ca["id"]]:
                        continue
                    rows.append((sums[ca["id"]][r["id"]], pv))
                if len(rows) < 8:
                    continue
                ratios = [p / s for s, p in rows if s]
                if not ratios:
                    continue
                k = _nice(statistics.median(ratios))
                ok = sum(1 for s, p in rows if _close(s * k, p))
                if ok / len(rows) >= 0.95:
                    out.append(dict(attr=pa["id"], type=parent["id"], op="sum_children", rel=rel["id"],
                                    child=child["id"], child_attr=ca["id"], k=k, ok=ok, n=len(rows),
                                    share=round(ok / len(rows), 4),
                                    text=f"{pa['name']} = Summe {ca['name']} der {child['plural']}"
                                         + (f" × {_fmt_k(k)}" if k != 1 else "")))
                    break
    return out


def find_date_offsets(spec: dict, recs: list[dict], model: dict, records: dict) -> list[dict]:
    """due = date + n days, either constant or taken from the referenced party (Zahlungsziel)."""
    out = []
    dates = [a for a in spec["attrs"] if a["kind"] in ("date", "datetime")]
    dues = [a for a in dates if a.get("role") == "due"]
    if not dues or len(recs) < 8:
        return out
    by_id = {r["id"]: r for rs in records.values() for r in rs}
    specs = {t["id"]: t for t in model["types"]}
    for due in dues:
        best = None
        for base in dates:
            if base is due:
                continue
            diffs = []
            for r in recs:
                a, b = as_date(r["data"].get(base["id"])), as_date(r["data"].get(due["id"]))
                if a and b:
                    diffs.append(((b - a).days, r))
            if len(diffs) < 8:
                continue
            cnt = Counter(d for d, _ in diffs)
            k, kc = cnt.most_common(1)[0]
            share = kc / len(diffs)
            if share >= 0.9 and k >= 0:
                best = dict(attr=due["id"], op="date_add", args=[base["id"]], days=k, share=round(share, 3),
                            n=len(diffs), text=f"{due['name']} = {base['name']} + {k} Tage")
                break
            # offset from a duration attribute of the referenced party
            for ref in [a for a in spec["attrs"] if a["kind"] == "ref"]:
                tspec = specs.get(ref.get("ref"))
                if not tspec:
                    continue
                for dur in [a for a in tspec["attrs"] if a["kind"] == "duration"]:
                    ok = n = 0
                    for d, r in diffs:
                        target = by_id.get(r["data"].get(ref["id"]))
                        if not target:
                            continue
                        dv = parse_duration(target["data"].get(dur["id"]))
                        if dv is None:
                            continue
                        n += 1
                        if dv == d:
                            ok += 1
                    if n >= 8 and ok / n >= 0.9:
                        best = dict(attr=due["id"], op="date_add_ref", args=[base["id"]], ref=ref["id"],
                                    ref_attr=dur["id"], share=round(ok / n, 3), n=n,
                                    text=f"{due['name']} = {base['name']} + {dur['name']} (aus {tspec['name']})")
                        break
                if best:
                    break
            if best:
                break
            if share >= 0.6 and k > 0:
                best = dict(attr=due["id"], op="date_default", args=[base["id"]], days=k, share=round(share, 3),
                            n=len(diffs), text=f"{due['name']} meist {base['name']} + {k} Tage")
        if best:
            out.append(best)
    return out


def _period_style(v) -> str:
    s = fold(str(v or "")).strip()
    return "kw" if s.startswith(("kw", "woche", "kalenderwoche")) else "q" if s[:1] == "q" or "quartal" in s else \
        "alpha" if s[:1].isalpha() else "num"


def find_period_next(spec: dict, recs: list[dict]) -> list[dict]:
    """'Nächste Wartung' = 'Letzte Wartung' + 'Intervall' (jährlich, halbjährlich …) – learned when the
    firm's own list says so; it then moves on by itself when a maintenance is entered."""
    out = []
    pers = [a for a in spec["attrs"] if a.get("period") and a.get("role") == "due"]
    dates = [a for a in spec["attrs"] if a["kind"] in ("date", "datetime") and a.get("role") != "due"]
    ivs = [a for a in spec["attrs"] if a["kind"] == "text" and a.get("enum") and not a.get("period")]
    for p in pers:
        best = None
        for d in dates:
            for iv in ivs + [None]:
                if iv is None and best and best["args"][1:] and best["share"] >= 0.8:
                    break  # the list's own interval column says what is meant, even if the data deviates
                ok = n = 0
                for r in recs:
                    last, per = as_date(r["data"].get(d["id"])), parse_period(r["data"].get(p["id"]))
                    k = interval_months(r["data"].get(iv["id"])) if iv else 12
                    if not (last and per and k):
                        continue
                    n += 1
                    nxt = add_months(last, k)
                    if per[0] - timedelta(days=31) <= nxt <= per[1] + timedelta(days=31):
                        ok += 1
                if n >= 5 and ok >= 0.8 * n and (best is None or ok / n > best["share"]):
                    style = Counter(_period_style(r["data"].get(p["id"])) for r in recs
                                    if parse_period(r["data"].get(p["id"]))).most_common(1)[0][0]
                    like = next(str(r["data"][p["id"]]) for r in recs if parse_period(r["data"].get(p["id"]))
                                and _period_style(r["data"][p["id"]]) == style)
                    best = dict(attr=p["id"], op="period_next", args=[d["id"]] + ([iv["id"]] if iv else []),
                                months=None if iv else 12, like=like, share=round(ok / n, 3), n=n, on_change=True,
                                text=f"{p['name']} = {d['name']} + " + (iv["name"] if iv else "1 Jahr"))
            if best and best["share"] >= 0.95:
                break
        if best:
            out.append(best)
    return out


_NUMBERING = re.compile(r"^(?P<pre>\D*?)(?P<year>(?:19|20)\d\d|\d\d(?=[-/_.]\d))?(?P<sep>[-/_.]?)(?P<num>\d+)$")


def find_numbering(spec: dict, recs: list[dict], today: date | None = None) -> dict | None:
    """Numbering scheme of the key. Gaps and duplicates are reported for documents
    (GoBD: invoice numbers must be unique and without gaps)."""
    key = spec.get("key")
    if not key or len(recs) < 3:
        return None
    today = today or date.today()
    vals = [str(r["data"].get(key)) for r in recs if r["data"].get(key) is not None]
    schemes = Counter()
    parsed = []
    for v in vals:
        m = _NUMBERING.match(v.strip())
        if not m:
            continue
        sch = (m.group("pre"), len(m.group("year") or ""), m.group("sep"), len(m.group("num")))
        schemes[sch] += 1
        parsed.append((sch, m.group("year"), int(m.group("num")), v))
    if not schemes:
        return None
    sch, cnt = schemes.most_common(1)[0]
    if cnt / len(vals) < 0.9:
        return None
    pre, has_year, sep, width = sch
    nums_by_year = defaultdict(list)
    for s, y, n, v in parsed:
        if s == sch:
            nums_by_year[y].append(n)
    year = (str(today.year) if has_year == 4 else str(today.year)[2:]) if has_year else None
    cur = nums_by_year.get(year, []) if has_year else nums_by_year.get(None, [])
    nxt = (max(cur) + 1) if cur else 1
    example = f"{pre}{year}{sep}{str(nxt).zfill(width)}" if has_year else f"{pre}{sep}{str(nxt).zfill(width)}"
    # gaps and duplicates (GoBD: invoice numbers must be unique and gap-free)
    issues = []
    for y, nums in nums_by_year.items():
        c = Counter(nums)
        dups = sorted(n for n, k in c.items() if k > 1)
        s = sorted(c)
        gaps = [n for n in range(s[0], s[-1] + 1) if n not in c] if s and s[-1] - s[0] < 20000 else []
        lab = (lambda n: f"{pre}{y}{sep}{str(n).zfill(width)}") if has_year else (lambda n: f"{pre}{sep}{str(n).zfill(width)}")
        if gaps and spec.get("kind") == "transaction" and spec.get("concept") == "rechnung":
            # only invoices must be gap-free: a contract or an offer that was never made leaves an honest gap
            issues.append(dict(kind="gap", year=y, count=len(gaps), examples=[lab(n) for n in gaps[:5]]))
        if dups:
            issues.append(dict(kind="dup", year=y, count=len(dups), examples=[lab(n) for n in dups[:5]]))
    return dict(attr=key, prefix=pre, year=has_year, sep=sep, width=width, next=example, share=round(cnt / len(vals), 3),
                n=len(vals), issues=issues)


def find_defaults(spec: dict, recs: list[dict]) -> dict:
    out = {}
    if len(recs) < 10:
        return out
    for a in spec["attrs"]:
        if a.get("hidden") or a["kind"] in ("ref",) or a.get("role") in ("status", "id", "name", "notes", "email",
                                                                             "phone", "person", "street"):
            continue
        if not (a.get("enum") or a["kind"] in ("duration", "percent")):
            continue
        vals = [r["data"].get(a["id"]) for r in recs if r["data"].get(a["id"]) is not None]
        if len(vals) < 10:
            continue
        v, c = Counter(map(_hashable, vals)).most_common(1)[0]
        if c / len(vals) >= 0.6:
            out[a["id"]] = dict(value=v, share=round(c / len(vals), 3))
    return out


def _hashable(v):
    return tuple(v) if isinstance(v, list) else v


def find_thresholds(spec: dict) -> list[dict]:
    out = []
    attrs = [a for a in spec["attrs"] if a["kind"] == "number"]
    for m in attrs:
        toks = tokens(m["name"])
        joined = "".join(toks)
        for pre in ("mindest", "minimal", "min", "melde", "sicherheits", "soll"):
            if joined.startswith(pre) and len(joined) > len(pre) + 2:
                rest = joined[len(pre):]
                for a in attrs:
                    if a is m:
                        continue
                    aj = "".join(tokens(a["name"]))
                    if aj == rest or aj.endswith(rest) or rest.endswith(aj):
                        out.append(dict(attr=a["id"], min=m["id"], text=f"{a['name']} soll nicht unter {m['name']} fallen"))
                        break
                break
    return out


def virtual_sums(model: dict):
    """Documents whose amounts only live on their lines (orders) get a computed total."""
    specs = {t["id"]: t for t in model["types"]}
    for rel in model["relations"]:
        child, parent = specs.get(rel["src"]), specs.get(rel["dst"])
        if not child or not parent or child["kind"] != "line" or rel["kind"] not in ("parent", "ref"):
            continue
        if parent["kind"] != "transaction" or any(a["kind"] == "money" and not a.get("hidden") for a in parent["attrs"]):
            continue
        money = [a for a in child["attrs"] if a["kind"] == "money" and not a.get("hidden")]
        if not money:
            continue
        total = next((a for a in money if set(tokens(a["name"])) & {"gesamt", "summe", "total", "betrag"}), money[-1])
        if any(a.get("virtual") for a in parent["attrs"]):
            continue
        parent["attrs"].append(dict(id=f"sum_{rel['id']}", name="Summe", kind="money", role="money", fill=1.0,
                                    distinct=0, enum=None, constant=False, hidden=False, sources=[],
                                    currency=total.get("currency") or "EUR",
                                    virtual=dict(rel=rel["id"], child=child["id"], ref=rel["attr"], attr=total["id"]),
                                    explain=f"Summe „{total['name']}“ der {child['plural']}"))


def apply_virtual(model: dict, records: dict):
    """Fill computed totals into the in-memory records (never stored)."""
    specs = {t["id"]: t for t in model["types"]}
    for t in model["types"]:
        for a in t["attrs"]:
            v = a.get("virtual")
            if not v or v.get("payments") or v.get("stock") or v.get("recurring"):
                continue
            sums = defaultdict(float)
            for r in records.get(v["child"], []):
                p = r["data"].get(v["ref"])
                x = r["data"].get(v["attr"])
                if isinstance(p, int) and isinstance(x, (int, float)):
                    sums[p] += float(x)
            for r in records.get(t["id"], []):
                if r["id"] in sums:
                    r["data"][a["id"]] = round(sums[r["id"]], 2)


_LAST_WORDS = {"letzte", "letzter", "letztes", "zuletzt", "last", "durchgefuehrt", "erledigt", "geprueft"}
_NEXT_WORDS = {"naechste", "naechster", "naechstes", "next", "faellig", "geplant", "planung", "soll"}
_END_WORDS = {"gekuendigt", "kuendigung", "ende", "endet", "vertragsende", "bis"}


def find_recurring(spec: dict, recs: list[dict]) -> dict | None:
    """A maintenance contract: "letzte Wartung", "Intervall" and – sometimes – "nächste Wartung". The next
    date written by hand is often missing, out of date or "nach Absprache"; last date plus interval is not."""
    if len(recs) < 4:
        return None
    def share(aid, fn):
        vals = [_raw(r, aid) for r in recs]
        vals = [v for v in vals if v not in (None, "", "—", "-")]
        return (sum(1 for v in vals if fn(v)) / len(vals), len(vals)) if vals else (0.0, 0)
    ivs = [a for a in spec["attrs"] if a["kind"] == "text" and not a.get("virtual")
           and (lambda sh: sh[0] >= 0.6 and sh[1] >= 3)(share(a["id"], lambda v: interval_months(v) is not None))]
    lasts = [a for a in spec["attrs"] if a["kind"] in ("date", "datetime", "text") and not a.get("virtual")
             and set(tokens(a["name"])) & _LAST_WORDS and not set(tokens(a["name"])) & _NEXT_WORDS
             and share(a["id"], lambda v: next_occurrence(v, None) is not None)[0] >= 0.5]
    if not ivs or not lasts:
        return None
    last = lasts[0]
    noun = [w for w in tokens(last["name"]) if w not in _LAST_WORDS] or ["termin"]
    nxt = next((a for a in spec["attrs"] if a is not last and not a.get("virtual") and set(tokens(a["name"])) & _NEXT_WORDS
                and set(tokens(a["name"])) & set(noun)), None)
    end = next((a for a in spec["attrs"] if a["kind"] in ("date", "datetime") and set(tokens(a["name"])) & _END_WORDS), None)
    status = next((a for a in spec["attrs"] if a.get("role") == "status"), None)
    word = " ".join(noun).capitalize().replace("Pruefung", "Prüfung")
    return dict(attr=f"next_{last['id']}", last=last["id"], interval=ivs[0]["id"], next=nxt["id"] if nxt else None,
                end=end["id"] if end else None, status=status["id"] if status else None, name=f"{word} fällig",
                text=f"{word} fällig = {last['name']} + {ivs[0]['name']}" + (f"; „{nxt['name']}“, wenn später" if nxt else ""))


def _raw(r: dict, aid: str):
    """The value as read; for a date column, what could not be read as a day ("Okt. 2025") is in raw."""
    v = r["data"].get(aid)
    return v if v is not None else ((r.get("meta") or {}).get("raw") or {}).get(aid)


def recurring_due(rule: dict, r: dict, visit: date | None = None) -> tuple[str, str] | None:
    """(when it is due – a day or a month –, how it was reckoned) for one contract."""
    last = next_occurrence(_raw(r, rule["last"]), None)
    if visit and (not last or visit > last[1]):
        last = (visit, visit)  # the time sheet shows the visit the list does not have yet
    k = interval_months(_raw(r, rule["interval"]))
    computed = (add_months(last[0], k), add_months(last[1], k), "letzte + Intervall") if last and k else None
    planned = None
    if rule.get("next"):
        raw = _raw(r, rule["next"])
        # "KW 42" without a year is often last round's week: it only counts where nothing else is known
        yearless = bool(re.match(r"^\s*(kw|kalenderwoche|woche)\s*\.?\s*\d{1,2}\s*$", fold(str(raw or ""))))
        nx = next_occurrence(raw, last[1] if last else date.today() - timedelta(days=365))
        if nx and not (yearless and computed):
            planned = (nx[0], nx[1], "eingetragen")
    if computed and planned:
        # a later appointment moves it; an earlier or the same month is what the computed day says more exactly
        a, b, how = planned if planned[0] > computed[1] else computed
    elif computed or planned:
        a, b, how = computed or planned
    else:
        return None
    ends = []
    if rule.get("end"):
        ends.append(as_date(r["data"].get(rule["end"])))
    if rule.get("status"):
        m = re.search(r"(\d{1,2}\.\d{1,2}\.\d{2,4})", str(r["data"].get(rule["status"]) or ""))
        if m and "kuendig" in fold(str(r["data"].get(rule["status"]))):
            ends.append(as_date(m.group(1)))
    if any(e and a > e for e in ends):
        return None  # the contract has ended before
    value = a.isoformat() if a == b else (f"KW {a.isocalendar()[1]}/{a.isocalendar()[0]}" if (b - a).days == 6
                                         else f"{a.month:02d}/{a.year}")
    return value, how


def apply_recurring(model: dict, records: dict):
    """Fill the computed next date of every recurring contract into the in-memory records."""
    visits: dict[int, date] = {}
    for t in model["types"]:
        if t.get("concept") not in ("zeiteintrag", "stundenzettel"):
            continue
        refs = [a["id"] for a in t["attrs"] if a["kind"] == "ref"]
        d_attr = next((a["id"] for a in t["attrs"] if a["kind"] in ("date", "datetime")), None)
        for r in records.get(t["id"], []):
            d = as_date(r["data"].get(d_attr)) if d_attr else None
            for aid in refs:
                v = r["data"].get(aid)
                if d and isinstance(v, int) and (v not in visits or d > visits[v]):
                    visits[v] = d
    for t in model["types"]:
        rule = t.get("recurring")
        if not rule:
            continue
        for r in records.get(t["id"], []):
            got = recurring_due(rule, r, visits.get(r["id"]))
            if got:
                r["data"][rule["attr"]] = got[0]


def find_lookups(model: dict, records: dict) -> list[dict]:
    """Values that are copied from the referenced record at the time of entry:
    the unit price of an order line is (mostly) the article's list price."""
    specs = {t["id"]: t for t in model["types"]}
    by_id = {r["id"]: r for rs in records.values() for r in rs}
    out = []
    for t in model["types"]:
        recs = records.get(t["id"], [])
        if len(recs) < 10:
            continue
        for ref in [a for a in t["attrs"] if a["kind"] == "ref"]:
            dst = specs.get(ref.get("ref"))
            if not dst:
                continue
            for x in [a for a in t["attrs"] if a["kind"] == "money" and not a.get("hidden")]:
                for y in [a for a in dst["attrs"] if a["kind"] == "money" and not a.get("hidden")]:
                    pairs = []
                    for r in recs:
                        tr = by_id.get(r["data"].get(ref["id"]))
                        xv, yv = as_number(r["data"].get(x["id"])), as_number(tr["data"].get(y["id"])) if tr else None
                        if xv is not None and yv:
                            pairs.append((yv, xv))
                    if len(pairs) < 10:
                        continue
                    k = _nice(statistics.median(p / q for q, p in pairs))
                    ok = sum(1 for q, p in pairs if _close(q * k, p))
                    if ok / len(pairs) >= 0.7:
                        out.append(dict(type=t["id"], attr=x["id"], ref=ref["id"], src_type=dst["id"], src_attr=y["id"],
                                        k=k, share=round(ok / len(pairs), 3), n=len(pairs),
                                        text=f"{t['plural']}: {x['name']} meist = {dst['name']} › {y['name']}"
                                             + (f" × {_fmt_k(k)}" if k != 1 else "")))
                        break
            # the same party as the document it refers to (an invoice goes to the order's customer)
            if dst["kind"] != "transaction":
                continue
            for x in [a for a in t["attrs"] if a["kind"] == "ref" and a is not ref]:
                for y in [a for a in dst["attrs"] if a["kind"] == "ref" and a.get("ref") == x.get("ref")]:
                    n = ok = 0
                    for r in recs:
                        tr = by_id.get(r["data"].get(ref["id"]))
                        xv, yv = r["data"].get(x["id"]), tr["data"].get(y["id"]) if tr else None
                        if isinstance(xv, int) and isinstance(yv, int):
                            n += 1
                            ok += xv == yv
                    if n >= 5 and ok / n >= 0.9:
                        out.append(dict(type=t["id"], attr=x["id"], ref=ref["id"], src_type=dst["id"], src_attr=y["id"],
                                        kind="copy", share=round(ok / n, 3), n=n,
                                        text=f"{t['plural']}: {x['name']} = {dst['name']} › {y['name']}"))
                        break
    return out


def _foreign_numbers(t: dict, model: dict) -> bool:
    """Documents whose numbers another firm gives out (incoming invoices, supplier orders)."""
    specs = {x["id"]: x for x in model["types"]}
    for a in t["attrs"]:
        if a["kind"] == "ref" and specs.get(a.get("ref"), {}).get("concept") == "lieferant":
            return True
    return fold(t.get("name") or "").startswith(("eingang", "lieferantenrechnung"))


def infer_behavior(model: dict, records: dict, today: date | None = None):
    virtual_sums(model)
    apply_virtual(model, records)
    model["aggregates"] = find_aggregates(model, records)
    model["lookups"] = find_lookups(model, records)
    for t in model["types"]:
        if t["kind"] == "document":
            continue
        recs = records.get(t["id"], [])
        t["count"] = len(recs)
        t["formulas"] = find_formulas(t, recs)
        t["formulas"] += [a for a in model["aggregates"] if a["type"] == t["id"]]
        t["formulas"] += find_date_offsets(t, recs, model, records)
        t["formulas"] += find_period_next(t, recs)
        t["recurring"] = find_recurring(t, recs) if t["kind"] != "line" else None
        if t["recurring"] and not any(a["id"] == t["recurring"]["attr"] for a in t["attrs"]):
            rule = t["recurring"]
            t["attrs"].append(dict(id=rule["attr"], name=rule["name"], kind="text", role="due", period=True, fill=1.0,
                                   distinct=0, enum=None, constant=False, hidden=False, sources=[],
                                   virtual=dict(recurring=True), explain=rule["text"]))
        t["numbering"] = find_numbering(t, recs, today)
        t["incoming"] = bool(t.get("concept") == "rechnung" and _foreign_numbers(t, model))
        if t["numbering"] and t["incoming"]:
            t["numbering"]["issues"] = []  # the supplier's numbers: gaps there are not ours to close
        t["defaults"] = find_defaults(t, recs)
        t["thresholds"] = find_thresholds(t)
    apply_recurring(model, records)
    doc = next((t for t in model["types"] if t["kind"] == "document"), None)
    if doc:
        doc["count"] = len(records.get(doc["id"], []))
