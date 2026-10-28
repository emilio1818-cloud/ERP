"""Observations: a table (or an entity extracted from a table) seen as a set of records.

An observation is the unit the inference works on. A raw table is one observation;
normalisation may split it into several (e.g. order headers, order lines, customers).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .. import lexicon
from ..text import fold, norm_key, norm_name, tokens
from ..values import Profile, _entropy

ENTITY_ROLES = {"id", "name", "email", "person"}
NEVER_DETERMINANT = {"zip", "city", "street", "country", "phone", "iban", "bic", "url", "notes", "money", "quantity",
                     "percent", "date", "due", "flag", "duration", "number", "status", "category", "unit"}


@dataclass
class Col:
    name: str
    prof: Profile
    values: list  # typed values per record of the observation
    keys: list    # normalised keys per record (for matching), None for empty
    origin: tuple[int, int]  # (raw table id, column index)
    residual: bool = False   # values of rows that could not be assigned during extraction

    @property
    def kind(self) -> str:
        return self.prof.kind

    @property
    def role(self) -> str | None:
        return self.prof.role

    @property
    def filled(self) -> int:
        return sum(1 for k in self.keys if k is not None)

    @property
    def distinct(self) -> int:
        return len({k for k in self.keys if k is not None})

    def bits(self) -> float:
        cnt = Counter(k for k in self.keys if k is not None)
        return max(_entropy(cnt), 0.5)

    def is_constant(self) -> bool:
        ks = [k for k in self.keys if k is not None]
        return len(ks) >= 3 and len(set(ks)) == 1


@dataclass
class Obs:
    oid: str
    table_id: int
    label: str                      # e.g. "Aufträge_Großkunden › 2025"
    file_concept: str | None
    qualifier: str | None
    cols: list[Col]
    prov: list[list[tuple[int, int]]]  # per record: (raw table id, line number)
    n: int
    key: str | None = None          # column name of identifying column
    determinant: str | None = None  # set for extracted observations
    extracted_from: str | None = None
    kind_hint: str | None = None    # header / party / line
    links: list[tuple[str, str]] = field(default_factory=list)  # (col name, target oid) from extraction
    name_hint: tuple[str, str] | None = None  # (singular, plural)
    concept: str | None = None
    source_id: int = 0

    def col(self, name: str) -> Col | None:
        for c in self.cols:
            if c.name == name:
                return c
        return None

    def title_col(self) -> Col | None:
        for role in ("name", "person"):
            for c in self.cols:
                if c.role == role and c.kind == "text" and c.name != self.key:
                    return c
        return None

    def email_col(self) -> Col | None:
        return next((c for c in self.cols if c.kind == "email"), None)


def match_key(prof: Profile, value) -> str | None:
    if value is None:
        return None
    if prof.kind in ("text",) and prof.role in ("name", "person"):
        k = norm_name(value)
        return k or None
    if prof.kind == "email":
        return str(value).strip().casefold()
    if prof.kind in ("date", "datetime"):
        return value.isoformat() if hasattr(value, "isoformat") else norm_key(value)
    if prof.kind in ("number", "money", "percent", "duration"):
        try:
            return repr(round(float(value), 6))
        except (TypeError, ValueError):
            return norm_key(value)
    return norm_key(value) or None


def obs_from_table(table_id: int, label: str, columns: list[str], profiles: list[Profile],
                   lines: list[tuple[int, int]] | list[int], source_id: int = 0) -> Obs:
    """`lines` are (table id, line) pairs; plain ints are taken as lines of `table_id`."""
    cols = []
    for j, (name, prof) in enumerate(zip(columns, profiles)):
        if prof.kind == "empty":
            continue
        keys = [match_key(prof, v) for v in prof.values]
        cols.append(Col(name=name, prof=prof, values=list(prof.values), keys=keys, origin=(table_id, j)))
    lines = [l if isinstance(l, tuple) else (table_id, l) for l in lines]
    n = len(lines)
    stem = label.split(" › ")[0]
    sheet = label.split(" › ")[1] if " › " in label else ""
    concept = lexicon.concept_of(stem) or (lexicon.concept_of(sheet) if sheet else None)
    o = Obs(oid=f"T{table_id}", table_id=table_id, label=label, file_concept=concept,
            qualifier=lexicon.qualifier_of(stem), cols=cols, prov=[[l] for l in lines], n=n, source_id=source_id)
    o.concept = concept
    o.key = pick_key(o)
    return o


def pick_key(o: Obs) -> str | None:
    """The identifying column: an explicit number/code that is unique and (almost) always filled.
    Tables without such a column have no key; their records are identified by e-mail, name
    or content instead."""
    best, best_score = None, 0.0
    for c in o.cols:
        if c.kind != "id" or c.role in NEVER_DETERMINANT:
            continue
        filled = c.filled
        if filled < max(2, 0.9 * o.n):
            continue
        uniq = c.distinct / filled if filled else 0
        if uniq < 0.98:
            continue
        score = uniq * (filled / o.n)
        if c.kind == "id":
            score *= 2.0
            if c.prof.pattern_share >= 0.8:
                score *= 1.2
        elif c.kind == "email":
            score *= 1.1
        elif c.role in ("name",):
            score *= 1.0
        else:
            score *= 0.6
        if c.prof.concept and c.prof.concept == o.concept:
            score *= 1.3
        # first columns are more often keys
        score *= 1.0 - 0.02 * min(10, o.cols.index(c))
        if score > best_score:
            best, best_score = c.name, score
    return best


# --- naming ---------------------------------------------------------------------------------

_EN_HEADERS = {
    "company": "Firma", "company name": "Firma", "contact": "Ansprechpartner", "contact person": "Ansprechpartner",
    "email": "E-Mail", "e mail": "E-Mail", "phone": "Telefon", "telephone": "Telefon", "mobile": "Mobil",
    "city": "Ort", "zip": "PLZ", "zip code": "PLZ", "postal code": "PLZ", "street": "Straße", "address": "Adresse",
    "country": "Land", "notes": "Notizen", "note": "Notiz", "comment": "Kommentar", "segment": "Segment",
    "customer since": "Kunde seit", "created at": "Erstellt am", "created": "Erstellt am", "date": "Datum",
    "name": "Name", "billing name": "Name", "shipping city": "Lieferort", "lineitem name": "Artikel",
    "lineitem sku": "Art.-Nr.", "lineitem quantity": "Menge", "lineitem price": "Preis (brutto)",
    "subtotal": "Zwischensumme", "shipping": "Versandkosten", "total": "Gesamt", "financial status": "Zahlungsstatus",
    "fulfillment status": "Versandstatus", "fulfilled at": "Versendet am", "quantity": "Menge", "qty": "Menge",
    "price": "Preis", "unit price": "Einzelpreis", "amount": "Betrag", "status": "Status", "description": "Beschreibung",
    "title": "Titel", "type": "Typ", "category": "Kategorie", "due date": "Fällig am", "paid at": "Bezahlt am",
    "paid on": "Bezahlt am", "invoice date": "Rechnungsdatum", "invoice number": "Rechnungsnr.",
    "order number": "Bestellnr.", "order date": "Bestelldatum", "customer": "Kunde", "supplier": "Lieferant",
    "product": "Produkt", "sku": "Art.-Nr.", "first name": "Vorname", "last name": "Nachname", "website": "Website",
    "start date": "Beginn", "end date": "Ende", "owner": "Verantwortlich", "stage": "Phase", "tags": "Schlagworte",
    "beguenstigter zahlungspflichtiger": "Zahlungspartner", "auftraggeber empfaenger": "Zahlungspartner",
    "empfaenger auftraggeber": "Zahlungspartner", "name zahlungsbeteiligter": "Zahlungspartner",
    "kontonummer iban": "IBAN", "iban zahlungsbeteiligter": "IBAN", "waehrung": "Währung",
}


def display_header(name: str) -> str:
    key = " ".join(tokens(name))
    return _EN_HEADERS.get(key, name)


def clean_stem(label: str) -> str:
    """'Shop_Bestellungen_Export_2025-2026' -> 'Shop Bestellungen'."""
    stem = label.split(" › ")[0]
    out = []
    for t in stem.replace("_", " ").replace("-", " ").split():
        ft = fold(t)
        if ft in lexicon.CONTAINER_WORDS or t.isdigit() or ft.isdigit() or (len(ft) <= 2 and not ft.isalpha()):
            continue
        out.append(t)
    return " ".join(out) or stem
