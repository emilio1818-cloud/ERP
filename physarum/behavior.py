"""Behaviour learned from the records: formulas, defaults, numbering, thresholds.

Nothing here is configured. "Brutto = Netto + MwSt", "kg = Säcke × 60", "next invoice
number RE-2026-0165" and "Bestand must stay above Mindestbestand" are read off the data
and only kept if they hold for (almost) every record. Each rule carries its evidence.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import date

from .text import fold, tokens
from .values import parse_duration, as_date

NUMERIC = ("number", "money", "percent", "duration")
NICE = [0.07, 0.19, 0.16, 0.05, 1.07, 1.19, 1.16, 0.5, 2, 3, 4, 5, 6, 10, 12, 20, 24, 25, 30, 50, 60, 100, 1000, 0.01, 0.1]


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


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


def find_formulas(spec: dict, recs: list[dict]) -> list[dict]:
    attrs = [a for a in spec["attrs"] if a["kind"] in NUMERIC and not a.get("constant")]
    out = []
    if len(recs) < 8 or len(attrs) < 2:
        return out
    sample = recs[:800]
    col = {a["id"]: [_num(r["data"].get(a["id"])) for r in sample] for a in attrs}
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
            if accept(cid, ok, n):
                out.append(dict(attr=cid, op="scale", args=[a["id"]], k=k, ok=ok, n=n,
                                text=f"{c['name']} = {a['name']} × {_fmt_k(k)}"))
                used_targets.add(cid)
                deps[cid] = {a["id"]}
                break
    for f in out:
        f["share"] = round(f["ok"] / f["n"], 4)
    return out


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
                v = _num(r["data"].get(a["id"]))
                if v is not None:
                    sums[a["id"]][p] += v
        for pa in [a for a in parent["attrs"] if a["kind"] == "money" and not a.get("constant")]:
            for ca in cattrs:
                rows = []
                for r in precs:
                    pv = _num(r["data"].get(pa["id"]))
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
        if gaps and spec.get("kind") == "transaction":
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
            if not v or v.get("payments"):
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
                        xv, yv = _num(r["data"].get(x["id"])), _num(tr["data"].get(y["id"])) if tr else None
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
        t["numbering"] = find_numbering(t, recs, today)
        if t["numbering"] and _foreign_numbers(t, model):
            t["numbering"]["issues"] = []  # the supplier's numbers: gaps there are not ours to close
        t["defaults"] = find_defaults(t, recs)
        t["thresholds"] = find_thresholds(t)
    doc = next((t for t in model["types"] if t["kind"] == "document"), None)
    if doc:
        doc["count"] = len(records.get(doc["id"], []))
