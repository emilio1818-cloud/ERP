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

import hashlib
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import lexicon
from .store import dumps, loads, now_iso
from .text import fold, norm_key, tokens
from .values import as_date, as_number, fmt_eur, parse_duration

LOCKED_CONCEPTS = {"rechnung"}
TAX_WORDS = {"mwst", "ust", "umsatzsteuer", "mehrwertsteuer", "steuer", "vat", "tax", "steuersatz"}
_NUM = re.compile(r"^(?P<pre>.*?)(?P<num>\d+)$")


class BillingError(Exception):
    pass


def _d(v) -> Decimal | None:
    """A number as Decimal: German or plain notation, never binary floating point."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip().replace("€", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def cents(x: Decimal) -> Decimal:
    """Commercial rounding to the cent: 2,755 € -> 2,76 €."""
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rate_of(v) -> Decimal | None:
    """7, 0.07, '7 %', '7,0' -> 0.07"""
    x = _d(str(v).replace("%", "")) if v is not None else None
    if x is None:
        return None
    return x / 100 if x > 1 else x


def words(name: str) -> set[str]:
    """Header words, with German abbreviations kept whole ("MwSt" is "mwst", not "mw st")."""
    return set(tokens(name, camel=False)) | set(tokens(name))


_header_words = words


def is_invoice(spec: dict | None) -> bool:
    """An invoice this firm writes (drafts, numbers, print, e-invoice, storno) – not one a
    supplier sent: those keep the supplier's number and are corrected by the supplier."""
    return bool(spec) and spec.get("concept") in LOCKED_CONCEPTS and bool(spec.get("key")) and not spec.get("incoming")


def is_own_invoice(rt, spec: dict) -> bool:
    return is_invoice(spec)


def is_draft(rec: dict) -> bool:
    return bool((rec.get("meta") or {}).get("draft"))


def attr_by(spec: dict, *, kind=None, words=(), role=None):
    wanted = set(words)  # the parameter hides the function words() of this module
    for a in spec["attrs"]:
        if a.get("hidden") or a.get("virtual"):
            continue
        if kind and a["kind"] != kind:
            continue
        if role and a.get("role") != role:
            continue
        if wanted and not _header_words(a["name"]) & wanted:
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
        q = as_number(d.get(qty["id"])) if qty else None
        p = as_number(d.get(price["id"])) if price else None
        t = as_number(d.get(total["id"])) if total else None
        if t is None and q is not None and p is not None:
            t = round(q * p, 2)
        art = rt.by_id.get(d.get(item["id"])) if item else None
        rate = None
        name = None
        sku = None
        if art:
            aspec = rt.spec(art["type"])
            ra = next((a for a in aspec["attrs"] if a["kind"] == "percent" and words(a["name"]) & TAX_WORDS), None)
            rate = as_number(art["data"].get(ra["id"])) if ra else None
            name = rt.title(art["id"])
            if aspec.get("key") and aspec["key"] != aspec.get("title"):
                sku = art["data"].get(aspec["key"])
        if name is None and text:
            name = d.get(text["id"])
        out.append(dict(text=str(name or "Position"), sku=sku, qty=q, unit=d.get(unit["id"]) if unit else None,
                        price=p, total=t, rate=rate))
    return out


def tax_by_lines(lines: list[dict]) -> dict | None:
    """VAT per rate from the lines, when every line knows its rate: the tax of each rate on the
    sum of its lines, rounded commercially (§ 14 Abs. 4 Nr. 8 UStG)."""
    if not lines or any(x.get("rate") is None or x.get("total") is None for x in lines):
        return None
    by_rate: dict[Decimal, Decimal] = {}
    for x in lines:
        r = rate_of(x["rate"])
        by_rate[r] = by_rate.get(r, Decimal(0)) + cents(_d(x["total"]))
    groups = []
    for r, n in sorted(by_rate.items()):
        groups.append(dict(rate=float(r), net=float(cents(n)), tax=float(cents(n * r))))
    net = sum((cents(_d(g["net"])) for g in groups), Decimal(0))
    tax = sum((cents(_d(g["tax"])) for g in groups), Decimal(0))
    return dict(net=float(net), tax=float(tax), gross=float(net + tax), groups=groups)


def clean_positions(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Lines as typed in a draft: text, quantity, unit, unit price, VAT rate. The line total is
    always quantity × price, rounded to the cent – a discount is a line of its own with a negative price."""
    out, errors = [], []
    for i, r in enumerate(rows, start=1):
        text = str(r.get("text") or "").strip()
        q, p, rt_ = _d(r.get("qty")), _d(r.get("price")), rate_of(r.get("rate"))
        if not text and q is None and p is None:
            continue  # an empty row
        if not text:
            errors.append(f"Position {i}: Bezeichnung fehlt")
        if q is None:
            errors.append(f"Position {i}: Menge fehlt")
        if p is None:
            errors.append(f"Position {i}: Einzelpreis fehlt")
        if rt_ is None or rt_ < 0 or rt_ > Decimal("0.3"):
            errors.append(f"Position {i}: Steuersatz fehlt oder ist unklar")
        if errors and errors[-1].startswith(f"Position {i}"):
            continue
        total = cents(q * p)
        out.append(dict(text=text[:300], sku=(str(r.get("sku")).strip() or None) if r.get("sku") else None,
                        qty=float(q), unit=(str(r.get("unit")).strip() or None) if r.get("unit") else None,
                        price=float(p), rate=float(rt_), total=float(total)))
    return out, errors



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
        elif as_number(v) is not None:
            out[lp["attr"]] = round(as_number(v) * lp.get("k", 1), 2)
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
                       ", ".join(f"{_pct(g['rate'])} auf {fmt_eur(g['net'])}" for g in t["groups"]))
    return out, why


def _pct(r: float) -> str:
    x = r * 100 if r <= 1 else r
    return (f"{x:.0f}" if abs(x - round(x)) < 0.01 else f"{x:.1f}".replace(".", ",")) + " %"


# --- numbers ------------------------------------------------------------------------------------------------

def next_free_number(rt, spec: dict, c=None, today: date | None = None) -> str:
    """The next number of the learned scheme – RE-2026-0001 … where none is learned – that was never given
    out: neither in the data, nor by this program (cancelled and deleted numbers stay used)."""
    from .ops import next_number

    today = today or date.today()
    cc = c or rt.store.conn()
    given = [r["number"] for r in cc.execute("SELECT number FROM numbers WHERE type=?", (spec["id"],)).fetchall()]
    given += [str(r["data"][spec["key"]]) for r in rt.records.get(spec["id"], []) if r["data"].get(spec["key"])]
    used = {norm_key(x) for x in given}
    cand = next_number(rt, spec, today)
    if not cand:
        pre = f"RE-{today.year}-"
        n = max((int(x[len(pre):]) for x in given if x.startswith(pre) and x[len(pre):].isdigit()), default=0)
        cand = f"{pre}{n + 1:04d}"
    guard = 0
    while norm_key(cand) in used and guard < 100000:
        cand = _increment(cand)
        guard += 1
    return cand


def date_attr(rt, spec: dict) -> str | None:
    """The invoice date: the start of its learned course, else its first date column."""
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    if proc:
        return proc["start"]["attr"]
    return next((a["id"] for a in spec["attrs"] if a["kind"] in ("date", "datetime") and not a.get("hidden")
                 and a.get("role") != "due"), None)


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
    amount = as_number(d.get(mf["gross"]["id"])) if mf["gross"] else None
    if amount is None and mf["net"]:
        amount = as_number(d.get(mf["net"]["id"]))
    if not amount or amount <= 0:
        out.append((mf["net"] or mf["gross"] or {"name": "Betrag"})["name"])
    return out


def recipient(rt, party_rid: int | None) -> dict:
    cust = rt.by_id.get(party_rid) if isinstance(party_rid, int) else None
    if not cust:
        return {}
    cs = rt.spec(cust["type"])
    d = cust["data"]

    def role(r):
        a = next((x for x in cs["attrs"] if x.get("role") == r and d.get(x["id"])), None)
        return str(d[a["id"]]) if a else None
    vat_id = next((str(d[a["id"]]) for a in cs["attrs"] if words(a["name"]) & {"ustid", "ust", "vat"}
                   and a["kind"] in ("id", "text") and d.get(a["id"])), None)
    land = next((str(d[a["id"]]).strip() for a in cs["attrs"] if words(a["name"]) & {"land", "country", "staat"}
                 and d.get(a["id"])), None)
    return dict(name=rt.title(cust["id"]), person=role("person"), street=role("street"), zip=role("zip"),
                city=role("city"), email=role("email"), number=d.get(cs["key"]) if cs.get("key") else None,
                vat_id=vat_id, country=country_code(land, vat_id),
                # BT-10: a public buyer is reached by its Leitweg-ID (E-Rechnungsverordnung)
                leitweg=next((str(d[a["id"]]).strip() for a in cs["attrs"] if "leitweg" in fold(a["name"])
                              and d.get(a["id"])), None),
                salutation=salutation(cs, d, rt.title(cust["id"])))


_COUNTRIES = {"deutschland": "DE", "germany": "DE", "oesterreich": "AT", "austria": "AT", "schweiz": "CH",
              "switzerland": "CH", "niederlande": "NL", "netherlands": "NL", "holland": "NL", "belgien": "BE",
              "frankreich": "FR", "france": "FR", "italien": "IT", "spanien": "ES", "polen": "PL", "daenemark": "DK",
              "luxemburg": "LU", "tschechien": "CZ"}


def country_code(land: str | None, vat_id: str | None) -> str | None:
    """ISO code of a customer's country: as written ("AT", "Österreich"), else the prefix of the VAT id
    ("ATU12345678"; Greece writes EL)."""
    if land:
        t = fold(land)
        if len(land.strip()) == 2 and land.strip().isalpha():
            return land.strip().upper()
        if t in _COUNTRIES:
            return _COUNTRIES[t]
    v = (vat_id or "").replace(" ", "").upper()
    if len(v) > 4 and v[:2].isalpha():
        return "GR" if v[:2] == "EL" else v[:2]
    return None


_SALUTE = {"herr": "Sehr geehrter Herr", "hr": "Sehr geehrter Herr", "herrn": "Sehr geehrter Herr",
           "frau": "Sehr geehrte Frau", "fr": "Sehr geehrte Frau", "familie": "Sehr geehrte Familie",
           "fam": "Sehr geehrte Familie", "eheleute": "Sehr geehrte Familie"}


def salutation(spec: dict, data: dict, name: str) -> str:
    """"Sehr geehrter Herr Schulze," – only where the customer list says "Herr" (a first name says nothing about
    how someone wants to be addressed); a firm, or nothing said, is "Damen und Herren"."""
    anrede = next((str(data[a["id"]]) for a in spec["attrs"] if words(a["name"]) & {"anrede", "salutation", "titel"}
                   and isinstance(data.get(a["id"]), str)), "")
    lead = _SALUTE.get(fold(anrede).strip(" ."))
    if not lead:
        return "Sehr geehrte Damen und Herren,"
    surname = next((str(data[a["id"]]) for a in spec["attrs"] if words(a["name"]) & {"nachname", "name1", "familienname",
                                                                                   "surname", "lastname"}
                    and isinstance(data.get(a["id"]), str) and data[a["id"]].strip()), None)
    if not surname:
        n = name.split(",")[0] if "," in name else name.split()[-1] if name.split() else name
        surname = n.strip()
    title = " ".join(w for w in name.split() if fold(w).strip(".") in ("dr", "prof"))
    return f"{lead} {title + ' ' if title and title not in surname else ''}{surname.strip()},"


def draft_positions(rt, rec: dict) -> list[dict]:
    """The lines a draft proposes: as edited, else taken from the order."""
    meta = rec.get("meta") or {}
    if meta.get("positions") is not None:
        return meta["positions"]
    return positions(rt, rec)


def apply_totals(spec: dict, data: dict, pos: list[dict]) -> dict | None:
    """Head amounts are the sum of the lines – never typed separately."""
    t = tax_by_lines(pos)
    if not t:
        return None
    mf = money_fields(spec)
    for k in ("net", "tax", "gross"):
        if mf[k]:
            data[mf[k]["id"]] = t[k]
    from .payments import _DEDUCT_WORDS, _PAYABLE_WORDS
    deduct = next((a for a in spec["attrs"] if a["kind"] in ("money", "number") and not a.get("virtual")
                   and set(tokens(a["name"])) & _DEDUCT_WORDS), None)
    for a in spec["attrs"]:
        if a["kind"] == "money" and not a.get("virtual") and set(tokens(a["name"])) & _PAYABLE_WORDS:
            # "Zahlbetrag": what the customer pays – the total less down payments already invoiced
            less = data.get(deduct["id"]) if deduct else None
            less = abs(float(less)) if isinstance(less, (int, float)) and not isinstance(less, bool) else 0.0
            data[a["id"]] = round(t["gross"] - less, 2)
    return t


def set_positions(rt, rid: int, rows: list[dict], actor: str) -> list[dict]:
    """Edit the lines of a draft (discount, shipping, partial delivery are lines of their own)."""
    from .ops import _write_refs_and_search

    rt.ensure()
    rec = rt.store.record(rid)
    spec = rt.spec(rec["type"]) if rec else None
    if not rec or rec.get("deleted") or not is_invoice(spec) or not is_draft(rec):
        raise BillingError("Positionen lassen sich nur in einem Entwurf ändern.")
    pos, errors = clean_positions(rows)
    if errors:
        raise BillingError("; ".join(errors))
    data, meta = dict(rec["data"]), dict(rec["meta"] or {})
    before = {k: data.get(k) for k in data}
    apply_totals(spec, data, pos)
    meta["positions"] = pos
    ts = now_iso()
    with rt.store.tx() as c:
        c.execute("UPDATE records SET data=?, meta=?, updated_at=? WHERE id=?", (dumps(data), dumps(meta), ts, rid))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                  (rid, ts, actor, "edit", f"Positionen geändert ({len(pos)})"))
        for aid in data:
            if before.get(aid) != data.get(aid):
                c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                          (rid, ts, "Physarum", "auto", aid, dumps(before.get(aid)), dumps(data.get(aid)),
                           "Summe der Positionen"))
        _write_refs_and_search(rt, c, rid, spec, data)
        rt.bump(c)
    return pos


def delivery_of(rt, spec: dict, rec: dict):
    """When the service was rendered: as given at issue, else the delivery date of the order."""
    meta = rec.get("meta") or {}
    if meta.get("delivery"):
        return as_date(meta["delivery"])
    src = source_attr(rt, spec)
    order = rt.by_id.get(rec["data"].get(src["id"])) if src else None
    if not order:
        return None
    oproc = next((p for p in rt.model.get("processes", []) if p["type"] == order["type"]), None)
    best = None
    for st in (oproc or {}).get("steps", []):
        if fold(st["label"]) in ("geliefert", "versendet", "erledigt", "ausgeliefert"):
            for s2 in [st] + st.get("also", []):
                if s2["source"] == "own":
                    best = as_date(order["data"].get(s2["attr"])) or best
    return best


def other_invoices(rt, spec: dict, rec: dict) -> list[str]:
    """Issued, valid invoices for the same order (a second invoice is a decision, not an accident)."""
    src = source_attr(rt, spec)
    oid = rec["data"].get(src["id"]) if src else None
    if not isinstance(oid, int):
        return []
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    st = (proc or {}).get("status") or {}
    out = []
    for r in rt.records.get(spec["id"], []):
        m = r.get("meta") or {}
        if r["id"] == rec["id"] or r["data"].get(src["id"]) != oid or m.get("draft") or m.get("storno_of") or \
                m.get("storno_by") or str(r["data"].get(st.get("attr"))) in (st.get("negative") or []):
            continue
        out.append(str(r["data"].get(spec["key"]) or f"#{r['id']}"))
    return out


TAX_NOTES = {
    "kleinunternehmer": ("E", "Kein Ausweis von Umsatzsteuer, da Kleinunternehmer gemäß § 19 UStG."),
    "13b": ("AE", "Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG)."),
    "eu": ("K", "Steuerfreie innergemeinschaftliche Lieferung (§ 4 Nr. 1 Buchst. b, § 6a UStG)."),
    "ausfuhr": ("G", "Steuerfreie Ausfuhrlieferung (§ 4 Nr. 1 Buchst. a, § 6 UStG)."),
    "steuerfrei": ("E", "Steuerfreie Leistung nach § 4 UStG."),
}


def issue_problems(rt, spec: dict, rec: dict, delivery=None, tax_note: str | None = None,
                   extra_ok: bool = False) -> list[str]:
    """Everything that keeps a draft from becoming an invoice (§ 14 Abs. 4 UStG)."""
    out = list(missing_for_issue(rt, spec, rec))
    pos = draft_positions(rt, rec)
    _, errs = clean_positions(pos)
    if not pos:
        out.append("mindestens eine Position (Bezeichnung, Menge, Einzelpreis, Steuersatz)")
    out += errs
    comp = company_missing(rt.store)
    if comp:
        out.append("Ihre Firmendaten: " + ", ".join(comp))
    t = tax_by_lines(pos) if not errs else None
    party = party_attr(rt, spec)
    b = recipient(rt, rec["data"].get(party["id"]) if party else None)
    if t and t["gross"] > 250:
        lack = [n for k, n in (("street", "Straße"), ("zip", "PLZ"), ("city", "Ort")) if not b.get(k)]
        if lack:
            out.append(f"Anschrift des Kunden ({', '.join(lack)}) – über 250 € Pflicht")
    if not (delivery or delivery_of(rt, spec, rec)):
        out.append("Leistungsdatum (wann geliefert oder geleistet wurde)")
    if t and any(abs(g["rate"]) < 1e-9 for g in t["groups"]) and not (tax_note or company(rt.store).get("kleinunternehmer")):
        out.append("Grund für 0 % Umsatzsteuer (z. B. § 13b, innergemeinschaftlich, Ausfuhr)")
    if tax_note in ("13b", "eu") and not b.get("vat_id"):
        out.append("USt-IdNr. des Kunden (für Reverse Charge bzw. innergemeinschaftliche Lieferung)")
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    st = (proc or {}).get("status") or {}
    if st.get("attr") and str(rec["data"].get(st["attr"])) in (st.get("negative") or []):
        out.append("ein Status, der nicht „storniert“ ist")
    others = other_invoices(rt, spec, rec)
    if others and not extra_ok:
        out.append(f"Bestätigung: Zu diesem Auftrag gibt es schon {', '.join(others)}")
    return out


def issue(rt, rid: int, actor: str, today: date | None = None, delivery=None, delivery_end=None,
          tax_note: str | None = None, extra_ok: bool = False, render=None) -> str:
    """Turn a draft into an issued, locked invoice. Returns its number. The invoice date is the
    day of issue; recipient, lines, firm data and delivery date are fixed as they are now, and the
    printed and the electronic invoice are archived unchangeably (§ 14b UStG, GoBD)."""
    from .ops import _write_refs_and_search

    rt.ensure()
    today = today or date.today()
    rec = rt.store.record(rid)
    spec = rt.spec(rec["type"]) if rec else None
    if not rec or rec.get("deleted") or not spec or not is_invoice(spec) or not is_draft(rec):
        raise BillingError("Nur ein Entwurf kann ausgestellt werden.")
    delivery = as_date(delivery) if delivery else None
    delivery_end = as_date(delivery_end) if delivery_end else None
    problems = issue_problems(rt, spec, rec, delivery, tax_note, extra_ok)
    if problems:
        raise BillingError("Zum Ausstellen fehlt noch: " + "; ".join(problems))
    data = dict(rec["data"])
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    da = date_attr(rt, spec)
    if da:
        data[da] = today.isoformat()  # an invoice is dated the day it is issued – stored as printed
    comp = company(rt.store)
    pos, _ = clean_positions(draft_positions(rt, rec))
    if comp.get("kleinunternehmer"):
        pos = [dict(x, rate=0.0) for x in pos]  # § 19 UStG: no VAT on the invoice, whatever the line said
    totals = apply_totals(spec, data, pos)
    if comp.get("kleinunternehmer") and not totals:
        mf = money_fields(spec)
        if mf["tax"]:
            data[mf["tax"]["id"]] = 0.0
        if mf["gross"] and mf["net"] and as_number(data.get(mf["net"]["id"])) is not None:
            data[mf["gross"]["id"]] = as_number(data.get(mf["net"]["id"]))
    due = None
    if proc and proc.get("deadlines"):
        due_attr = proc["deadlines"][0]["attr"]
        days = None
        for f in spec.get("formulas") or []:
            if f["attr"] == due_attr and f["op"] == "date_add_ref":
                target = rt.by_id.get(data.get(f["ref"]))
                days = parse_duration(target["data"].get(f["ref_attr"])) if target else None
            elif f["attr"] == due_attr and f["op"] in ("date_add", "date_default"):
                days = f["days"]
        if days is None:
            days = _usual_term(rt, spec, proc) or 14
        due = today + timedelta(days=int(days))
        data[due_attr] = due.isoformat()
    deliv = delivery or delivery_of(rt, spec, rec)
    note = TAX_NOTES.get("kleinunternehmer" if comp.get("kleinunternehmer") else (tax_note or ""), (None, None))
    party = party_attr(rt, spec)
    meta = dict(rec["meta"] or {})
    ts = now_iso()
    with rt.store.tx() as c:
        row = c.execute("SELECT meta, deleted FROM records WHERE id=?", (rid,)).fetchone()
        if not row or row["deleted"] or not (loads(row["meta"]) or {}).get("draft"):
            raise BillingError("Dieser Entwurf wurde gerade schon ausgestellt.")
        number = next_free_number(rt, spec, c, today)
        reserve(c, spec["id"], number, rid)
        data[spec["key"]] = number
        meta.update(draft=False, issued=ts, issued_by=actor,
                    recipient=recipient(rt, data.get(party["id"]) if party else None),
                    positions=pos, company=comp, delivery=deliv.isoformat() if deliv else None,
                    delivery_end=delivery_end.isoformat() if delivery_end else None,
                    tax_note=note[1], tax_category=note[0], totals=totals,
                    terms=(f"Zahlbar ohne Abzug bis {due.strftime('%d.%m.%Y')}." if due else
                           "Zahlbar sofort nach Erhalt der Rechnung ohne Abzug."))
        meta.setdefault("w", {})[spec["key"]] = ["user", ts]
        c.execute("UPDATE records SET data=?, meta=?, updated_at=? WHERE id=?", (dumps(data), dumps(meta), ts, rid))
        c.execute("INSERT INTO idents(type,ident,record_id) VALUES(?,?,?) ON CONFLICT(type,ident) DO NOTHING",
                  (spec["id"], "k:" + norm_key(number), rid))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,new,note) VALUES(?,?,?,?,?,?,?)",
                  (rid, ts, actor, "issue", spec["key"], dumps(number),
                   "ausgestellt und festgeschrieben (Empfänger, Positionen, Firmendaten und Leistungsdatum wie zu diesem Zeitpunkt)"))
        _archive_documents(rt, c, dict(rec, data=data, meta=meta), number, render)
        _write_refs_and_search(rt, c, rid, spec, data)
        rt.bump(c)
    _order_invoiced(rt, spec, data, number, actor)
    return number


_PARTIAL = ("abschlag", "anzahlung", "teilrechnung", "vorauszahlung")


def _order_invoiced(rt, spec: dict, data: dict, number: str, actor: str):
    """The order a final invoice was written for is invoiced: its status says so, in the firm's own word
    for it ("abgerechnet") – not after a down payment, and only where the order list has such a word."""
    from .ops import OpError, update
    src = source_attr(rt, spec)
    order = rt.by_id.get(data.get(src["id"])) if src else None
    if not order:
        return
    kind = " ".join(str(v) for a in spec["attrs"] if a["kind"] == "text" and (v := data.get(a["id"])))
    if any(w in fold(kind) for w in _PARTIAL):
        return
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == order["type"]), None)
    st = (proc or {}).get("status") or {}
    sattr = next((a for a in rt.spec(order["type"])["attrs"] if a["id"] == st.get("attr")), None)
    word = next((v for v in (sattr or {}).get("enum") or [] if lexicon.status_reaches("berechnet", v)), None)
    cur = order["data"].get(sattr["id"]) if sattr else None
    if not word or cur == word or str(cur) in (st.get("negative") or []):
        return
    try:
        update(rt, order["id"], {sattr["id"]: word}, actor, note=f"Rechnung {number} ausgestellt", kind="auto")
    except OpError:
        pass  # a locked or vanished order keeps its status


def _archive_documents(rt, c, rec: dict, number: str, render=None):
    """The issued invoice as the customer gets it – stored once, with its checksum, never rewritten."""
    doc = document(rt, rec)
    safe = str(number).replace("/", "-")
    if render is not None:
        html = render(doc, rec)
        if html:
            archive_put(c, rec["id"], "html", f"Rechnung_{safe}.html", html.encode("utf-8"))
    from .einvoice import to_xrechnung, xrechnung_problems
    if not xrechnung_problems(doc):
        archive_put(c, rec["id"], "xml", f"XRechnung_{safe}.xml", to_xrechnung(doc).encode("utf-8"))


def archive_put(c, rid: int, kind: str, name: str, content: bytes) -> str:
    """Archive a document once; its checksum also goes into the sealed change log, so a document swapped
    behind Physarum's back no longer matches the seal."""
    h = hashlib.sha256(content).hexdigest()
    ts = now_iso()
    cur = c.execute("INSERT OR IGNORE INTO archive(record_id,kind,name,content,sha256,created_at) VALUES(?,?,?,?,?,?)",
                    (rid, kind, name, content, h, ts))
    if cur.rowcount:
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,new,note) VALUES(?,?,?,?,?,?,?)",
                  (rid, ts, "Physarum", "archive", kind, dumps(h), f"archiviert: {name}"))
    return h


def archive_get(store, rid: int, kind: str):
    return store.q1("SELECT * FROM archive WHERE record_id=? AND kind=?", (rid, kind))


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

def cancel(rt, rid: int, reason: str, actor: str, today: date | None = None, render=None) -> int | None:
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
    if not is_invoice(spec):
        raise BillingError("Nur eigene Rechnungen werden mit einer Stornorechnung storniert – eine Rechnung eines "
                           "Lieferanten korrigiert der Lieferant.")
    meta = dict(rec["meta"] or {})
    if meta.get("storno_by") or meta.get("storno_of"):
        raise BillingError("Diese Rechnung ist bereits storniert bzw. selbst ein Storno.")
    if not meta.get("issued"):
        raise BillingError("Diese Rechnung stammt aus Ihren Dateien, also aus einem anderen Programm. Storniert "
                           "wird sie dort; Physarum übernimmt das Storno beim nächsten Einwerfen.")
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    st = (proc or {}).get("status")
    neg_vals = (st or {}).get("negative") or []
    if st and str(rec["data"].get(st["attr"])) in neg_vals:
        raise BillingError("Diese Rechnung ist bereits storniert.")
    neg = neg_vals[0] if neg_vals else "storniert"
    data = dict(rec["data"])
    orig_doc = document(rt, rec)
    new = {}
    for a in spec["attrs"]:
        v = data.get(a["id"])
        if v is None or a.get("virtual"):
            continue
        if a["kind"] == "ref":
            new[a["id"]] = v
    pos = [dict(x, qty=-(x["qty"] or 0) if x.get("qty") is not None else None,
                total=float(-cents(_d(x["total"]))) if x.get("total") is not None else None)
           for x in (orig_doc.get("positions") or [])]
    totals = apply_totals(spec, new, pos) if pos else None
    if not totals:
        mf = money_fields(spec)
        for k in ("net", "tax", "gross"):
            if mf[k] and as_number(data.get(mf[k]["id"])) is not None:
                new[mf[k]["id"]] = -as_number(data.get(mf[k]["id"]))
    da = date_attr(rt, spec)
    if da:
        new[da] = today.isoformat()
    if st:
        new[st["attr"]] = neg
        data[st["attr"]] = neg
    ts = now_iso()
    with rt.store.tx() as c:
        number = next_free_number(rt, spec, c, today)
        new[spec["key"]] = number
        nmeta = dict(storno_of=rid, issued=ts, issued_by=actor, recipient=orig_doc.get("buyer"), positions=pos,
                     company=orig_doc.get("seller") or company(rt.store), delivery=orig_doc.get("delivery"),
                     delivery_end=orig_doc.get("delivery_end"), tax_note=orig_doc.get("tax_note"),
                     tax_category=orig_doc.get("tax_category"), totals=totals,
                     corrects=dict(number=data.get(spec["key"]), date=orig_doc.get("date")),
                     reason=reason, w={k: ["user", ts] for k in new})
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
        _archive_documents(rt, c, dict(id=nid, type=spec["id"], data=new, meta=nmeta, origin="user"), number, render)
        _write_refs_and_search(rt, c, nid, spec, new)
        _write_refs_and_search(rt, c, rid, spec, data)
        rt.bump(c)
    return nid


# --- the firm itself ------------------------------------------------------------------------------------------

COMPANY_FIELDS = [
    ("name", "Firmenname"), ("street", "Straße und Hausnummer"), ("zip", "PLZ"), ("city", "Ort"),
    ("vat_id", "USt-IdNr."), ("tax_no", "Steuernummer"), ("iban", "IBAN"), ("bic", "BIC"), ("bank", "Bank"),
    ("email", "E-Mail"), ("phone", "Telefon"), ("register", "Handelsregister"), ("manager", "Geschäftsführung"),
    ("country", "Land (ISO-Kürzel, z. B. DE)"),
]


def company(store) -> dict:
    c = store.kv_get("company_profile") or {}
    if isinstance(c, str):
        c = dict(name=c)
    return c


_LEGAL_END = (r"(?:GmbH\s*&\s*Co\.?\s*KG|GmbH|gGmbH|mbH|AG|KGaA|KG|UG(?:\s*\(haftungsbeschränkt\))?|e\.\s?K\.|GbR|OHG|"
              r"e\.\s?V\.|eG|PartG(?:\s*mbB)?)")
_FIRM_RE = re.compile(r"((?:[^\s:·–|;]+\s+){1,6})(" + _LEGAL_END + r")(?![\w])")
_OWN_LABELS = {"kontoinhaber", "inhaber", "auftraggeber", "firma", "unternehmen", "mandant", "absender"}
_IBAN_RE = re.compile(r"IBAN:?\s*([A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){3,7}(?:\s?[0-9A-Z]{1,3})?)")


def _firm_names(text: str) -> list[str]:
    """"Eingangsrechnungen Nordlicht Digital GmbH" -> "Digital GmbH", "Nordlicht Digital GmbH", … (every
    tail that ends in a legal form; the most frequent long one is the name)."""
    out = []
    for m in _FIRM_RE.finditer(text):
        words = m.group(1).split()
        out += [" ".join(words[k:] + [m.group(2)]) for k in range(len(words))]
    return out


def guess_company(rt) -> dict:
    """What the data already says about the firm itself: the name its own lists carry in their titles
    ("Projektübersicht Nordlicht Digital GmbH", "Kontoinhaber: …", a freelancer's "Auftraggeber: …"),
    the IBAN of its own bank statement. Letters from others (PDFs, mails) do not count: a supplier's
    invoice names the supplier."""
    from collections import Counter

    from .store import loads
    from .values import iban_ok
    out = {}
    names, strong = Counter(), Counter()
    seen = set()
    rows = rt.store.q("SELECT t.meta, s.name AS src FROM raw_tables t LEFT JOIN sources s ON s.id = t.source_id")
    for t in rows:
        if str(t["src"] or "").lower().endswith((".pdf", ".eml", ".msg")):
            continue
        title = (loads(t["meta"]) or {}).get("title") or ""
        if not title or title in seen:
            continue
        seen.add(title)
        for part in re.split(r"\s+[–·|-]\s+|\s*;\s*", title):
            label, colon, rest = part.partition(":")
            own = bool(colon) and fold(label).strip() in _OWN_LABELS
            for name in set(_firm_names(rest if colon and len(label) <= 30 else part)):
                names[name] += 1
                if own:
                    strong[name] += 1
            if not out.get("iban") and (own or "konto" in fold(title)):
                m = _IBAN_RE.search(part)
                if m and iban_ok(m.group(1).replace(" ", "")):
                    out["iban"] = m.group(1).replace(" ", "")
    pool = strong or names
    if pool:
        top = max(pool.values())
        out["name"] = max((n for n, c in pool.items() if c == top), key=len)
    if not out.get("iban"):
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
    """Everything an invoice states (§ 14 UStG): for the print page and the XRechnung. An issued
    invoice speaks only from what was fixed when it was issued; an imported one is a copy of the
    book's figures; only a draft looks at today's data."""
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
    issued_here = bool(meta.get("issued"))
    copy = not issued_here and not is_draft(rec)
    party = party_attr(rt, spec)
    buyer = meta.get("recipient") if issued_here else recipient(rt, d.get(party["id"]) if party else None)
    net = as_number(d.get(mf["net"]["id"])) if mf["net"] else None
    tax = as_number(d.get(mf["tax"]["id"])) if mf["tax"] else None
    gross = as_number(d.get(mf["gross"]["id"])) if mf["gross"] else None
    if copy:
        # the figures of the book, not lines rebuilt from today's articles
        rate = round(tax / net, 4) if net and tax is not None else None
        pos = [dict(text="Leistungen laut Rechnungsbuch", qty=1, unit=None, price=net, total=net, rate=rate, sku=None)]
        groups = [dict(rate=rate or 0.0, net=net or 0.0, tax=tax or 0.0)]
    else:
        pos = meta.get("positions") if meta.get("positions") is not None else positions(rt, rec)
        t = tax_by_lines(pos) or {}
        groups = t.get("groups") or []
        if t:
            net, tax, gross = t["net"], t["tax"], t["gross"]
    src = source_attr(rt, spec)
    order = rt.by_id.get(d.get(src["id"])) if src else None
    delivery = as_date(meta.get("delivery")) if issued_here else delivery_of(rt, spec, rec)
    corrects = (meta.get("corrects") or {}).get("number")
    if not corrects and meta.get("storno_of") and meta["storno_of"] in rt.by_id:
        corrects = rt.by_id[meta["storno_of"]]["data"].get(spec["key"])
    terms = meta.get("terms") if issued_here else (
        f"Zahlbar ohne Abzug bis {due.strftime('%d.%m.%Y')} ({(due - start).days} Tage)." if due and start else None)
    comp = company(rt.store)
    return dict(number=d.get(spec["key"]), date=(start or date.today()).isoformat(), due=due.isoformat() if due else None,
                delivery=delivery.isoformat() if delivery else None, delivery_end=meta.get("delivery_end"),
                seller=meta.get("company") if issued_here else comp, buyer=buyer or {}, positions=pos, groups=groups,
                net=net, tax=tax, gross=gross, order=rt.title(order["id"]) if order else None, corrects=corrects,
                corrects_date=(meta.get("corrects") or {}).get("date"), terms=terms, draft=is_draft(rec), copy=copy,
                tax_note=meta.get("tax_note") if issued_here else (TAX_NOTES["kleinunternehmer"][1] if comp.get("kleinunternehmer") else None),
                tax_category=meta.get("tax_category"), issued=meta.get("issued"),
                cancelled_by=rt.by_id.get(meta.get("storno_by"), {}).get("data", {}).get(spec["key"])
                if meta.get("storno_by") else None)
