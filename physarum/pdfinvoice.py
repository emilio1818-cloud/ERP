"""Invoices that arrive as a PDF without an e-invoice inside.

The text of a German invoice says what an XRechnung says, only in sentences: who sends it (the
letterhead), to whom (the address block), the number and date, the amounts, until when to pay – with
Skonto or without – and to which account. It is read once when the file comes in. Whether it is an
invoice the firm received or one of its own is decided when the firm grows: the firm is the party
that is on every invoice, and its own invoices are in its book already.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .text import fold

_AMT = r"(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})"
_DATE = r"(\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2}))(?!\d)"
_NUMBER = re.compile(r"\b(?:rechnungs?\s?-?\s?(?:nr|nummer|no)\.?|rechnung\s+nr\.?|beleg\s?-?\s?nr\.?|"
                     r"gutschrift\s+nr\.?|invoice\s+(?:no|number)\.?)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/._]{2,30})", re.I)
_INV_DATE = re.compile(r"\b(?:rechnungsdatum|belegdatum|invoice date|datum)\s*:?\s*" + _DATE, re.I)
_HEADING = re.compile(r"^\s*((?:schluss|abschlags|teil|sammel|storno)?rechnung|gutschrift|invoice|rechnungskorrektur)"
                      r"(?:\s*$|\s+(?:nr|nummer|no)\b)", re.I)
_GROSS = re.compile(r"^.*\b(rechnungsbetrag|gesamtbetrag(?:\s+brutto)?|summe\s+brutto|bruttobetrag|endbetrag|"
                    r"gesamt\s+brutto|zu\s+zahlen|zahlbetrag|restforderung)\b[^\n]*?" + _AMT + r"\s*(?:€|eur)?\s*$",
                    re.I | re.M)
_NET = re.compile(r"^.*\b(?:warenwert\s+netto|summe\s+netto|nettobetrag|netto\s*summe|gesamt\s+netto|"
                  r"zwischensumme\s+netto|netto)\b[^\n]*?" + _AMT + r"\s*(?:€|eur)?\s*$", re.I | re.M)
_TAX = re.compile(r"^.*\b(?:mwst|ust|umsatzsteuer|mehrwertsteuer)\b\.?[^\n]*?" + _AMT + r"\s*(?:€|eur)?\s*$",
                  re.I | re.M)
_PAY_BY = re.compile(r"\b(?:zahlbar|fällig|faellig|zahlungsziel)\s+(?:bis\s+(?:zum\s+)?|am\s+)?" + _DATE, re.I)
_SKONTO = re.compile(r"\bbis\s+(?:zum\s+)?" + _DATE + r"[^\n%]{0,40}?(\d{1,2}(?:,\d{1,2})?)\s*%\s*skonto"
                     r"(?:[^\n(]{0,20}\(\s*" + _AMT + r")?", re.I)
_NET_BY = re.compile(r"\bbis\s+(?:zum\s+)?" + _DATE + r"\s+(?:rein\s+)?netto\b", re.I)
_TERM_DAYS = re.compile(r"\b(?:zahlbar|zahlungsziel)\b\D{0,25}?(\d{1,3})\s*tage", re.I)
_VAT = re.compile(r"\b(?:ust|umsatzsteuer)\s?-?\s?id(?:ent)?(?:\.|ifikations)?\s?-?\s?(?:nr|nummer)?\.?\s*:?\s*"
                  r"([A-Z]{2}\s?\d{8,12})", re.I)
_TAX_NO = re.compile(r"\bsteuer\s?-?\s?(?:nr|nummer)\.?\s*:?\s*(\d{2,3}/\d{3,4}/\d{4,5}|\d{10,13})", re.I)
_IBAN = re.compile(r"\bIBAN:?\s*([A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){3,7}(?:\s?[0-9A-Z]{1,3})?)")
_MAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_ORDER = re.compile(r"^\s*(?:kommission|ihre\s+bestellung|bestell\s?-?\s?nr\.?|ihr\s+auftrag|auftrag|projekt|"
                    r"bauvorhaben)\s*:\s*([^\n]{1,80})$", re.I | re.M)
_THEIR_NO = re.compile(r"\b(?:ihre\s+)?kunden\s?-?\s?(?:nr|nummer)\.?\s*:?\s*([A-Z0-9][A-Z0-9\-/]{1,20})", re.I)
_LINE = re.compile(r"^\s*(\d{1,3})\s+(.+?)\s+(\d+(?:,\d+)?)\s+([A-Za-zäöü]{1,6}\.?)\s+" + _AMT + r"\s+" + _AMT + r"\s*$",
                   re.M)
_NEW_BANK = re.compile(r"neue[nr]?\s+bankverbindung|bankverbindung\s+(?:hat\s+sich\s+)?ge(?:ä|ae)ndert|"
                       r"neue[sn]?\s+konto|kontoverbindung\s+(?:hat\s+sich\s+)?ge(?:ä|ae)ndert", re.I)
_CONTACT = re.compile(r"@|·|\btel\b|\bfax\b|www\.|\b\d{5}\b", re.I)


def _amount(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _day(s: str | None) -> date | None:
    if not s:
        return None
    try:
        d, m, y = (int(x) for x in s.split("."))
        return date(y + 2000 if y < 100 else y, m, d)
    except ValueError:
        return None


def _seller(lines: list[str], text: str) -> str | None:
    """The letterhead's first line; where that is no name, the footer's company before its address."""
    from .billing import _LEGAL_END
    first = lines[0] if lines else ""
    if first and not _HEADING.match(first) and not _CONTACT.search(first) and len(first) <= 90:
        return first.strip()
    m = re.search(r"^([^\n·|]{3,80}?\b" + _LEGAL_END + r")\s*[·|]", text, re.M)
    return m.group(1).strip() if m else None


def _buyer(lines: list[str]) -> str | None:
    """The address block: between the letterhead and the heading, the first line that is not the
    sender's address or contact."""
    head = next((i for i, ln in enumerate(lines[:20]) if _HEADING.match(ln)), None)
    if head is None or head < 2:
        return None
    for ln in lines[1:head]:
        if not _CONTACT.search(ln) and not re.match(r"^\s*\d", ln) and len(ln) <= 80:
            return ln.strip()
    return None


def read(text: str | None, sender: str | None = None) -> dict | None:
    """The invoice in the e-invoice shape (see einvoice.parse), or None where the text is no invoice.
    `sender`: the mail address it came from, when it was attached to a mail."""
    if not text or len(text) > 60000:
        return None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    heading = next((m for ln in lines[:25] if (m := _HEADING.match(ln))), None)
    number = _NUMBER.search(text)
    gross = None
    for m in _GROSS.finditer(text):
        if fold(m.group(1)) in ("zu zahlen", "zahlbetrag", "restforderung") or gross is None:
            gross = _amount(m.group(2))
    seller = _seller(lines, text)
    if not (heading and number and gross is not None and seller):
        return None
    when = _INV_DATE.search(text)
    inv_date = _day(when.group(1)) if when else None
    net = next((_amount(m.group(1)) for m in _NET.finditer(text)), None)
    tax = next((_amount(m.group(1)) for m in _TAX.finditer(text)
                if not re.search(r"id\s?-?\s?nr|ident", m.group(0), re.I)), None)
    skonto = _SKONTO.search(text)
    net_by = _NET_BY.search(text)
    pay_by = [_day(m.group(1)) for m in _PAY_BY.finditer(text)]
    due = _day(net_by.group(1)) if net_by else None
    if due is None:
        cands = [d for d in pay_by if d and not (skonto and d == _day(skonto.group(1)))]
        due = cands[-1] if cands else None
    if due is None and inv_date:
        term = _TERM_DAYS.search(text)
        if term:
            due = inv_date + timedelta(days=int(term.group(1)))
    ibans = [re.sub(r"\s+", "", m.group(1)).upper() for m in _IBAN.finditer(text)]
    vat = _VAT.search(text)
    tax_no = _TAX_NO.search(text)
    mails = _MAIL.findall("\n".join(lines[:4]))
    order = _ORDER.search(text)
    their_no = _THEIR_NO.search(text)
    if sender:
        sm = _MAIL.search(sender)
        sender = sm.group(0).lower() if sm else None
    rows = []
    for m in _LINE.finditer(text):
        rows.append(dict(pos=m.group(1), name=m.group(2).strip(), qty=_amount(m.group(3)) if "," in m.group(3)
                         else float(m.group(3)), unit=m.group(4), price=_amount(m.group(5)), total=_amount(m.group(6))))
    credit = fold(heading.group(1)).startswith(("gutschrift", "storno")) or gross < 0
    return dict(number=number.group(1).rstrip(".,;"), date=inv_date, due=due, seller=seller,
                seller_vat=re.sub(r"\s+", "", vat.group(1)).upper() if vat else None,
                seller_tax_no=tax_no.group(1) if tax_no else None, seller_mail=sender or (mails[0] if mails else None),
                letterhead_mail=mails[0] if mails else None, iban=ibans[-1] if ibans else None,
                order=order.group(1).strip() if order else None, net=abs(net) if net is not None else None,
                tax=abs(tax) if tax is not None else None, gross=abs(gross), currency="EUR", lines=rows,
                buyer=_buyer(lines), credit=credit, syntax="PDF",
                skonto_until=_day(skonto.group(1)) if skonto else None,
                skonto_pct=_amount(skonto.group(2)) if skonto and "," in skonto.group(2)
                else (float(skonto.group(2)) if skonto else None),
                skonto_amount=_amount(skonto.group(3)) if skonto and skonto.group(3) else None,
                their_no=their_no.group(1) if their_no else None, new_bank=bool(_NEW_BANK.search(text)),
                kind=fold(heading.group(1)))


def problems(inv: dict) -> list[str]:
    """What does not add up – only what a text can say for sure (no schema, no positions to trust)."""
    from .einvoice import _eur
    out = []
    if None not in (inv.get("net"), inv.get("tax"), inv.get("gross")) and \
            abs(inv["net"] + inv["tax"] - inv["gross"]) > 0.011 and inv.get("kind") not in ("schlussrechnung",):
        out.append(f"Netto {_eur(inv['net'])} plus Umsatzsteuer {_eur(inv['tax'])} sind nicht {_eur(inv['gross'])}")
    if not inv.get("seller_vat") and not inv.get("seller_tax_no"):
        out.append("Weder USt-IdNr. noch Steuernummer des Lieferanten (§ 14 Abs. 4 UStG) – kein Vorsteuerabzug")
    return out


EXTRA_COLS = ["Skonto bis", "Skonto %", "Absender"]


def to_tables(inv: dict, source_name: str):
    """(header table, line table or None): the same columns as a received e-invoice, plus Skonto and
    the address it came from."""
    from .einvoice import to_tables as e_tables
    head, lines, _ = e_tables(inv, source_name)
    head.name = "Eingangsrechnungen (PDF)"
    head.columns = head.columns + EXTRA_COLS
    head.rows = [head.rows[0] + [inv.get("skonto_until"), inv.get("skonto_pct"), inv.get("seller_mail")]]
    head.meta.update({"format": "PDF-Rechnung", "structured": "pdf-invoice-header", "source": source_name,
                      "seller": inv.get("seller"), "buyer": inv.get("buyer"), "number": inv.get("number")})
    if lines is not None:
        lines.name = "Eingangsrechnungspositionen (PDF)"
        lines.meta.update({"format": "PDF-Rechnung", "structured": "pdf-invoice-lines",
                           "parent_table": head.name})
    return head, lines


def own_names(store, raw: list[dict]) -> set[str]:
    """Who the firm is: its profile, the titles of its own lists ("Rechnungsausgangsbuch – Wiesner
    Haustechnik GmbH"), and the party that stands on every invoice – as sender of its own, as recipient
    of the ones it receives."""
    from collections import Counter

    from .billing import _firm_names, company
    out = set()
    name = (company(store) or {}).get("name")
    if name:
        out.add(norm(name))
    titles = Counter()
    for t in raw:
        if (t.get("meta") or {}).get("structured", "").startswith(("pdf-invoice", "einvoice")):
            continue
        if str(t.get("source_name") or "").lower().endswith((".pdf", ".eml", ".msg")):
            continue
        for n in set(_firm_names((t.get("meta") or {}).get("title") or "")):
            titles[norm(n)] += 1
    if titles:
        top = max(titles.values())
        out.add(max((n for n, c in titles.items() if c == top), key=len))
    heads = [t["meta"] for t in raw if (t.get("meta") or {}).get("structured") == "pdf-invoice-header"]
    if len(heads) >= 3:
        on = Counter()
        for m in heads:
            for n in {norm(m.get("seller")), norm(m.get("buyer"))} - {""}:
                on[n] += 1
        top = max(on.values(), default=0)
        best = [n for n, c in on.items() if c == top]
        if len(best) == 1 and top >= 0.8 * len(heads):
            out.add(best[0])  # a tie (all from one supplier, or all to one customer) says nothing about who we are
    return out - {""}


def norm(name: str | None) -> str:
    """A firm's name without its legal form and punctuation: "HTG Haustechnik-Großhandel GmbH & Co. KG"
    -> "htg haustechnik grosshandel"."""
    from .billing import _LEGAL_END
    s = re.sub(_LEGAL_END + r"\s*$", "", str(name or "").strip())
    s = re.sub(r"[^\w]+", " ", fold(s))
    return " ".join(s.split())


def is_own(name: str | None, own: set[str]) -> bool:
    n = norm(name)
    return bool(n) and any(n == o or (len(o) >= 6 and (n.startswith(o) or o.startswith(n))) for o in own)


def received_only(store, raw: list[dict]) -> list[dict]:
    """Drop the firm's own invoices read from PDF: they are in its invoice book, and as received
    invoices they would turn the firm into its own supplier. Kept as documents all the same."""
    if not any((t.get("meta") or {}).get("structured") == "pdf-invoice-header" for t in raw):
        return raw
    own = own_names(store, raw)
    numbers = {str(m.get("number")) for t in raw if (m := t.get("meta") or {}).get("structured") == "pdf-invoice-header"
               and len(str(m.get("number") or "")) >= 5}
    listed = set()  # numbers the firm's own lists carry: its invoice book has them already
    for t in raw:
        if not (t.get("meta") or {}).get("structured", "").startswith("pdf-invoice"):
            for row in t["rows"]:
                listed.update(x for v in row if v is not None and (x := str(v).strip()) in numbers)
    drop = set()
    for t in raw:
        m = t.get("meta") or {}
        if m.get("structured") != "pdf-invoice-header":
            continue
        if is_own(m.get("seller"), own) or (own and m.get("buyer") and not is_own(m.get("buyer"), own)) \
                or str(m.get("number") or "") in listed:
            drop.add(t["id"])
    if not drop:
        return raw
    lines = _lines_of(raw, drop)
    return [t for t in raw if t["id"] not in drop and t["id"] not in lines]


def _lines_of(raw: list[dict], heads: set) -> set:
    """The position tables that came with the dropped headers (same source)."""
    srcs = {t["source_id"] for t in raw if t["id"] in heads}
    return {t["id"] for t in raw if (t.get("meta") or {}).get("structured") == "pdf-invoice-lines"
            and t["source_id"] in srcs}
