"""The Verfahrensdokumentation (GoBD) writes itself: where the data comes from, which rules work on it,
what people decided, how nothing gets lost. This module turns the stored decisions into sentences a
tax auditor can read; the page arranges them in the usual chapters."""
from __future__ import annotations

import json

from .store import loads, parse_pair


def _ident_title(rt, ident: str) -> str:
    """'k:k-10007' or 'n:wattwurm' -> the record's name as shown, or the value itself."""
    r = rt.store.q1("SELECT record_id FROM idents WHERE ident=? LIMIT 1", (ident,))
    if r and r["record_id"] in rt.by_id:
        return rt.title(r["record_id"])
    return ident.split(":", 1)[-1]


def _attr(rt, aid: str):
    for t in rt.model.get("types", []):
        for a in t["attrs"]:
            if a["id"] == aid:
                return t, a
    return None, None


def _plural(rt, tid: str) -> str:
    s = rt.spec(tid)
    return s["plural"] if s else tid


def decision_text(rt, d: dict) -> str:
    """One human decision as a sentence."""
    kind, subj = d["kind"], d["subject"]
    v = loads(d["value"]) if isinstance(d.get("value"), str) else d.get("value")
    try:
        if kind == "same_record":
            parts = subj.split("|")
            if len(parts) == 2:
                a, b = (_ident_title(rt, x) for x in parts)
                return f"„{a}“ und „{b}“ sind {'derselbe Eintrag' if v == 'same' else 'verschiedene Einträge'}."
        if kind == "same_type":
            pair = parse_pair(subj)
            if pair:
                a, b = (x.split("|")[0] for x in pair)
                return f"Die Listen „{a}“ und „{b}“ {'gehören zu einer Art von Dingen' if v == 'same' else 'sind verschiedene Arten'}."
        if kind == "relation":
            parts = subj.split("|")
            if len(parts) == 4:
                _, src, attr, dst = parts
                if rt.spec(src):
                    _, a = _attr(rt, attr)
                    name = (a or {}).get("name") or attr
                    return f"„{name}“ bei {_plural(rt, src)} {'verweist auf' if v == 'yes' else 'ist kein Verweis auf'} {_plural(rt, dst)}."
                return f"„{attr}“ bei {src} {'verweist auf' if v == 'yes' else 'ist kein Verweis auf'} {dst}."
        if kind == "payment_match":
            return f"Zahlungszuordnung ({subj}): {'zugeordnet' if v == 'yes' else 'nicht zugeordnet'}."
        if kind == "auto":
            return f"Automatik „{subj}“ {'eingeschaltet' if v == 'on' else 'abgelehnt'}."
        if kind == "rename_type":
            name = (v or {}).get("name") if isinstance(v, dict) else v
            return f"Die Art „{subj}“ heißt jetzt „{name}“."
        if kind == "rename_attr":
            t, a = _attr(rt, subj)
            return f"Das Feld {('bei ' + t['plural'] + ' ') if t else ''}heißt jetzt „{v}“."
        if kind == "hide_attr":
            t, a = _attr(rt, subj)
            return f"Das Feld „{(a or {}).get('name') or subj}“{(' bei ' + t['plural']) if t else ''} wird {'ausgeblendet' if v else 'wieder angezeigt'}."
        if kind == "list_cols":
            return f"Die Spalten der Liste „{_plural(rt, subj)}“ wurden angepasst."
        if kind == "hidden_record":
            tid = subj.split("|")[0]
            return f"Ein Eintrag aus den Quellen wird bei {_plural(rt, tid)} nicht übernommen. Grund: {v}"
        if kind == "mail_done":
            rid = int(subj)
            return f"Die E-Mail „{rt.title(rid) if rid in rt.by_id else subj}“ ist erledigt."
    except (ValueError, TypeError, KeyError):
        pass
    return f"{kind}: {subj} → {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}"


def decisions(rt) -> list[dict]:
    rows = rt.store.q("SELECT kind, subject, value, actor, ts, note FROM decisions ORDER BY ts")
    return [dict(ts=r["ts"], actor=r["actor"], text=decision_text(rt, dict(r)), note=r["note"]) for r in rows]
