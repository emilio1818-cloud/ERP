"""Reminders: one letter per customer with everything that is overdue.

The level rises with every letter that was sent (reminder, first and second dunning letter) and is
kept per invoice. A complaint about an invoice stops dunning it: first clarify, then remind. So does
a transfer without a number that may have paid it: first confirm, then remind.
"""
from __future__ import annotations

from datetime import date

from .store import dumps, loads, now_iso
from .text import fold

LEVELS = {1: "Zahlungserinnerung", 2: "1. Mahnung", 3: "2. Mahnung"}
_COMPLAINT = ("reklamation", "reklamier", "beschwerde", "mangel", "maengel", "defekt", "falsch geliefert",
              "fehlt", "nicht erhalten", "storno", "gutschrift")


def level_of(rec: dict) -> int:
    """How many letters were sent for this invoice already."""
    return len((rec.get("meta") or {}).get("dunning") or [])


def complaint(rt, rid: int) -> dict | None:
    """A mail or document that names this invoice and sounds like a complaint."""
    for frm, attr, kind, how in rt.backrefs.get(rid, []):
        d = rt.by_id.get(frm)
        if not d or d["type"] != "doc":
            continue
        text = fold(" ".join(str(v) for v in d["data"].values() if isinstance(v, str))[:5000])
        if any(w in text for w in _COMPLAINT):
            return dict(rid=frm, title=rt.title(frm), date=d["data"].get("doc_date"))
    return None


def overdue_of(rt, party_rid: int, tid: str, today: date | None = None) -> list[dict]:
    """The customer's overdue, unpaid invoices of one type, oldest first."""
    today = today or date.today()
    spec = rt.spec(tid)
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == tid), None)
    if not spec or not proc or not proc.get("party"):
        return []
    out = []
    maybe = rt.payment_proposals()
    for r in rt.records.get(tid, []):
        if r["data"].get(proc["party"]) != party_rid:
            continue
        e = rt.ledger.get(r["id"])
        if not e or e["state"] not in ("offen", "teilbezahlt") or e["open"] <= 0.005 or e.get("retention"):
            continue  # paid, or what is left is a retention until the warranty ends
        due = e.get("due")  # from the book, or reckoned the way the firm does it (see payments.estimate_due)
        if not due or due >= today:
            continue
        lvl = level_of(r)
        out.append(dict(rid=r["id"], number=r["data"].get(spec.get("key")) or rt.title(r["id"]),
                        date=r["data"].get(proc["start"]["attr"]), due=due.isoformat(), due_how=e.get("due_how"),
                        gross=e["gross"], paid=e["paid"], open=e["open"], days=(today - due).days,
                        level=min(lvl + 1, 3), complaint=complaint(rt, r["id"]), maybe_paid=maybe.get(r["id"])))
    out.sort(key=lambda x: (x["due"], x["number"]))
    return out


def record_sent(rt, party_rid: int, tid: str, actor: str, today: date | None = None) -> int:
    """The letter went out: every invoice in it gets its level, a log entry, and the status 'gemahnt'
    where the firm uses such a status. Invoices under complaint are left out."""
    today = today or date.today()
    items = [x for x in overdue_of(rt, party_rid, tid, today) if not x["complaint"] and not x["maybe_paid"]]
    if not items:
        return 0
    spec = rt.spec(tid)
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == tid), None)
    st = (proc or {}).get("status")
    dun = None
    if st:
        enum = next((a.get("enum") for a in spec["attrs"] if a["id"] == st["attr"]), None) or []
        dun = next((v for v in enum if fold(str(v)) in ("gemahnt", "mahnung", "erinnert", "1. mahnung")), None)
    ts = now_iso()
    with rt.store.tx() as c:
        for x in items:
            row = c.execute("SELECT data, meta FROM records WHERE id=?", (x["rid"],)).fetchone()
            data, meta = loads(row["data"]) or {}, loads(row["meta"]) or {}
            meta.setdefault("dunning", []).append(dict(level=x["level"], date=today.isoformat(), by=actor))
            old = data.get(st["attr"]) if st else None
            if dun and old != dun and str(old) not in (st.get("negative") or []):
                data[st["attr"]] = dun  # the status follows the letter (a step of the payment process)
                c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                          (x["rid"], ts, actor, "edit", st["attr"], dumps(old), dumps(dun), f"{LEVELS[x['level']]} versendet"))
            c.execute("UPDATE records SET data=?, meta=?, updated_at=? WHERE id=?", (dumps(data), dumps(meta), ts, x["rid"]))
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                      (x["rid"], ts, actor, "remind", f"{LEVELS[x['level']]} versendet (offen {x['open']:.2f} €)".replace(".", ",")))
        rt.bump(c)
    return len(items)
