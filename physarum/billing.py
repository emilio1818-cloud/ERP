"""Invoices made here: from the order, as a draft, issued with a number, cancelled with a document.

* A new invoice takes over what history says it takes over: the customer of the order, its
  amount, its lines. VAT comes from the articles' own rates (7 % coffee, 19 % grinder), not
  from a rate learned on the past; the learned rate is only the fallback.
* An invoice made here starts as a draft: it has no number yet and can be changed or
  deleted. Issuing it checks what an invoice needs (§ 14 UStG), gives it the next free number
  – a number is never handed out twice, not even after a deletion – and fixes recipient and
  lines as they were at that moment. From then on it is locked.
* A cancellation is a document of its own: a cancellation invoice with its own number and
  negative amounts that points to the original.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .store import dumps, now_iso
from .text import fold, norm_key, tokens
from .values import as_date, parse_duration

LOCKED_CONCEPTS = {"rechnung"}
TAX_WORDS = {"mwst", "ust", "umsatzsteuer", "mehrwertsteuer", "steuer", "vat", "tax", "steuersatz"}
_NUM = re.compile(r"^(?P<pre>.*?)(?P<num>\d+)$")


class BillingError(Exception):
    pass


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def words(name: str) -> set[str]:
    """Header words, with German abbreviations kept whole ("MwSt" is "mwst", not "mw st")."""
    return set(tokens(name, camel=False)) | set(tokens(name))


def is_invoice(spec: dict | None) -> bool:
    return bool(spec) and spec.get("concept") in LOCKED_CONCEPTS and bool(spec.get("key"))


def is_draft(rec: dict) -> bool:
    return bool((rec.get("meta") or {}).get("draft"))


def attr_by(spec: dict, *, kind=None, words=(), role=None):
    for a in spec["attrs"]:
        if a.get("hidden") or a.get("virtual"):
            continue
        if kind and a["kind"] != kind:
            continue
        if role and a.get("role") != role:
            continue
        if words and not words(a["name"]) & set(words):
            continue
        return a
    return None


def money_fields(spec: dict) -> dict:
    """net / tax / gross attributes of a document type."""
    ms = [a for a in spec["attrs"] if a["kind"] == "money" and not a.get("hidden")]
    net = next((a for a in ms if words(a["name"]) & {"netto", "net"} and not a.get("virtual")), None)
    tax = next((a for a in ms if words(a["name"]) & TAX_WORDS), None)
    gross = next((a for a in ms if words(a["name"]) & {"brutto", "gross", "gesamt", "total", "betrag"}
                  and not a.get("virtual")), None)
    if net is None:
        net = next((a for a in ms if a is not tax and a is not gross), None)
    return dict(net=net, tax=tax, gross=gross)


def party_attr(rt, spec: dict):
    refs = [a for a in spec["attrs"] if a["kind"] == "ref" and a["id"] != spec.get("key")]
    return next((a for a in refs if (rt.spec(a.get("ref")) or {}).get("kind") == "master"), None)


def source_attr(rt, spec: dict):
    """The reference to the document an invoice is made from (the order)."""
    return next((a for a in spec["attrs"] if a["kind"] == "ref" and (rt.spec(a.get("ref")) or {}).get("kind") == "transaction"),
                None)


# --- lines ---------------------------------------------------------------------------------------------

def line_type(rt, spec_id: str) -> dict | None:
    for r in rt.model["relations"]:
        if r["dst"] == spec_id and r["kind"] in ("parent", "ref"):
            s = rt.spec(r["src"])
            if s and s["kind"] == "line":
                return dict(spec=s, attr=r["attr"])
    return None


def positions(rt, rec: dict) -> list[dict]:
    """The lines of a document: its own, or those of the order it was made from. Each line:
    text, quantity, unit, unit price, total, VAT rate (if the article knows it)."""
    snap = (rec.get("meta") or {}).get("positions")
    if snap:
        return snap
    spec = rt.spec(rec["type"])
    lt = line_type(rt, spec["id"])
    owner = rec
    if not lt or not any(x["data"].get(lt["attr"]) == rec["id"] for x in rt.records.get(lt["spec"]["id"], [])):
        src = source_attr(rt, spec)
        sid = rec["data"].get(src["id"]) if src else None
        if isinstance(sid, int) and sid in rt.by_id:
            owner = rt.by_id[sid]
            lt = line_type(rt, owner["type"])
    if not lt:
        return []
    ls = lt["spec"]
    qty = attr_by(ls, kind="number", role="quantity") or attr_by(ls, kind="number")
    price = next((a for a in ls["attrs"] if a["kind"] == "money" and words(a["name"]) & {"einzelpreis", "preis",
                                                                                                 "price", "ep"}), None)
    total = next((a for a in ls["attrs"] if a["kind"] == "money" and words(a["name"]) & {"gesamt", "summe", "total",
                                                                                                 "betrag"}), None)
    unit = next((a for a in ls["attrs"] if fold(a["name"]) in ("einheit", "unit", "me", "gebinde")), None)
    item = next((a for a in ls["attrs"] if a["kind"] == "ref" and a["id"] != lt["attr"]), None)
    text = next((a for a in ls["attrs"] if a["kind"] == "text" and a.get("role") in ("name", None, "notes")
                 and not a.get("hidden")), None)
    out = []
    for ln in rt.records.get(ls["id"], []):
        if ln["data"].get(lt["attr"]) != owner["id"]:
            continue
        d = ln["data"]
        q = _num(d.get(qty["id"])) if qty else None
        p = _num(d.get(price["id"])) if price else None
        t = _num(d.get(total["id"])) if total else None
        if t is None and q is not None and p is not None:
            t = round(q * p, 2)
        art = rt.by_id.get(d.get(item["id"])) if item else None
        rate = None
        name = None
        sku = None
        if art:
            aspec = rt.spec(art["type"])
            ra = next((a for a in aspec["attrs"] if a["kind"] == "percent" and words(a["name"]) & TAX_WORDS), None)
            rate = _num(art["data"].get(ra["id"])) if ra else None
            name = rt.title(art["id"])
            if aspec.get("key") and aspec["key"] != aspec.get("title"):
                sku = art["data"].get(aspec["key"])
        if name is None and text:
            name = d.get(text["id"])
        out.append(dict(text=str(name or "Position"), sku=sku, qty=q, unit=d.get(unit["id"]) if unit else None,
                        price=p, total=t, rate=rate))
    return out


def tax_by_lines(lines: list[dict]) -> dict | None:
    """VAT per rate from the lines, when every line knows its rate."""
    if not lines or any(x["rate"] is None or x["total"] is None for x in lines):
        return None
    by_rate: dict[float, float] = {}
    for x in lines:
        by_rate[x["rate"]] = by_rate.get(x["rate"], 0.0) + x["total"]
    groups = [dict(rate=r, net=round(n, 2), tax=round(n * r, 2)) for r, n in sorted(by_rate.items())]
    net = round(sum(g["net"] for g in groups), 2)
    tax = round(sum(g["tax"] for g in groups), 2)
    return dict(net=net, tax=tax, gross=round(net + tax, 2), groups=groups)


# --- a new invoice from what it refers to -----------------------------------------------------------------

def derive(rt, spec: dict, data: dict) -> tuple[dict, list[str]]:
    """Fill a new record from the record it refers to: learned copies (customer, amount) and, for
    invoices, VAT by the articles' rates. Returns (values, explanations)."""
    out, why = {}, []
    for lp in rt.model.get("lookups", []):
        if lp["type"] != spec["id"]:
            continue
        src = rt.by_id.get(data.get(lp["ref"]))
        if not src or src["type"] != lp["src_type"]:
            continue
        v = src["data"].get(lp["src_attr"])
        if lp.get("kind") == "copy":
            if v is not None:
                out[lp["attr"]] = v
        elif _num(v) is not None:
            out[lp["attr"]] = round(_num(v) * lp.get("k", 1), 2)
    if is_invoice(spec):
        mf = money_fields(spec)
        rec = dict(id=-1, type=spec["id"], data=dict(data, **out), meta={})
        t = tax_by_lines(positions(rt, rec))
        if t and mf["net"] and mf["tax"]:
            out[mf["net"]["id"]] = t["net"]
            out[mf["tax"]["id"]] = t["tax"]
            if mf["gross"]:
                out[mf["gross"]["id"]] = t["gross"]
            why.append("MwSt nach den Steuersätzen der Artikel: " +
                       ", ".join(f"{_pct(g['rate'])} auf {_eur(g['net'])}" for g in t["groups"]))
    return out, why


def _pct(r: float) -> str:
    x = r * 100 if r <= 1 else r
    return (f"{x:.0f}" if abs(x - round(x)) < 0.01 else f"{x:.1f}".replace(".", ",")) + " %"


def _eur(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


# --- numbers ------------------------------------------------------------------------------------------------

def next_free_number(rt, spec: dict, c=None, today: date | None = None) -> str | None:
    """The next number of the learned scheme that was never given out – neither in the data,
    nor by this program (cancelled and deleted numbers stay used)."""
    from .ops import next_number

    cand = next_number(rt, spec, today)
    if not cand:
        return None
    cc = c or rt.store.conn()
    used = {norm_key(r["number"]) for r in cc.execute("SELECT number FROM numbers WHERE type=?", (spec["id"],)).fetchall()}
    used |= {norm_key(r["data"].get(spec["key"])) for r in rt.records.get(spec["id"], []) if r["data"].get(spec["key"])}
    guard = 0
    while norm_key(cand) in used and guard < 100000:
        cand = _increment(cand)
        guard += 1
    return cand


def _increment(num: str) -> str:
    m = _NUM.match(num)
    if not m:
        return num + "-1"
    n = m.group("num")
    return m.group("pre") + str(int(n) + 1).zfill(len(n))


def reserve(c, spec_id: str, number: str, rid: int):
    c.execute("INSERT OR IGNORE INTO numbers(type,number,record_id,ts) VALUES(?,?,?,?)", (spec_id, number, rid, now_iso()))


# --- issuing ------------------------------------------------------------------------------------------------

def missing_for_issue(rt, spec: dict, rec: dict) -> list[str]:
    d = rec["data"]
    out = []
    party = party_attr(rt, spec)
    if party and not isinstance(d.get(party["id"]), int):
        out.append(party["name"])
    mf = money_fields(spec)
    amount = _num(d.get(mf["gross"]["id"])) if mf["gross"] else None
    if amount is None and mf["net"]:
        amount = _num(d.get(mf["net"]["id"]))
    if not amount or amount <= 0:
        out.append((mf["net"] or mf["gross"] or {"name": "Betrag"})["name"])
    return out


def issue_warnings(rt, spec: dict, rec: dict) -> list[str]:
    """What the invoice may lack without blocking it: above 250 € gross (§ 33 UStDV) the
    customer's full address belongs on it."""
    party = party_attr(rt, spec)
    mf = money_fields(spec)
    gross = _num(rec["data"].get(mf["gross"]["id"])) if mf["gross"] else None
    if not party or not isinstance(rec["data"].get(party["id"]), int) or gross is None or gross <= 250:
        return []
    b = recipient(rt, rec["data"][party["id"]])
    lack = [n for k, n in (("street", "Straße"), ("zip", "PLZ"), ("city", "Ort")) if not b.get(k)]
    if not lack:
        return []
    return [f"Bei {rt.title(rec['data'][party['id']])} fehlt noch {', '.join(lack)}. Über 250 € gehört die vollständige "
            f"Anschrift des Kunden auf die Rechnung (§ 14 UStG) – bitte beim Kunden ergänzen."]


def recipient(rt, party_rid: int | None) -> dict:
    cust = rt.by_id.get(party_rid) if isinstance(party_rid, int) else None
    if not cust:
        return {}
    cs = rt.spec(cust["type"])
    d = cust["data"]

    def role(r):
        a = next((x for x in cs["attrs"] if x.get("role") == r and d.get(x["id"])), None)
        return str(d[a["id"]]) if a else None
    return dict(name=rt.title(cust["id"]), person=role("person"), street=role("street"), zip=role("zip"),
                city=role("city"), email=role("email"), number=d.get(cs["key"]) if cs.get("key") else None,
                vat_id=next((str(d[a["id"]]) for a in cs["attrs"] if words(a["name"]) & {"ustid", "ust", "vat"}
                             and a["kind"] in ("id", "text") and d.get(a["id"])), None))


def issue(rt, rid: int, actor: str, today: date | None = None) -> str:
    """Turn a draft into an issued, locked invoice. Returns its number."""
    from .ops import apply_formulas, _write_refs_and_search

    rt.ensure()
    today = today or date.today()
    rec = rt.store.record(rid)
    spec = rt.spec(rec["type"]) if rec else None
    if not rec or rec.get("deleted") or not spec or not is_invoice(spec) or not is_draft(rec):
        raise BillingError("Nur ein Entwurf kann ausgestellt werden.")
    miss = missing_for_issue(rt, spec, rec)
    if miss:
        raise BillingError("Zum Ausstellen fehlt noch: " + ", ".join(miss))
    data = dict(rec["data"])
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    if proc and not data.get(proc["start"]["attr"]):
        data[proc["start"]["attr"]] = today.isoformat()
    given = set(data)
    for f in spec.get("formulas") or []:
        if f["op"] in ("date_add", "date_add_ref", "date_default"):
            given.discard(f["attr"])  # due date from the issue date
            data.pop(f["attr"], None)
    apply_formulas(rt, spec, data, given)
    if proc and proc.get("deadlines") and not any(data.get(dl["attr"]) for dl in proc["deadlines"]):
        due = next((dl["attr"] for dl in proc["deadlines"]), None)
        if due:
            days = _usual_term(rt, spec, proc) or 14
            data[due] = (as_date(data.get(proc["start"]["attr"])) + timedelta(days=days)).isoformat()
    meta = dict(rec["meta"] or {})
    party = party_attr(rt, spec)
    rec_view = dict(rec, data=data, meta={})
    meta.update(draft=False, issued=now_iso(), issued_by=actor,
                recipient=recipient(rt, data.get(party["id"]) if party else None),
                positions=positions(rt, rec_view), company=company(rt.store))
    with rt.store.tx() as c:
        number = next_free_number(rt, spec, c, today)
        if not number:
            number = f"{today.year}-{rid}"
        reserve(c, spec["id"], number, rid)
        data[spec["key"]] = number
        meta.setdefault("w", {})[spec["key"]] = ["user", now_iso()]
        c.execute("UPDATE records SET data=?, meta=?, updated_at=? WHERE id=?", (dumps(data), dumps(meta), now_iso(), rid))
        c.execute("INSERT INTO idents(type,ident,record_id) VALUES(?,?,?) ON CONFLICT(type,ident) DO NOTHING",
                  (spec["id"], "k:" + norm_key(number), rid))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,new,note) VALUES(?,?,?,?,?,?,?)",
                  (rid, now_iso(), actor, "issue", spec["key"], dumps(number),
                   "ausgestellt und festgeschrieben (Empfänger und Positionen wie zu diesem Zeitpunkt)"))
        _write_refs_and_search(rt, c, rid, spec, data)
        rt.bump(c)
    return number


def usual_due(rt, spec: dict, data: dict) -> dict | None:
    """A draft without a due date (the customer has no payment term): the firm's usual term."""
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    if not proc or not proc.get("deadlines"):
        return None
    due = proc["deadlines"][0]["attr"]
    start = as_date(data.get(proc["start"]["attr"]))
    if data.get(due) or not start:
        return None
    days = _usual_term(rt, spec, proc)
    if not days:
        return None
    a = rt.attr(spec["id"], due)
    return dict(attr=due, value=(start + timedelta(days=days)).isoformat(), hint=f"üblich {days} Tage nach Rechnungsdatum",
                why=f"{a['name'] if a else 'Fällig'}: üblich {days} Tage nach Rechnungsdatum (so bei den meisten bisherigen Rechnungen)")


def _usual_term(rt, spec, proc) -> int | None:
    """The firm's usual payment term: the most common distance between invoice and due date."""
    from collections import Counter
    due = next((dl["attr"] for dl in proc.get("deadlines", [])), None)
    if not due:
        return None
    c = Counter()
    for r in rt.records.get(spec["id"], []):
        a, b = as_date(r["data"].get(proc["start"]["attr"])), as_date(r["data"].get(due))
        if a and b and 0 <= (b - a).days <= 120:
            c[(b - a).days] += 1
    return c.most_common(1)[0][0] if c else None


# --- cancelling -----------------------------------------------------------------------------------------

def cancel(rt, rid: int, reason: str, actor: str, today: date | None = None) -> int | None:
    """Cancel an issued invoice with a cancellation invoice. Returns the new record id."""
    from .ops import _write_refs_and_search

    rt.ensure()
    today = today or date.today()
    reason = (reason or "").strip()
    if not reason:
        raise BillingError("Bitte einen Grund für das Storno angeben")
    rec = rt.store.record(rid)
    if not rec or rec.get("deleted"):
        raise BillingError("Datensatz nicht gefunden")
    spec = rt.spec(rec["type"])
    meta = dict(rec["meta"] or {})
    if meta.get("storno_by") or meta.get("storno_of"):
        raise BillingError("Diese Rechnung ist bereits storniert bzw. selbst ein Storno.")
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    st = (proc or {}).get("status")
    neg_vals = (st or {}).get("negative") or []
    if st and str(rec["data"].get(st["attr"])) in neg_vals:
        raise BillingError("Diese Rechnung ist bereits storniert.")
    neg = neg_vals[0] if neg_vals else "storniert"
    data = dict(rec["data"])
    new = {}
    for a in spec["attrs"]:
        v = data.get(a["id"])
        if v is None or a.get("virtual"):
            continue
        if a["kind"] == "money" and _num(v) is not None:
            new[a["id"]] = -round(_num(v), 2)
        elif a["kind"] in ("ref",):
            new[a["id"]] = v
    if proc:
        new[proc["start"]["attr"]] = today.isoformat()
    if st:
        new[st["attr"]] = neg
        data[st["attr"]] = neg
    ts = now_iso()
    with rt.store.tx() as c:
        number = next_free_number(rt, spec, c, today) or f"ST-{rid}"
        new[spec["key"]] = number
        nmeta = dict(storno_of=rid, issued=ts, issued_by=actor, recipient=meta.get("recipient"),
                     positions=[dict(x, qty=-(x["qty"] or 0) if x.get("qty") is not None else None,
                                     total=-(x["total"] or 0) if x.get("total") is not None else None)
                                for x in (meta.get("positions") or positions(rt, rec))],
                     company=meta.get("company") or company(rt.store), w={k: ["user", ts] for k in new})
        cur = c.execute("INSERT INTO records(type,data,meta,origin,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (spec["id"], dumps(new), dumps(nmeta), "user", ts, ts))
        nid = cur.lastrowid
        reserve(c, spec["id"], number, nid)
        c.executemany("INSERT OR IGNORE INTO idents(type,ident,record_id) VALUES(?,?,?)",
                      [(spec["id"], f"u:{nid}", nid), (spec["id"], "k:" + norm_key(number), nid)])
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                  (nid, ts, actor, "create", f"Stornorechnung zu {data.get(spec['key'])}: {reason}"))
        meta.update(storno_by=nid, storno=dict(ts=ts, actor=actor, reason=reason))
        c.execute("UPDATE records SET data=?, meta=?, updated_at=? WHERE id=?", (dumps(data), dumps(meta), ts, rid))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                  (rid, ts, actor, "storno", st["attr"] if st else None, dumps(rec["data"].get(st["attr"])) if st else None,
                   dumps(neg) if st else None, f"storniert durch {number}: {reason}"))
        c.execute("INSERT INTO notes(record_id,ts,actor,text) VALUES(?,?,?,?)", (rid, ts, actor, f"Storniert ({number}): {reason}"))
        _write_refs_and_search(rt, c, nid, spec, new)
        _write_refs_and_search(rt, c, rid, spec, data)
        rt.bump(c)
    return nid


# --- the firm itself ------------------------------------------------------------------------------------------

COMPANY_FIELDS = [
    ("name", "Firmenname"), ("street", "Straße und Hausnummer"), ("zip", "PLZ"), ("city", "Ort"),
    ("vat_id", "USt-IdNr."), ("tax_no", "Steuernummer"), ("iban", "IBAN"), ("bic", "BIC"), ("bank", "Bank"),
    ("email", "E-Mail"), ("phone", "Telefon"), ("register", "Handelsregister"), ("manager", "Geschäftsführung"),
]


def company(store) -> dict:
    c = store.kv_get("company_profile") or {}
    if isinstance(c, str):
        c = dict(name=c)
    return c


def guess_company(rt) -> dict:
    """What the data already says about the firm itself: the name in its list titles, its own
    account in the bank statement."""
    from collections import Counter

    from .store import loads
    out = {}
    names = Counter()
    for t in rt.store.q("SELECT meta FROM raw_tables"):
        title = (loads(t["meta"]) or {}).get("title") or ""
        for sep in (" – ", " - ", ": ", " · "):
            for part in title.split(sep):
                part = part.strip()
                if 3 <= len(part) <= 60 and re.search(r"\b(GmbH|AG|KG|UG|e\.K\.|GbR|OHG|mbH)\b", part):
                    names[part] += 1
    if names:
        out["name"] = names.most_common(1)[0][0]
    from .reconcile import bank_specs
    for b in bank_specs(rt.model):
        own = next((a for a in b["spec"]["attrs"] if a["kind"] == "iban" and a.get("hidden")), None)
        if own:
            for r in rt.records.get(b["spec"]["id"], [])[:1]:
                if r["data"].get(own["id"]):
                    out["iban"] = r["data"][own["id"]]
    return out


def company_missing(store) -> list[str]:
    c = company(store)
    need = [("name", "Firmenname"), ("street", "Straße"), ("zip", "PLZ"), ("city", "Ort")]
    out = [label for k, label in need if not c.get(k)]
    if not c.get("vat_id") and not c.get("tax_no"):
        out.append("Steuernummer oder USt-IdNr.")
    return out


# --- the printed and the electronic invoice ---------------------------------------------------------------

def document(rt, rec: dict) -> dict:
    """Everything an invoice states (§ 14 UStG): for the print page and the XRechnung."""
    spec = rt.spec(rec["type"])
    meta = rec.get("meta") or {}
    d = rec["data"]
    mf = money_fields(spec)
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    start = as_date(d.get(proc["start"]["attr"])) if proc else None
    due = None
    if proc:
        for dl in proc.get("deadlines", []):
            due = as_date(d.get(dl["attr"])) or due
    party = party_attr(rt, spec)
    buyer = meta.get("recipient") or recipient(rt, d.get(party["id"]) if party else None)
    pos = meta.get("positions") or positions(rt, rec)
    groups = (tax_by_lines(pos) or {}).get("groups")
    net = _num(d.get(mf["net"]["id"])) if mf["net"] else None
    tax = _num(d.get(mf["tax"]["id"])) if mf["tax"] else None
    gross = _num(d.get(mf["gross"]["id"])) if mf["gross"] else None
    if not groups:
        rate = (tax / net) if net and tax is not None else 0.0
        groups = [dict(rate=round(rate, 4), net=net or 0.0, tax=tax or 0.0)]
    if not pos:
        pos = [dict(text=f"Leistungen laut {rt.title(d.get(source_attr(rt, spec)['id']))}" if source_attr(rt, spec)
                    and d.get(source_attr(rt, spec)["id"]) else "Leistung", qty=1, unit=None, price=net, total=net,
                    rate=groups[0]["rate"], sku=None)]
    src = source_attr(rt, spec)
    order = rt.by_id.get(d.get(src["id"])) if src else None
    delivery = None
    if order:
        oproc = next((p for p in rt.model.get("processes", []) if p["type"] == order["type"]), None)
        for st in (oproc or {}).get("steps", []):
            if fold(st["label"]) in ("geliefert", "versendet", "erledigt"):
                for s2 in [st] + st.get("also", []):
                    if s2["source"] == "own":
                        delivery = as_date(order["data"].get(s2["attr"])) or delivery
    corrects = None
    if meta.get("storno_of") and meta["storno_of"] in rt.by_id:
        corrects = rt.by_id[meta["storno_of"]]["data"].get(spec["key"])
    terms = None
    if due and start:
        terms = f"Zahlbar ohne Abzug bis {due.strftime('%d.%m.%Y')} ({(due - start).days} Tage)."
    return dict(number=d.get(spec["key"]), date=(start or date.today()).isoformat(), due=due.isoformat() if due else None,
                delivery=delivery.isoformat() if delivery else None, seller=meta.get("company") or company(rt.store),
                buyer=buyer, positions=pos, groups=groups, net=net, tax=tax, gross=gross,
                order=rt.title(order["id"]) if order else None, corrects=corrects, terms=terms,
                draft=is_draft(rec), cancelled_by=rt.by_id.get(meta.get("storno_by"), {}).get("data", {}).get(spec["key"])
                if meta.get("storno_by") else None)
