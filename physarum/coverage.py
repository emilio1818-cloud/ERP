"""The organism's reward: how completely the firm is mapped.

Physarum grows towards food and keeps the tubes that carry it. Here the food is the firm's data:
rows that became things, references that found their target, documents that belong to a case,
business cases whose course is known, and the owner's answers. What is still missing is shown as
the next thing to feed it – never as a fault of the firm.
"""
from __future__ import annotations

from collections import Counter

from .lexicon import dative_plural
from .text import fold
from .store import loads

# business cases that have a course (ordered, delivered, invoiced, paid); bank rows and time sheets are facts
_NO_COURSE = {"kontobewegung", "zahlung", "stundenzettel", "zeiterfassung", "zeiteintrag", "abwesenheit", "dokument",
              "termin"}
# a bank line's counterparty need not be a known customer (rent, leasing, the tax office)
_FREE_REFS = {"kontobewegung", "zahlung", "dokument"}
_BULK = ("no-reply", "noreply", "newsletter", "news@", "mailer-daemon", "notifications@", "marketing@")

WEIGHTS = dict(rows=0.25, refs=0.3, docs=0.15, processes=0.2, answers=0.1)

# a time entry on "Intern – Teammeeting" names no project: internal work is a category, not a missing record
_INTERNAL = ("intern", "internal", "allgemein", "verwaltung", "buero", "orga", "organisation", "overhead",
             "gemeinkosten", "nicht abrechenbar", "non billable", "non-billable", "urlaub", "krank", "feiertag")


def _internal(examples: Counter) -> bool:
    vals = [fold(v) for v in examples]
    if not vals or len(vals) > 12 or sum(examples.values()) < 3 * len(vals):
        return False
    return all(any(v.startswith(w) or f" {w}" in v or f"{w} " in v for w in _INTERNAL) for v in vals)


def coverage(rt) -> dict:
    rt.ensure()
    m = rt.model
    if not m:
        return {}
    summ = rt.store.q1("SELECT summary FROM models ORDER BY version DESC LIMIT 1")
    stats = (loads(summ["summary"]) or {}).get("stats", {}) if summ else {}
    cov = stats.get("coverage") or {}
    parts, gaps = {}, []

    # 1. rows that became things (older versions of a list and pivot reports count as understood)
    if cov.get("rows_in"):
        done = cov.get("rows_used", 0) + cov.get("rows_report", 0) + cov.get("rows_versions", 0)
        parts["rows"] = dict(label="Zeilen zu Dingen geworden", value=min(1.0, done / cov["rows_in"]),
                             detail=f"{min(done, cov['rows_in']):,} von {cov['rows_in']:,} Zeilen".replace(",", "."))
        for x in cov.get("lost", [])[:3]:
            gaps.append(dict(weight=x["unused"], text=f"{x['unused']} Zeilen aus „{x['source']}“ gehören zu keinem Ding",
                             hint="Vielleicht Zwischensummen oder Notizen – sonst lohnt eine Rückfrage.", href="/quellen"))

    # 2. references that found their target
    total = ok = 0
    for spec in m["types"]:
        if (spec.get("concept") or "") in _FREE_REFS:
            continue
        refs = [a for a in spec["attrs"] if a["kind"] == "ref" and not a.get("hidden")]
        if not refs:
            continue
        for a in refs:
            n_ok = n_raw = 0
            examples = Counter()
            for r in rt.records.get(spec["id"], []):
                v = r["data"].get(a["id"])
                if isinstance(v, int) and not isinstance(v, bool):
                    n_ok += 1
                else:
                    raw = ((r.get("meta") or {}).get("raw") or {}).get(a["id"])
                    if raw not in (None, ""):
                        n_raw += 1
                        examples[str(raw)] += 1
            if n_raw and _internal(examples):
                n_raw = 0  # internal work, not a gap
            total += n_ok + n_raw
            ok += n_ok
            if n_raw:
                dst = rt.spec(a.get("ref")) or {}
                ex = ", ".join(f"„{k}“" for k, _ in examples.most_common(2))
                dp = dative_plural(dst.get("plural", "Einträge"))
                gaps.append(dict(weight=n_raw, href=f"/t/{spec['id']}",
                                 text=f"{n_raw} {spec['plural']} nennen bei „{a['name']}“ etwas, das es unter den "
                                      f"{dp} nicht gibt (z. B. {ex})",
                                 hint=f"Eine Liste mit diesen {dp} einwerfen – dann verbinden sie sich."))
    if total:
        parts["refs"] = dict(label="Verweise gefunden", value=ok / total,
                             detail=f"{ok:,} von {total:,} Verweisen".replace(",", "."))

    # 3. documents that belong to something
    # newsletters and notes about the files belong to no business case and are no gap
    docs = [d for d in rt.records.get("doc", []) if str(d["data"].get("doc_kind") or "") != "Text"
            and not any(w in fold(str(d["data"].get("doc_from") or "")) for w in _BULK)]
    if docs:
        linked = sum(1 for d in docs if rt.outrefs.get(d["id"]))
        parts["docs"] = dict(label="Dokumente einem Vorgang zugeordnet", value=linked / len(docs),
                             detail=f"{linked} von {len(docs)} Mails, PDFs und Texten")
        alone = [d for d in docs if not rt.outrefs.get(d["id"])]
        if alone:
            names = ", ".join(f"„{rt.title(d['id'])}“" for d in alone[:2])
            gaps.append(dict(weight=len(alone) * 3, href="/t/doc",
                             text=f"{len(alone)} {'Dokument nennt' if len(alone) == 1 else 'Dokumente nennen'} keinen Kunden, "
                                  f"Auftrag oder keine Rechnung, die Physarum kennt ({names})",
                             hint="Steht dort eine Nummer oder ein Name, fehlt die passende Liste."))

    # what only an older bank statement can tell: invoices that fell due before the first booking
    unseen = [e for e in rt.ledger.values() if e.get("unseen")]
    if unseen:
        first = min(e["unseen"] for e in unseen)
        by_type = Counter(e["type"] for e in unseen)
        what = ", ".join(f"{n} {(rt.spec(t) or {}).get('plural' if n != 1 else 'name', 'Rechnungen')}" for t, n in by_type.items())
        gaps.append(dict(weight=len(unseen) * 4, href="/quellen#einwerfen",
                         text=f"Ob {what} bezahlt {'ist' if len(unseen) == 1 else 'sind'}, zeigt erst ein Kontoauszug "
                              f"vor dem {first.strftime('%d.%m.%Y')}",
                         hint=f"{'Sie war' if len(unseen) == 1 else 'Sie waren'} fällig, bevor der eingeworfene "
                              f"Kontoauszug beginnt – ein älterer Auszug klärt es."))

    # 4. business cases whose course is known
    cases = [t for t in m["types"] if t["kind"] == "transaction" and (t.get("concept") or "") not in _NO_COURSE
             and len(rt.records.get(t["id"], [])) >= 2
             and any(a["kind"] in ("money",) or a.get("role") in ("due", "status") for a in t["attrs"])]
    if cases:
        with_proc = {p["type"] for p in m.get("processes", []) if p.get("steps") or p.get("deadlines")}
        known = [t for t in cases if t["id"] in with_proc]
        parts["processes"] = dict(label="Abläufe erkannt", value=len(known) / len(cases),
                                  detail=f"{len(known)} von {len(cases)} Arten von Vorgängen")
        for t in cases:
            if t["id"] not in with_proc:
                gaps.append(dict(weight=len(rt.records.get(t["id"], [])) / 5, href=f"/t/{t['id']}",
                                 text=f"Bei {dative_plural(t['plural'])} ist kein Ablauf zu erkennen",
                                 hint="Physarum liest Abläufe aus Datumsspalten („geliefert am“, „bezahlt am“). "
                                      "Ein Export mit solchen Spalten hilft."))

    # 5. the owner's answers
    qs = rt.store.q("SELECT status FROM questions WHERE status IN ('open', 'answered')")
    if qs:
        answered = sum(1 for q in qs if q["status"] == "answered")
        parts["answers"] = dict(label="Fragen beantwortet", value=answered / len(qs),
                                detail=f"{answered} von {len(qs)}")
        open_n = len(qs) - answered
        if open_n:
            gaps.append(dict(weight=open_n * 8, href="/fragen",
                             text=f"{open_n} {'Frage wartet' if open_n == 1 else 'Fragen warten'} auf Ihre Antwort",
                             hint="Jede Antwort gilt ab dem nächsten Wachstum für immer."))

    w = sum(WEIGHTS[k] for k in parts)
    score = sum(WEIGHTS[k] * p["value"] for k, p in parts.items()) / w if w else 0.0
    gaps.sort(key=lambda g: -g["weight"])
    return dict(score=score, parts=[dict(key=k, **p) for k, p in parts.items()], gaps=gaps[:6])
