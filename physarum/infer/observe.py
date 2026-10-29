"""Observations: a table (or an entity extracted from a table) seen as a set of records.

An observation is the unit the inference works on. A raw table is one observation;
normalisation may split it into several (e.g. order headers, order lines, customers).
"""
from __future__ import annotations

import re
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
    asof: str | None = None          # how current the data is ("Stand"), for "newest fact wins"
    tables: list[int] = field(default_factory=list)  # every raw table (version) behind this observation
    sig_label: str | None = None     # the founder version's name: stable while new versions arrive

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


_EMBEDDED = re.compile(r"(?<![\w-])([A-Za-z]{1,5}[-/]\d{2,6}(?:[-/]\d{2,6})*|[A-Za-z]{1,5}\d{4,})(?![\w-])")


def _shape(tok: str) -> str:
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", tok))


def _embedded_key(c: Col) -> list | None:
    """'P-2026-013 Website-Relaunch' and 'Website-Relaunch Elbe Logistik (P-2025-008)': the number
    inside the name is what identifies the thing; two tools write the same project differently."""
    if c.kind != "text" or c.role not in ("name", None):
        return None
    filled = [v for v in c.values if isinstance(v, str) and v.strip()]
    if len(filled) < 5:
        return None
    found = []
    for v in c.values:
        toks = _EMBEDDED.findall(v) if isinstance(v, str) and len(v) <= 200 else []
        found.append(toks[0] if len(toks) == 1 and toks[0] != v.strip() else None)
    hits = [t for t in found if t]
    if len(hits) < 0.6 * len(filled):
        return None
    shape, n = Counter(_shape(t) for t in hits).most_common(1)[0]
    if n < 0.9 * len(hits) or sum(ch == "9" for ch in shape) < 3:
        return None
    return [t if t and _shape(t) == shape else None for t in found]


def _add_embedded_keys(cols: list[Col]):
    from ..values import profile_column
    for c in list(cols):
        toks = _embedded_key(c)
        if not toks:
            continue
        concept = lexicon.header_concept(c.name)
        name = f"{lexicon.CONCEPTS[concept]['sg']}-Nr." if concept else f"{display_header(c.name)}-Nr."
        if any(x.name == name or x.kind == "id" and x.prof.concept and x.prof.concept == concept for x in cols):
            continue
        prof = profile_column(name, toks)
        if prof.kind not in ("id", "text"):
            continue
        prof.kind, prof.role = "id", "id"
        keys = [match_key(prof, v) for v in prof.values]
        cols.insert(cols.index(c), Col(name=name, prof=prof, values=list(prof.values), keys=keys, origin=c.origin))


_FROM = {"von", "ab", "from", "start", "beginn", "seit"}
_TO = {"bis", "to", "until", "ende", "end"}
_DEADLINE = {"faellig", "faelligkeit", "frist", "deadline", "termin", "due", "zahlbar"}
from ..values import _PLANNED  # noqa: E402 - "Ende (geplant)" stays a date to keep


def _period_ends(cols: list[Col]):
    """'von … bis' (an absence, a contract term): the end of a period, not a deadline to watch."""
    if not any(c.kind in ("date", "datetime") and set(tokens(c.name)) & _FROM for c in cols):
        return
    for c in cols:
        toks = set(tokens(c.name))
        if c.kind in ("date", "datetime") and c.role == "due" and toks & _TO and not toks & _DEADLINE and \
                not toks & _PLANNED:
            c.prof.role = "date"


def obs_from_table(table_id: int, label: str, columns: list[str], profiles: list[Profile],
                   lines: list[tuple[int, int]] | list[int], source_id: int = 0, tables: list[int] | None = None,
                   sig_label: str | None = None) -> Obs:
    """`lines` are (table id, line) pairs; plain ints are taken as lines of `table_id`."""
    cols = []
    for j, (name, prof) in enumerate(zip(columns, profiles)):
        if prof.kind == "empty":
            continue
        cache: dict = {}
        keys = []
        for v in prof.values:
            try:
                k = cache[v]
            except (KeyError, TypeError):
                k = match_key(prof, v)
                try:
                    cache[v] = k
                except TypeError:
                    pass
            keys.append(k)
        cols.append(Col(name=name, prof=prof, values=list(prof.values), keys=keys, origin=(table_id, j)))
    _add_embedded_keys(cols)
    _period_ends(cols)
    _full_name(cols, table_id)
    _name_pair(cols, table_id)
    lines = [l if isinstance(l, tuple) else (table_id, l) for l in lines]
    n = len(lines)
    stem = label.split(" › ")[0]
    sheet = label.split(" › ")[1] if " › " in label else ""
    part = None
    if lexicon.json_path(stem) or ("." in stem and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{2,}", stem.rsplit(".", 1)[1])
                                   and not stem.rsplit(".", 1)[1].isdigit()):
        stem, part = stem.rsplit(".", 1)  # nested export: "Termine_Export.appointments"
    if part is not None:
        concept = lexicon.concept_of(part) or lexicon.concept_of(stem)
    else:
        concept = (lexicon.concept_of(sheet) if sheet else None) or lexicon.concept_of(stem)
    o = Obs(oid=f"T{table_id}", table_id=table_id, label=label, file_concept=concept,
            qualifier=lexicon.qualifier_of(stem), cols=cols, prov=[[l] for l in lines], n=n, source_id=source_id,
            tables=list(tables or [table_id]), sig_label=sig_label)
    o.concept = concept
    o.key = pick_key(o)
    return o


_FIRST = {"vorname", "first", "firstname", "given", "rufname"}
_LAST = {"nachname", "last", "lastname", "surname", "familienname", "family"}


def _full_name(cols: list[Col], table_id: int):
    """Personnel exports split names ('First name', 'Last name'); everyone else writes them in
    one field. A combined name lets both meet."""
    first = next((c for c in cols if c.kind == "text" and set(tokens(c.name)) & _FIRST), None)
    last = next((c for c in cols if c.kind == "text" and set(tokens(c.name)) & _LAST and c is not first), None)
    if not first or not last or any(fold(c.name) == "name" for c in cols):
        return
    vals = []
    for a, b in zip(first.values, last.values):
        v = " ".join(str(x).strip() for x in (a, b) if x not in (None, ""))
        vals.append(v or None)
    from ..values import profile_column
    prof = profile_column("Name", vals)
    prof.role = "name"
    keys = [norm_name(v) if v else None for v in vals]
    first.prof.role = last.prof.role = "person_part"
    cols.insert(cols.index(first), Col(name="Name", prof=prof, values=vals, keys=keys, origin=(table_id, -1)))


_SALUTATION = {"anrede", "salutation", "briefanrede"}
# "Herr", "Frau", "Eheleute", "Familie", "Herr Dr." – a person; "Firma" and an empty salutation – not
_PERSON_SAL = {"herr", "herrn", "frau", "eheleute", "familie", "fam", "hr", "fr", "dr", "prof", "mr", "mrs", "ms"}
_PAIR_NAMES = ("Nachname / Firma", "Vorname / Zusatz")


def _name_pair(cols: list[Col], table_id: int):
    """Older programs keep a customer as salutation, 'NAME1' (surname or firm) and 'NAME2' (first
    names, or an addition such as 'z. Hd. Frau Kortenbruck'). A person is then 'Detlef u. Sabine
    Rasche' – the way a bank statement or a letter names them; a firm keeps its name."""
    if any(fold(c.name) == "name" for c in cols):
        return
    pair = [next((c for c in cols if c.kind == "text" and re.fullmatch(rf"name\s*[_-]?{i}", fold(c.name))), None)
            for i in (1, 2)]
    sal = next((c for c in cols if set(tokens(c.name)) & _SALUTATION), None)
    if None in pair or sal is None:
        return
    n1, n2 = pair
    vals, persons = [], 0
    for s, a, b in zip(sal.values, n1.values, n2.values):
        words = fold(str(s or "")).replace(".", " ").split()
        person = bool(words) and words[0] in _PERSON_SAL
        a = str(a).strip() if a not in (None, "") else ""
        b = str(b).strip() if b not in (None, "") else ""
        if person and a and b:
            persons += 1
            vals.append(f"{b} {a}")
        else:
            vals.append(a or None)
    if not persons:
        return
    from ..values import profile_column
    prof = profile_column("Name", vals)
    prof.role = "name"
    keys = [norm_name(v) if v else None for v in vals]
    n1.name, n2.name = _PAIR_NAMES
    n1.prof.role = n2.prof.role = "person_part"
    cols.insert(cols.index(n1), Col(name="Name", prof=prof, values=vals, keys=keys, origin=(table_id, -1)))


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
    "postal code": "PLZ", "postcode": "PLZ", "street": "Straße", "display name": "Name", "start": "Beginn",
    "end": "Ende", "resource ids": "Mitarbeiter", "resources": "Mitarbeiter", "short": "Kürzel",
    "created": "Erstellt am", "updated at": "Geändert am", "reference": "Bezug", "price estimate amount": "Schätzpreis",
    "amount": "Betrag", "currency": "Währung", "customer": "Kunde", "notes": "Notizen", "title": "Titel",
    # ticket systems, CRMs and time trackers export in English
    "id": "ID", "subject": "Betreff", "description text": "Beschreibung", "priority": "Priorität", "source": "Quelle",
    "resolved at": "Gelöst am", "closed at": "Geschlossen am", "first responded at": "Erste Antwort am",
    "due by": "Fällig am", "executed at": "Ausgeführt am", "time spent": "Zeitaufwand", "billable": "Abrechenbar",
    "agent": "Bearbeiter", "agent email": "E-Mail (Bearbeiter)", "responder": "Bearbeiter", "requester": "Kontakt",
    "ticket id": "Ticket-Nr.", "start time": "Startzeit", "end time": "Endzeit", "billable rate eur": "Stundensatz (EUR)",
    "billable amount eur": "Betrag (EUR)", "duration h": "Dauer (h)", "duration decimal": "Dauer (dezimal)",
    "duration": "Dauer", "task": "Aufgabe", "user": "Mitarbeiter", "group": "Team", "client": "Kunde",
    "project": "Projekt", "record id": "Datensatz-Nr. (CRM)", "phone number": "Telefon", "job title": "Position",
    "associated company id": "Firmen-Nr. (CRM)", "associated company ids": "Firmen-Nr. (CRM)",
    "lifecycle stage": "Lebenszyklus", "create date": "Erstellt am", "last activity date": "Letzte Aktivität",
    "deal name": "Verkaufschance", "deal stage": "Phase", "close date": "Abschlussdatum", "deal type": "Art",
    "company domain name": "Website", "industry": "Branche", "cf umgebung": "Umgebung", "cf projekt": "Projekt",
    "von": "Von", "bis": "Bis", "country region": "Land",
}


def display_header(name: str) -> str:
    parts = lexicon.json_path(name)
    if parts:
        if len(parts) >= 2:
            last = " ".join(tokens(parts[-1]))
            if last in ("id", "nr", "no", "number", "uuid") and len(parts) >= 2:
                return display_header(parts[-2]) + "-Nr."
            if last in ("display name", "name") and len(parts) == 2:
                return display_header(parts[-2])
            return display_header(parts[-1])
    key = " ".join(tokens(name))
    if key in _EN_HEADERS:
        return _EN_HEADERS[key]
    return _calm(name)


_KEEP_CAPS = {"kdnr", "plz", "iban", "bic", "ust", "ustid", "mwst", "nr", "id", "ean", "gtin", "sku", "eur", "usd", "chf",
              "gmbh", "ag", "kg", "ok"}
_UMLAUTS = {"strasse": "Straße", "groesse": "Größe", "gebaeude": "Gebäude", "faellig": "fällig", "maerz": "März",
            "loeschen": "löschen", "geaendert": "geändert", "kuerzel": "Kürzel"}


def _calm(name: str) -> str:
    """'KUNDE_SEIT' is how an old program shouts a header: 'Kunde seit'. Abbreviations stay."""
    letters = [ch for ch in name if ch.isalpha()]
    if len(letters) < 3 or not all(ch.isupper() for ch in letters):
        return name
    words = [w for w in re.split(r"[_\s]+", name.strip()) if w]
    if len(words) == 1 and fold(words[0]) in _KEEP_CAPS:
        return name
    out = [{"nr": "Nr.", "id": "ID"}.get(fold(w)) or (w if fold(w) in _KEEP_CAPS else _UMLAUTS.get(fold(w), w.lower()))
           for w in words]
    out[0] = out[0][:1].upper() + out[0][1:]
    return " ".join(out)


def clean_stem(label: str) -> str:
    """'Shop_Bestellungen_Export_2025-2026' -> 'Shop Bestellungen'; a nested export's array
    ('Termine_Export.resources') is named by the array."""
    stem = label.split(" › ")[0]
    if lexicon.json_path(stem):
        part = stem.rsplit(".", 1)[1]
        stem = display_header(part) if display_header(part) != part else part[:1].upper() + part[1:]
    out = []
    for t in stem.replace("_", " ").replace("-", " ").split():
        ft = fold(t)
        if ft in lexicon.CONTAINER_WORDS or t.isdigit() or ft.isdigit() or (len(ft) <= 2 and not ft.isalpha()):
            continue
        out.append(t)
    return " ".join(out) or stem
