"""Presentation helpers: formatting values, choosing columns, building page models."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, datetime

from markupsafe import Markup, escape

from ..text import fold
from ..values import as_date, display

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def money(x, currency: str = "EUR") -> str:
    if x is None:
        return "–"
    return display(x, "money", currency)


def fmt(rt, attr: dict, value, link: bool = True, short: bool = False) -> Markup:
    if value is None or value == "":
        return Markup('<span class="faint">–</span>')
    k = attr["kind"]
    if k == "ref":
        if isinstance(value, int) and value in rt.by_id:
            t = escape(rt.title(value))
            return Markup(f'<a href="/r/{value}">{t}</a>') if link else Markup(t)
        return Markup(f'{escape(str(value))} <span class="tag" title="Nicht verknüpft">?</span>')
    if k == "email":
        return Markup(f'<a href="mailto:{escape(value)}">{escape(value)}</a>') if link else Markup(escape(value))
    if k == "phone":
        tel = "".join(ch for ch in str(value) if ch.isdigit() or ch == "+")
        return Markup(f'<a href="tel:{tel}">{escape(value)}</a>') if link else Markup(escape(value))
    if k == "url":
        href = value if str(value).startswith("http") else f"https://{value}"
        return Markup(f'<a href="{escape(href)}" rel="noopener" target="_blank">{escape(value)}</a>')
    if k == "iban":
        s = str(value)
        return Markup(escape(" ".join(s[i:i + 4] for i in range(0, len(s), 4))))
    if k in ("money", "number", "percent", "duration", "date", "datetime", "bool"):
        return Markup(escape(display(value, k, attr.get("currency"))))
    s = str(value)
    if short and len(s) > 70:
        return Markup(f'<span title="{escape(s[:500])}">{escape(s[:68])}…</span>')
    if attr.get("role") == "status" or (attr.get("enum") and attr.get("role") in ("status",)):
        shown = show_value(s)
        tip = f' title="{escape(s)}"' if shown != s else ""
        return Markup(f'<span class="pill {status_class(s)}"{tip}>{escape(shown)}</span>')
    if attr.get("enum") and show_value(s) != s:
        return Markup(f'<span title="{escape(s)}">{escape(show_value(s))}</span>')
    if "\n" in s:
        return Markup("<br>".join(escape(x) for x in s.splitlines()))
    return Markup(escape(s))


def status_class(v: str) -> str:
    from ..lexicon import DONE_STATES, NEGATIVE_STATES
    from ..text import fold

    f = fold(str(v))
    if f in DONE_STATES:
        return "good"
    if f in NEGATIVE_STATES:
        return "bad"
    if f in ("ueberfaellig", "overdue"):
        return "bad"
    if f in ("gemahnt", "mahnung", "pending", "in pruefung", "unfulfilled", "teilbezahlt",
             "ueberzahlt", "partially paid", "partially_refunded"):
        return "warn"
    if f in ("offen", "open"):
        return "info"
    return "info"


def input_value(attr: dict, value) -> str:
    if value is None:
        return ""
    k = attr["kind"]
    num = isinstance(value, (int, float)) and not isinstance(value, bool)
    if k == "money" and num:
        return f"{float(value):.2f}".replace(".", ",")
    if k == "number" and num:
        x = float(value)
        return str(int(x)) if x.is_integer() else str(x).replace(".", ",")
    if k == "percent" and num:
        x = float(value) * 100
        return (str(int(x)) if abs(x - round(x)) < 1e-9 else f"{x:.1f}".replace(".", ","))
    if k in ("money", "number", "percent"):
        return str(value)  # "ca. 50 €" stays what it says
    if k == "date":
        return str(value)[:10]
    if k == "datetime":
        return str(value)[:16]
    return str(value)


def list_columns(spec: dict, limit: int | None = 7, pins: dict | None = None) -> list[dict]:
    """The columns a list shows: what the person pinned, then the most conductive attributes
    (as of the last growth – between two feedings the list does not rearrange itself)."""
    pins = pins or {}
    pinned, unpinned = set(pins.get("pin") or []), set(pins.get("unpin") or [])
    attrs = [a for a in spec["attrs"] if not a.get("hidden") and a.get("role") != "notes" and a["id"] not in unpinned]
    paid = any(a["id"] == "pay_state" for a in attrs)
    if paid:
        # the payment column says it with money; the stored status only on request
        attrs = [a for a in attrs if not (a.get("role") == "status" and a["id"] != "pay_state" and a["id"] not in pinned)]
    sal = {a["id"]: (a.get("salience") or 0) for a in attrs}
    for k in (spec.get("key"), spec.get("title")):
        if k in sal:
            sal[k] = 10.0
    if spec["kind"] == "transaction":
        # a transaction is read by its date; an invoice also by when it falls due
        when = next((a["id"] for a in attrs if a["kind"] in ("date", "datetime") and a.get("role") != "due"), None)
        if when:
            sal[when] = max(sal[when], 8.5)
        due = next((a["id"] for a in attrs if a.get("role") == "due"), None)
        if due and paid:
            sal[due] = max(sal[due], 8.0)
        if paid:
            # what is owed is the gross amount: it belongs next to "offen"
            from ..billing import money_fields
            g = money_fields(spec)["gross"]
            if g and g["id"] in sal:
                sal[g["id"]] = max(sal[g["id"]], 8.2)
    if paid:
        sal["pay_state"] = sal["pay_open"] = 9.0
    ranked = sorted(attrs, key=lambda a: (a["id"] not in pinned, -sal[a["id"]]))
    if limit is None:
        return ranked
    keep = ranked[:max(limit, len(pinned & set(sal)))]
    order = {a["id"]: i for i, a in enumerate(spec["attrs"])}
    keep.sort(key=lambda a: (0 if a["id"] in (spec.get("key"), spec.get("title")) else 1, order[a["id"]]))
    return keep


def related_columns(spec: dict, recs: list[dict], parent_type: str, limit: int = 6) -> list[dict]:
    """Columns for a few related records on a record page: what tells these rows apart. A column
    empty here, one that says the same in every row, or a date equal to another date is left out;
    a purpose or description is worth showing."""
    cand = [c for c in list_columns(spec, None) if not (c["kind"] == "ref" and c.get("ref") == parent_type)]
    notes = [a for a in spec["attrs"] if a.get("role") == "notes" and not a.get("hidden") and a["kind"] == "text"]
    sample = recs[:60]
    if not sample:
        return cand[:limit]

    def vals(c):
        return [r["data"].get(c["id"]) for r in sample]

    keep = []
    for c in cand + [n for n in notes[:1] if n not in cand]:
        v = vals(c)
        filled = [x for x in v if x not in (None, "")]
        if len(filled) < 0.3 * len(sample):
            continue
        essential = c["id"] in (spec.get("key"), spec.get("title")) or c["kind"] == "money"
        if len(sample) >= 3 and len({str(x) for x in filled}) == 1 and not essential:
            continue  # the same in every row here ("GUTSCHR. UEBERWEISUNG")
        if c["kind"] in ("date", "datetime") and any(
                o["kind"] in ("date", "datetime") and sum(1 for a, b in zip(v, vals(o)) if a == b) >= 0.9 * len(sample)
                for o in keep):
            continue  # "Wertstellung" next to "Buchungstag", "Ende" next to "Beginn"
        keep.append(c)
    note = next((c for c in keep if c.get("role") == "notes"), None)
    out = [c for c in keep if c is not note][:limit - (1 if note else 0)]  # the most telling ones …
    order = {a["id"]: i for i, a in enumerate(spec["attrs"])}
    out.sort(key=lambda a: (0 if a["id"] in (spec.get("key"), spec.get("title")) else 1, order[a["id"]]))  # … in file order
    if note:
        pos = next((i for i, c in enumerate(out) if c["kind"] in ("money", "number")), len(out))
        out.insert(pos, note)  # the purpose before the amounts
    return out


from ..lexicon import EN_VALUES, show_value  # noqa: E402,F401  (German display of English values)


def facet_key(v) -> str:
    from ..text import fold
    return " ".join(fold(show_value(v)).split())


def facets(rt, spec: dict, recs: list[dict], limit: int = 2) -> list[dict]:
    """Filter chips. "Café" and "Cafe", "Office" and "Büro" are one chip."""
    out = []
    cands = [a for a in spec["attrs"] if a.get("enum") and not a.get("hidden") and 2 <= len(a["enum"]) <= 14
             and (a.get("role") == "status" or a["id"] == "pay_state")]  # a BIC or a weekday is no way to look
    if any(a["id"] == "pay_state" for a in cands):
        cands = [a for a in cands if a["id"] == "pay_state" or a.get("role") != "status"]
    cands.sort(key=lambda a: (0 if a["id"] == "pay_state" else 1 if a.get("role") == "status" else 2,
                              -(a.get("salience") or 0)))
    # "Kundengruppe" from one file and "Segment" from another say the same: one chip row is enough
    picked = []
    for a in cands:
        keys = {facet_key(v) for v in (a.get("enum") or [])}
        if any(len(keys & {facet_key(v) for v in (b.get("enum") or [])}) >= 0.5 * min(len(keys), len(b.get("enum") or [1]))
               for b in picked):
            continue
        picked.append(a)
    for a in picked[:limit]:
        cnt, label = Counter(), {}
        variants: dict[str, Counter] = defaultdict(Counter)
        for r in recs:
            v = r["data"].get(a["id"])
            if v is None:
                continue
            k = facet_key(v)
            cnt[k] += 1
            variants[k][show_value(v)] += 1
        for k in cnt:
            label[k] = variants[k].most_common(1)[0][0]
        out.append(dict(attr=a, values=[(k, label[k], n) for k, n in cnt.most_common(12)]))
    return out


def spark(series: list[dict], w: int = 220, h: int = 38) -> Markup:
    vals = [s["value"] for s in series]
    if not vals or max(vals) == min(vals) == 0:
        return Markup("")
    lo, hi = min(0, min(vals)), max(vals) or 1
    n = len(vals)
    pts = [(i * (w - 4) / max(1, n - 1) + 2, h - 3 - (v - lo) / ((hi - lo) or 1) * (h - 8)) for i, v in enumerate(vals)]
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = d + f" L{pts[-1][0]:.1f},{h} L{pts[0][0]:.1f},{h} Z"
    last = pts[-1]
    return Markup(f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
                  f'<path class="area" d="{area}"/><path d="{d}"/>'
                  f'<circle cx="{last[0]:.1f}" cy="{last[1]:.1f}" r="2.8" fill="var(--accent-strong)"/></svg>')


def today_text(d: date | None = None) -> str:
    d = d or date.today()
    return f"{WEEKDAYS[d.weekday()]}, {d.day}. {MONTHS[d.month - 1]} {d.year}"


def greeting() -> str:
    h = datetime.now().hour
    return "Guten Morgen" if h < 11 else "Guten Tag" if h < 18 else "Guten Abend"


def ago(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return ts
    s = (datetime.now() - t).total_seconds()
    if s < 90:
        return "gerade eben"
    if s < 3600:
        return f"vor {int(s // 60)} Min."
    if s < 86400:
        return f"vor {int(s // 3600)} Std."
    if s < 86400 * 30:
        n = int(s // 86400)
        return "gestern" if n == 1 else f"vor {n} Tagen"
    return t.strftime("%d.%m.%Y")


def after_days(n) -> str:
    """'nach 1 Tag', 'nach 3 Tagen', 'nach 2 Wochen', 'am selben Tag'."""
    try:
        n = round(float(n))
    except (TypeError, ValueError):
        return str(n)
    if n <= 0:
        return "am selben Tag"
    if n == 1:
        return "nach 1 Tag"
    if n >= 21:
        return f"nach {round(n / 7)} Wochen"
    return f"nach {n} Tagen"


def days_text(n: int) -> str:
    if n == 0:
        return "heute"
    if n == 1:
        return "1 Tag"
    if n < 0:
        return f"in {-n} Tagen"
    if n >= 14:
        return f"{round(n / 7)} Wochen"
    return f"{n} Tage"


def organism_svg(rt, w: int = 900, h: int = 520, highlight: str | None = None) -> Markup:
    m = rt.model
    net = m.get("network") or {}
    pos = net.get("positions") or {}
    cond = net.get("conductivity") or {}
    types = [t for t in m["types"] if t["id"] in pos]
    if not types:
        return Markup("")
    pad = 70
    P = {t["id"]: (pad + pos[t["id"]][0] * (w - 2 * pad), pad + pos[t["id"]][1] * (h - 2 * pad)) for t in types}
    parts = [f'<svg class="organism" viewBox="0 0 {w} {h}" role="img" aria-label="Netz der erkannten Arten von Dingen">']
    for e in net.get("edges", []):
        a, b = e["a"], e["b"]
        if a not in P or b not in P:
            continue
        d = cond.get(e["id"], 0.0)
        (x1, y1), (x2, y2) = P[a], P[b]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = x2 - x1, y2 - y1
        cx, cy = mx - dy * 0.12, my + dx * 0.12  # a slight organic curve
        path = f"M{x1:.0f},{y1:.0f} Q{cx:.0f},{cy:.0f} {x2:.0f},{y2:.0f}"
        width = 1.2 + 11 * d
        op = 0.25 + 0.75 * d
        parts.append(f'<path class="tube" d="{path}" stroke-width="{width:.1f}" opacity="{op:.2f}"><title>Fluss {d:.2f}</title></path>')
        if d > 0.35:
            parts.append(f'<path class="flow" d="{path}" stroke-width="{max(1.2, width / 3):.1f}"/>')
    for t in types:
        x, y = P[t["id"]]
        r = 8 + 8.5 * math.log10(1 + (t.get("count") or 0))
        if t["kind"] == "line":
            r *= 0.6
        r = min(r, 38)
        label = escape(t["plural"])
        cnt = t.get("count") or 0
        # a long name at the edge would be cut off: it reads from the edge inwards instead
        half, tx, anchor = len(t["plural"]) * 3.7, x, "middle"
        if x - half < 4:
            tx, anchor = max(4.0, x - r), "start"
        elif x + half > w - 4:
            tx, anchor = min(w - 4.0, x + r), "end"
        how = f' style="text-anchor:{anchor}"' if anchor != "middle" else ""
        parts.append(f'<a href="/t/{t["id"]}"><g class="node {t["kind"]}"><circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}"/>'
                     f'<text x="{tx:.0f}" y="{y + r + 15:.0f}"{how}>{label}</text>'
                     f'<text class="sub" x="{tx:.0f}" y="{y + r + 29:.0f}"{how}>{cnt:,}</text></g></a>'.replace(",", "."))
    parts.append("</svg>")
    return Markup("".join(parts))


def process_svg(rt, p: dict, open_counts: dict, w: int = 860, slow: int | None = None) -> Markup:
    """The course of a process as a tube from stop to stop; `slow` marks the segment that takes longest."""
    steps = p["steps"]
    n = len(steps) + 1
    h = 150
    xs = [60 + i * (w - 120) / max(1, n - 1) for i in range(n)]
    y = 62
    parts = [f'<svg class="procmap" viewBox="0 0 {w} {h}" role="img" aria-label="Ablauf {escape(p["name"])}">']
    labels = [p["start"]["label"]] + [s["label"] for s in steps]
    shares = [1.0] + [s.get("share", 0) for s in steps]
    for i in range(1, n):
        width = 2 + 16 * shares[i]
        cls = "tube slow" if slow is not None and i - 1 == slow else "tube"
        parts.append(f'<path class="{cls}" d="M{xs[i - 1]:.0f},{y} L{xs[i]:.0f},{y}" stroke-width="{width:.1f}"/>')
        st = steps[i - 1]
        md = st.get("median_days")
        if md is not None:
            unit = "Tag" if round(md) == 1 else "Tage"
            parts.append(f'<text class="small" x="{(xs[i - 1] + xs[i]) / 2:.0f}" y="{y - 16}" text-anchor="middle">'
                         f'Ø {md:.0f} {unit} · {round(shares[i] * 100)} %</text>')
        oc = open_counts.get(st["id"])
        if oc:
            parts.append(f'<text class="small" x="{(xs[i - 1] + xs[i]) / 2:.0f}" y="{y + 30}" text-anchor="middle" '
                         f'fill="var(--bad)">{oc} offen</text>')
    for i in range(n):
        parts.append(f'<circle class="stop" cx="{xs[i]:.0f}" cy="{y}" r="11"/>')
        parts.append(f'<text x="{xs[i]:.0f}" y="{y + 58}" text-anchor="middle">{escape(labels[i])}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))


SHOWN = 7  # cards on Heute before "weitere Hinweise": what fits the first look


def cards(work: list[dict], plural_of) -> list[dict]:
    """One card per thing to do: what is overdue and what falls due soon at the same step together, the stock
    to reorder in one. Every item keeps the group it came from (its reason, its button). Hints, and what does
    not fit the first look, wait behind "weitere Hinweise"."""
    out, at = [], {}
    for g in work:
        key = (g["type"], g.get("step"), "due") if g["kind"] in ("overdue", "soon") else \
            (g["type"], "stock") if g["kind"] in ("threshold", "reach") else None
        items = [dict(x, _g=g) for x in g["items"]]
        c = at.get(key) if key else None
        if c is None:
            c = dict(g, items=items)
            out.append(c)
            if key:
                at[key] = c
            continue
        seen = {x["rid"] for x in c["items"]}
        new = [x for x in items if x["rid"] not in seen]
        c["items"] += new
        c["count"] += g["count"] - (len(items) - len(new))
        c["amount"] = round((c["amount"] or 0) + sum(x.get("money") or 0 for x in new), 2)
        c["severity"] = max(c["severity"], g["severity"])
        c["explain"] = " ".join(x if x.endswith(".") else x + "." for x in (c.get("explain"), g.get("explain")) if x)
        c["title"] = f"{plural_of(g['type'])} nachbestellen" if key[-1] == "stock" else \
            f"{c['title'].rsplit(' – ', 1)[0]} – überfällig und bald fällig"
    for k, c in enumerate(out):
        c["hidden"] = k >= SHOWN or c["severity"] < 2
    return out


def at_a_glance(rt, open_items: dict | None, n_files: int) -> str:
    """The firm in one plain paragraph: what there is, since when, how fast money comes in."""
    m = rt.model or {}
    procs = {p["type"]: p for p in m.get("processes", [])}
    kinds = [t for t in m.get("types", []) if t["kind"] in ("master", "transaction") and rt.records.get(t["id"])
             and (t.get("concept") or "") not in ("kontakt", "zeiteintrag", "kontobewegung")]
    kinds.sort(key=lambda t: -(t.get("salience") or 0))
    kinds = kinds[:5]
    kinds.sort(key=lambda t: (t["kind"] != "master", -(t.get("salience") or 0)))  # who first, then what happens
    parts = []
    for t in kinds:
        n = len(rt.records[t["id"]])
        txt = f"{display(n, 'number')} {t['plural'] if n != 1 else t['name']}"
        p = procs.get(t["id"])
        if p and t["kind"] == "transaction":
            ds = [as_date(r["data"].get(p["start"]["attr"])) for r in rt.records[t["id"]]]
            ds = [d for d in ds if d]
            if ds:
                first = min(ds)
                txt += f" seit {MONTHS[first.month - 1]} {first.year}"
        parts.append(txt)
    if not parts:
        return ""
    out = f"In {display(n_files, 'number')} {'Datei' if n_files == 1 else 'Dateien'} steckt Ihre Firma: " + \
        (", ".join(parts[:-1]) + " und " + parts[-1] if len(parts) > 1 else parts[0]) + "."
    inv = next((p for p in m.get("processes", []) if p.get("gross") and p.get("party")
                and (rt.spec(p["type"]) or {}).get("concept") == "rechnung" and not (rt.spec(p["type"]) or {}).get("incoming")), None)
    paid = next((s for s in (inv or {}).get("steps", []) if s.get("label") == "bezahlt" and s.get("median_days")), None)
    if paid:
        out += f" Rechnungen werden meist nach {round(paid['median_days'])} Tagen bezahlt"
        out += (f"; offen sind {display(open_items['n'] + open_items.get('partial', 0), 'number')} über "
                f"{money(open_items['amount'])}." if open_items else ".")
    elif open_items:
        out += f" Offen sind {display(open_items['n'] + open_items.get('partial', 0), 'number')} Rechnungen über {money(open_items['amount'])}."
    return out


def chain_view(c: dict) -> dict:
    """A value chain for the page: its tube, how long it usually takes and where the time goes."""
    nodes, segs = c["nodes"], c["segments"]
    pseudo = dict(name=c["title"], start=dict(label=nodes[0]),
                  steps=[dict(id=f"{c['id']}_{k}", label=nodes[k], median_days=sg["median"], share=sg["share"])
                         for k, sg in enumerate(segs, start=1)])
    t = c["total"]
    n = f"{t['n']:,}".replace(",", ".")
    lines = [f"Üblich {_days(t['median'])} von „{nodes[0]}“ bis „{nodes[-1]}“ (bei 80 % höchstens {_days(t['p80'])}), "
             f"aus {n} abgeschlossenen Fällen."]
    k = c.get("slowest")
    if k is not None and t["median"]:
        sg = segs[k]
        part = sg["median"] / t["median"]
        how = "fast die ganze Zeit" if part >= 0.85 else "gut zwei Drittel der Zeit" if part >= 0.6 else \
            "die Hälfte der Zeit" if part >= 0.45 else "gut ein Drittel der Zeit" if part >= 0.3 else None
        lines.append(f"Am längsten dauert „{sg['frm']} → {sg['to']}“: üblich {_days(sg['median'])}"
                     + (f" – {how}." if how else "."))
        if fold(sg["to"]) == "berechnet":
            lines.append(f"Rechnungen gleich nach „{sg['frm']}“ zu schreiben brächte das Geld früher.")
    return dict(c=c, svg=process_svg(None, pseudo, {}, slow=k), lines=lines)


def _days(x) -> str:
    v = round(float(x or 0), 1)
    v = int(v) if v == int(v) else v
    return f"{str(v).replace('.', ',')} {'Tag' if v == 1 else 'Tage'}"
