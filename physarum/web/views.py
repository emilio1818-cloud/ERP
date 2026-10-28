"""Presentation helpers: formatting values, choosing columns, building page models."""
from __future__ import annotations

import html
import math
from collections import Counter, defaultdict
from datetime import date, datetime

from markupsafe import Markup, escape

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
        return Markup(f'<span class="pill {status_class(s)}">{escape(s)}</span>')
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
    if f in ("gemahnt", "ueberfaellig", "mahnung", "overdue", "pending", "in pruefung", "unfulfilled"):
        return "warn"
    return "info"


def input_value(attr: dict, value) -> str:
    if value is None:
        return ""
    k = attr["kind"]
    if k == "money":
        return f"{float(value):.2f}".replace(".", ",")
    if k == "number":
        x = float(value)
        return str(int(x)) if x.is_integer() else str(x).replace(".", ",")
    if k == "percent":
        x = float(value) * 100
        return (str(int(x)) if abs(x - round(x)) < 1e-9 else f"{x:.1f}".replace(".", ","))
    if k == "date":
        return str(value)[:10]
    if k == "datetime":
        return str(value)[:16]
    return str(value)


def list_columns(spec: dict, limit: int = 7) -> list[dict]:
    """The columns a list shows: the most conductive attributes, in their natural order."""
    attrs = [a for a in spec["attrs"] if not a.get("hidden") and a.get("role") != "notes"]
    ranked = sorted(attrs, key=lambda a: -(a.get("salience") or 0))
    keep = ranked[:limit]
    order = {a["id"]: i for i, a in enumerate(spec["attrs"])}
    keep.sort(key=lambda a: (0 if a["id"] in (spec.get("key"), spec.get("title")) else 1, order[a["id"]]))
    return keep


def facets(rt, spec: dict, recs: list[dict], limit: int = 2) -> list[dict]:
    out = []
    cands = [a for a in spec["attrs"] if a.get("enum") and not a.get("hidden") and 2 <= len(a["enum"]) <= 12]
    cands.sort(key=lambda a: (0 if a.get("role") == "status" else 1, -(a.get("salience") or 0)))
    for a in cands[:limit]:
        cnt = Counter(str(r["data"].get(a["id"])) for r in recs if r["data"].get(a["id"]) is not None)
        out.append(dict(attr=a, values=cnt.most_common(12)))
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
        parts.append(f'<path class="tube" d="{path}" stroke-width="{width:.1f}" opacity="{op:.2f}"><title>Leitfähigkeit {d:.2f}</title></path>')
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
        parts.append(f'<a href="/t/{t["id"]}"><g class="node {t["kind"]}"><circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}"/>'
                     f'<text x="{x:.0f}" y="{y + r + 15:.0f}">{label}</text>'
                     f'<text class="sub" x="{x:.0f}" y="{y + r + 29:.0f}">{cnt:,}</text></g></a>'.replace(",", "."))
    parts.append("</svg>")
    return Markup("".join(parts))


def process_svg(rt, p: dict, open_counts: dict, w: int = 860) -> Markup:
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
        parts.append(f'<path class="tube" d="M{xs[i - 1]:.0f},{y} L{xs[i]:.0f},{y}" stroke-width="{width:.1f}"/>')
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
