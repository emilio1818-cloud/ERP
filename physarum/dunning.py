"""Reminders: one letter per customer with everything that is overdue.

The level rises with every letter that was sent (reminder, first and second dunning letter) and is
kept per invoice; a status the firm's own book gives it ("gemahnt") counts as a letter too. After a
letter the customer has some days to pay before the next. A complaint about an invoice stops dunning
it: first clarify, then remind. So does a transfer without a number that may have paid it: first
confirm, then remind.
"""
from __future__ import annotations

from datetime import date, timedelta

from .store import dumps, loads, now_iso
from .text import fold

LEVELS = {1: "Zahlungserinnerung", 2: "1. Mahnung", 3: "2. Mahnung"}
WAIT = 10  # days after a letter before the next one: the "zehn Tage nach Erhalt" the letters give
_SENT = {"erinnert": 1, "zahlungserinnerung": 1, "gemahnt": 1, "mahnung": 2, "1. mahnung": 2, "2. mahnung": 3}
_COMPLAINT = ("reklamation", "reklamier", "beschwerde", "mangel", "maengel", "defekt", "falsch geliefert",
              "fehlt", "nicht erhalten", "storno", "gutschrift")


def level_of(rec: dict, status=None) -> int:
    """The level the letters for this invoice have reached: logged here, or as the book's status says."""
    log = (rec.get("meta") or {}).get("dunning") or []
    return max([x.get("level") or 1 for x in log] + [_SENT.get(fold(str(status or "")), 0)])


def sent_on(rec: dict) -> date | None:
    """The day the last letter logged here went out."""
    log = (rec.get("meta") or {}).get("dunning") or []
    return date.fromisoformat(log[-1]["date"]) if log else None


def complaint(rt, rid: int) -> dict | None:
    """A mail or document that names this invoice and sounds like a complaint – unless it was ticked off."""
    done = rt.store.decisions("mail_done")
    for frm, attr, kind, how in rt.backrefs.get(rid, []):
        d = rt.by_id.get(frm)
        if not d or d["type"] != "doc" or str(frm) in done:
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
    st = (proc.get("status") or {}).get("attr")
    # what Heute says a letter has to wait for: the customer's mail that it is paid, a complaint, an objection
    asks = {x["rid"]: x["hold"] for g in rt.work(today) if g["kind"] == "overdue" for x in g["items"] if x.get("hold")}
    for r in rt.records.get(tid, []):
        if r["data"].get(proc["party"]) != party_rid:
            continue
        e = rt.ledger.get(r["id"])
        if not e or e["state"] not in ("offen", "teilbezahlt") or e["open"] <= 0.005 or e.get("retention") or e.get("unseen"):
            continue  # paid, or what is left is a retention until the warranty ends
        due = e.get("due")  # from the book, or reckoned the way the firm does it (see payments.estimate_due)
        if not due or due >= today:
            continue
        lvl = level_of(r, r["data"].get(st) if st else None)
        sent = sent_on(r)
        wait = sent + timedelta(days=WAIT) if sent and (today - sent).days < WAIT else None
        ask = rt.by_id.get(asks.get(r["id"]))
        out.append(dict(rid=r["id"], number=r["data"].get(spec.get("key")) or rt.title(r["id"]),
                        date=r["data"].get(proc["start"]["attr"]), due=due.isoformat(), due_how=e.get("due_how"),
                        gross=e["gross"], paid=e["paid"], open=e["open"], days=(today - due).days,
                        level=lvl if wait else min(lvl + 1, 3), sent=sent, wait=wait,
                        complaint=complaint(rt, r["id"]) or (ask and dict(rid=ask["id"], title=rt.title(ask["id"]),
                                                                          date=ask["data"].get("doc_date"))),
                        maybe_paid=maybe.get(r["id"])))
    out.sort(key=lambda x: (x["due"], x["number"]))
    return out


def record_sent(rt, party_rid: int, tid: str, actor: str, today: date | None = None) -> int:
    """The letter went out: every invoice in it gets its level, a log entry, and the status 'gemahnt'
    where the firm uses such a status. Invoices under complaint, and those whose last letter is still
    running, are left out."""
    today = today or date.today()
    items = [x for x in overdue_of(rt, party_rid, tid, today) if not x["complaint"] and not x["maybe_paid"] and not x["wait"]]
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
                prev = meta.setdefault("w", {}).get(st["attr"])  # Physarum's own step: the next export of the
                base = old if prev is None or prev[0] == "import" else (prev[2] if len(prev) > 2 else None)
                meta["w"][st["attr"]] = ["auto", ts, base]  # old program, still saying "offen", does not undo it
                c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                          (x["rid"], ts, actor, "edit", st["attr"], dumps(old), dumps(dun), f"{LEVELS[x['level']]} versendet"))
            c.execute("UPDATE records SET data=?, meta=?, updated_at=? WHERE id=?", (dumps(data), dumps(meta), ts, x["rid"]))
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                      (x["rid"], ts, actor, "remind", f"{LEVELS[x['level']]} versendet (offen {x['open']:.2f} €)".replace(".", ",")))
        rt.bump(c)
    return len(items)
