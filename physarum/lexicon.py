"""Business vocabulary (German/English): what things are called and what columns mean.

The lexicon is deliberately small. It only seeds the inference; the data decides.
Terms are folded (see text.fold) and matched against header/file-name tokens.
"""
from __future__ import annotations

import re

from .text import fold, tokens

# concept -> singular, plural, compound stem, kind, terms (folded; prefix match for terms ending in '*')
CONCEPTS: dict[str, dict] = {
    "kunde": dict(sg="Kunde", pl="Kunden", stem="Kunden", kind="master",
                  terms=["kunde", "kunden", "kdnr", "kundennr", "kundennummer", "customer", "customers", "client",
                         "clients", "debitor", "debitoren", "kaeufer", "buyer", "abnehmer", "billing",
                         "auftraggeber", "mandant", "mandanten", "account", "accounts"]),
    "lieferant": dict(sg="Lieferant", pl="Lieferanten", stem="Lieferanten", kind="master",
                      terms=["lieferant", "lieferanten", "liefnr", "supplier", "suppliers", "vendor", "vendors",
                             "kreditor", "kreditoren", "haendler", "grosshaendler", "grosshandel"]),
    "artikel": dict(sg="Artikel", pl="Artikel", stem="Artikel", kind="master",
                    terms=["artikel", "artnr", "artikelnr", "artikelnummer", "produkt", "produkte", "product",
                           "products", "item", "items", "ware", "waren", "sku", "material", "materialien",
                           "lineitem", "leistung", "leistungen", "sortiment", "preisliste", "katalog"]),
    "auftrag": dict(sg="Auftrag", pl="Aufträge", stem="Auftrags", kind="transaction", party="kunde",
                    terms=["auftrag", "auftraege", "auftrags", "auftragsnr", "kundenauftrag", "kundenauftraege",
                           "order", "orders", "salesorder", "job", "jobs"]),
    "bestellung": dict(sg="Bestellung", pl="Bestellungen", stem="Bestell", kind="transaction", party="kunde",
                       terms=["bestellung", "bestellungen", "bestell", "bestellnr", "purchase", "po"]),
    "einkauf": dict(sg="Einkauf", pl="Einkäufe", stem="Einkaufs", kind="transaction", party="lieferant",
                    terms=["einkauf", "einkaeufe", "beschaffung", "wareneingang", "purchases", "procurement"]),
    "angebot": dict(sg="Angebot", pl="Angebote", stem="Angebots", kind="transaction", party="kunde",
                    terms=["angebot", "angebote", "angebots", "quote", "quotes", "offer", "offers", "kostenvoranschlag",
                           "kva"]),
    "rechnung": dict(sg="Rechnung", pl="Rechnungen", stem="Rechnungs", kind="transaction", party="kunde",
                     terms=["rechnung", "rechnungen", "rechnungs", "renr", "rechnungsnr", "invoice", "invoices",
                            "faktura", "fakturen", "ausgangsrechnung", "ausgangsrechnungen"]),
    # the measured work of a job, position by position: what the final invoice is made from
    "aufmass": dict(sg="Aufmaßposition", pl="Aufmaßpositionen", stem="Aufmaß", kind="transaction", party="auftrag",
                    terms=["aufmass", "aufmasse", "aufmasses", "schlussaufmass", "aufmassblatt", "massenermittlung",
                           "aufmassliste"],
                    # each row is a position: a "Schlussaufmaß" file holds Aufmaßpositionen
                    names={w: ("Aufmaßposition", "Aufmaßpositionen") for w in ("aufmass", "schlussaufmass",
                                                                               "aufmassblatt", "aufmassliste")}),
    "lieferschein": dict(sg="Lieferschein", pl="Lieferscheine", stem="Lieferschein", kind="transaction",
                         party="kunde",
                         terms=["lieferschein", "lieferscheine", "lieferung", "lieferungen", "delivery", "deliveries",
                                "shipment", "shipments", "versand"]),
    "zahlung": dict(sg="Zahlung", pl="Zahlungen", stem="Zahlungs", kind="transaction",
                    terms=["zahlung", "zahlungen", "zahlungseingang", "zahlungseingaenge", "payment", "payments"]),
    "kontobewegung": dict(sg="Kontobewegung", pl="Kontobewegungen", stem="Kontobewegungs", kind="transaction",
                          terms=["kontoauszug", "kontoauszuege", "umsaetze", "kontoumsaetze", "bank", "banking",
                                 "statement", "transactions", "girokonto", "konto", "kontobewegungen", "umsatzanzeige"]),
    "mitarbeiter": dict(sg="Mitarbeiter", pl="Mitarbeiter", stem="Mitarbeiter", kind="master",
                        terms=["mitarbeiter", "mitarbeiterin", "personal", "employee", "employees", "staff", "team",
                               "angestellte", "belegschaft", "resources", "ressourcen", "monteure", "techniker"]),
    "projekt": dict(sg="Projekt", pl="Projekte", stem="Projekt", kind="transaction", party="kunde",
                    terms=["projekt", "projekte", "project", "projects", "baustelle", "baustellen"]),
    "vertrag": dict(sg="Vertrag", pl="Verträge", stem="Vertrags", kind="transaction", party="kunde",
                    terms=["vertrag", "vertraege", "contract", "contracts", "abo", "abos", "subscription",
                           "subscriptions", "wartungsvertrag", "wartungsvertraege"]),
    "kontakt": dict(sg="Kontakt", pl="Kontakte", stem="Kontakt", kind="master", party="kunde",
                    terms=["kontakt", "kontakte", "contact", "contacts", "ansprechpartner", "adressen", "adresse",
                           "adressbuch"]),
    "termin": dict(sg="Termin", pl="Termine", stem="Termin", kind="transaction",
                   terms=["termin", "termine", "appointment", "appointments", "kalender", "einsatz", "einsaetze"]),
    "lager": dict(sg="Lagerbestand", pl="Lagerbestände", stem="Lager", kind="master",
                  terms=["lager", "lagerbestand", "bestand", "bestaende", "inventory", "stock", "inventur"]),
    "ticket": dict(sg="Ticket", pl="Tickets", stem="Ticket", kind="transaction", party="kunde",
                   terms=["ticket", "tickets", "reklamation", "reklamationen", "anfrage", "anfragen", "support"]),
    "dokument": dict(sg="Dokument", pl="Dokumente", stem="Dokument", kind="document",
                     terms=["dokument", "dokumente", "document", "documents"]),
    "zeiteintrag": dict(sg="Zeiteintrag", pl="Zeiteinträge", stem="Zeit", kind="transaction", party="projekt",
                        names={"stundenzettel": ("Stundenzettel", "Stundenzettel"),
                               "stundennachweis": ("Stundennachweis", "Stundennachweise"),
                               "stundennachweise": ("Stundennachweis", "Stundennachweise")},
                        terms=["zeiteintrag", "zeiteintraege", "zeiterfassung", "stundenzettel", "stundennachweis",
                               "stundennachweise", "timesheet", "timesheets", "zeitbuchung", "zeitbuchungen",
                               "stundenbuchung", "stundenbuchungen", "stundenerfassung"]),
    "verkaufschance": dict(sg="Verkaufschance", pl="Verkaufschancen", stem="Verkaufschancen", kind="transaction",
                           party="kunde", terms=["verkaufschance", "verkaufschancen", "deal", "deals", "opportunity",
                                                 "opportunities", "pipeline"]),
    "abwesenheit": dict(sg="Abwesenheit", pl="Abwesenheiten", stem="Abwesenheits", kind="transaction",
                        party="mitarbeiter", terms=["abwesenheit", "abwesenheiten", "urlaub", "urlaube", "urlaubsplan",
                                                    "fehlzeiten", "absence", "absences", "krankmeldungen"]),
}
# terms that only count as whole words ("deal" is not in "Idealo")
_EXACT_TERMS = {"deal", "deals", "urlaub"}
# two-word names of a concept ("time entries", "time report")
CONCEPT_PHRASES = {"time entries": "zeiteintrag", "time entry": "zeiteintrag", "time report": "zeiteintrag",
                   "time tracking": "zeiteintrag", "time sheet": "zeiteintrag", "time sheets": "zeiteintrag",
                   "time logs": "zeiteintrag", "time log": "zeiteintrag"}

# words that describe the container, not the content ("Kundenliste" is about Kunden)
CONTAINER_WORDS = {
    "liste", "listen", "list", "export", "exports", "import", "tabelle", "table", "uebersicht", "verzeichnis",
    "datei", "daten", "data", "stamm", "stammdaten", "buch", "journal", "dump", "backup", "final", "neu", "alt",
    "old", "new", "kopie", "copy", "version", "stand", "aktuell", "current", "report", "bericht", "auswertung",
    "sheet", "blatt", "tabelle1", "sheet1", "file", "ausgang", "eingang", "csv", "xlsx", "xls", "txt", "v",
    "teil", "gesamt", "alle", "all", "master", "main", "my", "meine", "unsere", "firma", "kw",
}
QUALIFIER_WORDS = {"shop": "Shop", "online": "Online", "webshop": "Shop", "amazon": "Amazon", "ebay": "eBay",
                   "b2b": "B2B", "b2c": "B2C"}

# column roles ------------------------------------------------------------------------------
ROLE_TERMS: dict[str, list[str]] = {
    "id": ["nr", "no", "nummer", "number", "num", "id", "kennung", "code", "schluessel", "key", "ref", "referenz",
           "reference", "zeichen", "kennzeichen", "belegnr", "beleg"],
    "name": ["name", "namen", "bezeichnung", "firma", "firmenname", "company", "unternehmen", "titel", "title",
             "benennung", "label", "produktname", "artikelname", "kurzname", "billing"],
    "person": ["ansprechpartner", "kontakt", "contact", "person", "vorname", "nachname", "firstname", "lastname",
               "inhaber", "zustaendig", "bearbeiter", "verantwortlich", "owner", "sachbearbeiter", "techniker"],
    "email": ["email", "mail", "emailadresse"],
    "phone": ["telefon", "tel", "phone", "mobil", "mobile", "handy", "fon", "fax", "rufnummer"],
    "street": ["strasse", "str", "street", "adresse", "anschrift", "address", "hausnummer"],
    "zip": ["plz", "postleitzahl", "zip", "zipcode", "postcode", "postal"],
    "city": ["ort", "stadt", "city", "wohnort", "town", "gemeinde", "lieferort"],
    "country": ["land", "country", "staat"],
    "money": ["betrag", "summe", "preis", "price", "amount", "total", "gesamt", "netto", "brutto", "umsatz", "wert",
              "kosten", "cost", "costs", "eur", "euro", "honorar", "pauschale", "gebuehr", "fee", "subtotal",
              "shipping", "versandkosten", "rabattbetrag", "lohn", "gehalt", "vk", "ek", "listenpreis", "einzelpreis",
              "stueckpreis", "gesamtpreis", "monatspauschale", "saldo", "offen", "rest",
              "soll", "haben", "debit", "credit", "einnahme", "einnahmen", "ausgabe", "ausgaben", "budget",
              "festpreis", "auftragswert", "kostenrahmen"],
    "quantity": ["menge", "anzahl", "stueck", "stk", "qty", "quantity", "anz", "kg", "liter", "stunden", "std",
                 "hours", "saecke", "sack", "kartons", "einheiten", "bestand", "mindestbestand", "meldebestand",
                 "lagerbestand", "units", "pieces", "wochenstunden"],
    "percent": ["rabatt", "mwst", "ust", "steuersatz", "prozent", "percent", "discount", "skonto", "marge", "tax",
                "vat"],
    "date": ["datum", "date", "am", "tag", "zeitpunkt", "created", "erstellt", "angelegt", "beginn", "start",
             "eintritt", "since", "seit", "at", "on", "buchungstag", "valutadatum", "valuta", "geliefert",
             "bezahlt", "eingang", "versendet", "erledigt", "abgeschlossen", "storniert", "fulfilled", "paid",
             "shipped", "delivered", "closed", "ende", "end"],
    "due": ["faellig", "faelligkeit", "due", "frist", "deadline", "termin", "liefertermin", "wunschtermin",
            "naechste", "next", "bis", "ablauf", "expires", "expiry", "gueltig"],
    "status": ["status", "zustand", "state", "stage", "phase", "stand", "fortschritt", "progress"],
    "category": ["gruppe", "kategorie", "category", "typ", "type", "art", "segment", "klasse", "sorte",
                 "kundengruppe", "warengruppe", "bereich", "abteilung", "funktion", "rolle", "role", "gebinde",
                 "einheit", "unit", "roestung", "herkunft", "kanal", "channel", "zahlungsart"],
    "notes": ["notiz", "notizen", "bemerkung", "bemerkungen", "kommentar", "comment", "comments", "note", "notes",
              "beschreibung", "description", "info", "hinweis", "text", "verwendungszweck", "betreff", "subject",
              "memo", "details"],
    "iban": ["iban", "kontonummer", "konto", "bankverbindung"],
    "bic": ["bic", "swift"],
    "vat_id": ["ustid", "ustidnr", "vatid", "steuernummer", "steuernr"],
    "url": ["url", "web", "website", "homepage", "link"],
    "unit": ["einheit", "unit", "me", "mengeneinheit"],
}
# phrases (folded, space separated) with fixed meaning; checked before single tokens
ROLE_PHRASES: dict[str, str] = {
    "zahlungsziel": "duration", "zahlungsziel tage": "duration", "lieferzeit": "duration", "laufzeit": "duration",
    "kd nr": "id", "art nr": "id", "re nr": "id", "bestell nr": "id", "auftrags nr": "id", "lineitem sku": "id",
    "fulfillment status": "status", "financial status": "status", "payment status": "status",
    "lineitem price": "money", "lineitem quantity": "quantity", "lineitem name": "name",
    "billing name": "name", "shipping city": "city", "e mail": "email", "kontonummer iban": "iban",
    "beguenstigter zahlungspflichtiger": "name", "auftraggeber empfaenger": "name", "buchungstext": "category",
    "preis kg": "money", "summe eur": "money", "vk netto": "money", "created at": "date", "fulfilled at": "date",
    "customer since": "date", "bezahlt am": "date", "geliefert am": "date", "eingang am": "date",
    "naechste wartung": "due", "letzte wartung": "date", "faellig am": "due",
    "postal code": "zip", "zip code": "zip", "post code": "zip", "postleitzahl": "zip", "display name": "name",
    "empfaenger zahlungspflichtiger": "name", "auftraggeber zahlungsempfaenger": "name",
    "naechster termin": "due", "naechste pruefung": "due", "faellig bis": "due", "wartung faellig": "due",
    "resource ids": "person", "monteur": "person", "techniker": "person", "bearbeiter": "person",
}

# words that, in a header, mark the *end* of a process ("Bezahlt am", "Geliefert am")
MILESTONE_WORDS = {
    "geliefert": "geliefert", "lieferung": "geliefert", "delivered": "geliefert", "versendet": "versendet",
    "versand": "versendet", "shipped": "versendet", "fulfilled": "versendet", "bezahlt": "bezahlt", "paid": "bezahlt",
    "zahlung": "bezahlt", "zahlungseingang": "bezahlt", "eingang": "eingegangen", "erhalten": "eingegangen",
    "received": "eingegangen", "erledigt": "erledigt", "done": "erledigt", "abgeschlossen": "abgeschlossen",
    "closed": "abgeschlossen", "berechnet": "berechnet", "fakturiert": "berechnet", "invoiced": "berechnet",
    "storniert": "storniert", "cancelled": "storniert", "canceled": "storniert", "angenommen": "angenommen",
    "accepted": "angenommen", "unterschrieben": "unterschrieben", "signed": "unterschrieben", "gemahnt": "gemahnt",
    "freigegeben": "freigegeben", "approved": "freigegeben", "montiert": "montiert", "installiert": "installiert",
    "wartung": "gewartet", "gewartet": "gewartet", "ende": "beendet", "end": "beendet", "austritt": "ausgetreten",
}

# a date to act on, not one on which something happened ("nachfassen am", "Wiedervorlage", "Follow-up")
FOLLOW_UP = ("nachfass", "wiedervorlage", "followup", "nachhaken")



def _follows_up(toks: list[str]) -> bool:
    return any(t.startswith(FOLLOW_UP) for t in toks) or ("follow" in toks and "up" in toks)


def is_follow_up(header: str) -> bool:
    """'nachfassen am', 'Wiedervorlage': a day to call the customer again, not a deadline someone owes."""
    return _follows_up(tokens(header))


# status values that terminate a process without completing it
# how people are addressed and titled: "Fam. Fischer", "Herrn Dr. Behrens" – a person, not a firm, and not part of the name
SALUTATIONS = {"fam", "familie", "eheleute", "ehel", "herr", "herrn", "frau", "hr", "fr"}
TITLES = {"dr", "med", "dent", "vet", "prof", "dipl", "ing", "rer", "nat", "phil", "jur", "mag"}

NEGATIVE_STATES = {"storniert", "storno", "cancelled", "canceled", "abgesagt", "abgelehnt", "rejected", "verloren",
                   "lost", "refunded", "erstattet", "zurueckgezogen", "void", "ungueltig", "inaktiv", "inactive",
                   "gekuendigt", "archiviert"}
# status values that mean "done"
DONE_STATES = {"bezahlt", "paid", "erledigt", "done", "abgeschlossen", "closed", "geliefert", "delivered",
               "fulfilled", "versendet", "shipped", "fertig", "complete", "completed", "beglichen", "ausgeglichen"}

TOTAL_WORDS = {"summe", "gesamt", "total", "totals", "sum", "zwischensumme", "endsumme", "gesamtsumme", "insgesamt",
               "subtotal", "uebertrag"}

ADDRESS_ROLES = {"street", "zip", "city", "country", "phone", "email", "iban", "bic", "url"}


ABBREVIATIONS = {"kd": "kunde", "kdn": "kunde", "art": "artikel", "lief": "lieferant", "re": "rechnung",
                 "ma": "mitarbeiter", "auf": "auftrag", "ang": "angebot", "ls": "lieferschein", "bel": "dokument"}
ID_TOKENS = {"nr", "no", "nummer", "number", "num", "id", "code", "kennung"}
REF_SUFFIXES = ("nummer", "nr", "name", "id", "code", "bezeichnung", "kennung", "no", "mail", "email")
NONREF_SUFFIXES = ("gruppe", "typ", "art", "kategorie", "segment", "klasse", "status", "datum", "ziel", "seit",
                   "zahl", "anzahl", "preis", "nummernkreis", "konto", "rabatt", "umsatz", "wert", "summe",
                   "kosten", "betrag", "menge", "zeit", "tage", "frist", "termin", "bestand")


# words that end with a concept but mean something else ("Abrechnung" is how a project is billed)
_FALSE_COMPOUNDS = {"abrechnung", "abrechnungen", "abrechnungsart", "verrechnung", "berechnung", "umrechnung",
                    "nachberechnung", "einrechnung", "hochrechnung", "gegenrechnung",
                    # a partner's bank details are master data, not the firm's bank statement
                    "bankdaten", "bankverbindung", "bankverbindungen", "kontodaten", "kontoverbindung",
                    "kontoverbindungen", "bankangaben", "kontoangaben", "bankinfo", "bankdetails"}


def _compound_concept(tok: str) -> tuple[str | None, str]:
    """Split a (possibly compound) token into (concept, rest). Rightmost concept term wins."""
    if tok in _FALSE_COMPOUNDS:
        return None, tok
    best: tuple[int, int, str] | None = None  # (end position, length, concept)
    for c, spec in CONCEPTS.items():
        for term in spec["terms"]:
            if len(term) < 4 or term in _EXACT_TERMS:
                if tok == term:
                    cand = (len(tok), len(term), c)
                    best = max(best, cand) if best else cand
                continue
            pos = tok.rfind(term)
            if pos < 0:
                continue
            cand = (pos + len(term), len(term), c)
            if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                best = cand
    if not best:
        return None, tok
    end = best[0]
    return best[2], tok[end:]


def concepts_in_tokens(toks: list[str]) -> list[tuple[int, str]]:
    hits = []
    for i, t in enumerate(toks):
        if i + 1 < len(toks) and f"{t} {toks[i + 1]}" in CONCEPT_PHRASES:
            hits.append((i, CONCEPT_PHRASES[f"{t} {toks[i + 1]}"]))
            continue
        if t in CONTAINER_WORDS or t.isdigit():
            continue
        c, _rest = _compound_concept(t)
        if c:
            hits.append((i, c))
    return hits


def concept_of(text: str) -> str | None:
    """Concept of a file/sheet name like 'Kundenliste_2023.xlsx', 'Aufträge Großkunden', 'customer_orders'.
    Transactions beat master data (orders of customers are orders)."""
    hits = concepts_in_tokens(tokens(text))
    if not hits:
        return None
    trans = [c for _, c in hits if CONCEPTS[c]["kind"] == "transaction"]
    return trans[0] if trans else hits[0][1]


_re_digit_tail = re.compile(r"(?<=[a-z])\d$")
_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]+(?:\.[A-Za-z_][A-Za-z0-9_]+)+")


def json_path(header: str) -> list[str] | None:
    """'customer.address.postal_code' -> its parts; 'Art.-Nr' or 'z.B.' are not paths."""
    h = str(header).strip()
    return h.split(".") if _PATH.fullmatch(h) else None
_PATH_ID = {"id", "nr", "no", "number", "uuid", "key", "code", "display name", "name"}


def header_concept(header: str) -> str | None:
    """Entity concept a column header *refers to*: 'Kd-Nr' -> kunde, 'Lieferant' -> lieferant,
    'Kundennummer' -> kunde, but 'Kundengruppe' -> None and 'Rechnungsdatum' -> None.
    Paths from nested exports ('customer.address.postal_code') speak through their last part:
    a postal code inside a customer is a postal code, not a customer."""
    parts = json_path(header)
    if parts:
        if len(parts) >= 2:
            c = header_concept(parts[-1])
            if c:
                return c
            if " ".join(tokens(parts[-1])) in _PATH_ID and len(parts) == 2:
                return header_concept(parts[-2])
            return None
    plain = tokens(header, camel=False)
    c = _header_concept(plain)
    if c is None:
        split = tokens(header)
        if split != plain:
            c = _header_concept(split)
    return c


def _header_concept(toks: list[str]) -> str | None:
    for i, t in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if t in ABBREVIATIONS and nxt in ID_TOKENS:
            return ABBREVIATIONS[t]
        c, rest = _compound_concept(t)
        if not c:
            continue
        rest = rest.lstrip("s") if rest.startswith("s") and len(rest) > 3 else rest
        if rest == "" or rest.startswith(REF_SUFFIXES):
            if nxt and nxt.startswith(NONREF_SUFFIXES) and nxt not in ID_TOKENS:
                return None
            return c
        if rest.startswith(NONREF_SUFFIXES) or rest in CONTAINER_WORDS:
            return None
    return None


def qualifier_of(text: str) -> str | None:
    for t in tokens(text):
        if t in QUALIFIER_WORDS:
            return QUALIFIER_WORDS[t]
    return None


def header_role(header: str) -> str | None:
    """Role suggested by a column header alone (values may override)."""
    parts = json_path(header)
    if parts:
        return header_role(parts[-1])
    plain = [_re_digit_tail.sub("", t) or t for t in tokens(header, camel=False)]  # "Name1", "Strasse2"
    split = [_re_digit_tail.sub("", t) or t for t in tokens(header)]
    r = _header_role(plain)
    if r is None and split != plain:
        r = _header_role(split)
    return r


def _header_role(toks: list[str]) -> str | None:
    if not toks:
        return None
    phrase = " ".join(toks)
    if phrase in ROLE_PHRASES:
        return ROLE_PHRASES[phrase]
    for n in (3, 2):
        for i in range(len(toks) - n + 1):
            p = " ".join(toks[i:i + n])
            if p in ROLE_PHRASES:
                return ROLE_PHRASES[p]
    if _follows_up(toks):
        return "due"
    # last token is the head of the header in German and English ("Kunden-Nr", "Order ID")
    order = list(reversed(toks))
    for t in order:
        for role in ("id", "email", "phone", "zip", "iban", "bic", "vat_id", "url", "due", "status", "percent",
                     "money", "quantity", "date", "street", "city", "country", "notes", "person", "category",
                     "name", "unit"):
            if t in ROLE_TERMS[role]:
                return role
        # compounds: "kundennummer", "rechnungsdatum", "einzelpreis", "liefertermin"
        for role, suffixes in (("id", ("nummer", "nr", "id", "code")), ("date", ("datum", "date")),
                               ("due", ("termin", "frist", "faelligkeit")), ("money", ("preis", "betrag", "summe",
                                                                                         "kosten", "wert", "umsatz",
                                                                                         "pauschale")),
                               ("quantity", ("menge", "anzahl", "bestand", "stunden")),
                               ("name", ("name", "bezeichnung")), ("notes", ("notiz", "bemerkung", "text")),
                               ("phone", ("telefon",)), ("person", ("partner",)), ("category", ("gruppe", "art",
                                                                                                  "kategorie", "typ"))):
            if len(t) > 4 and t.endswith(suffixes):
                return role
    return None


def milestone_label(header: str) -> str | None:
    for t in tokens(header):
        if t in MILESTONE_WORDS:
            return MILESTONE_WORDS[t]
        for w, lab in MILESTONE_WORDS.items():
            if len(w) >= 6 and t.startswith(w):
                return lab
    return None


def concept_names(concept: str) -> tuple[str, str, str]:
    spec = CONCEPTS[concept]
    return spec["sg"], spec["pl"], spec["stem"]


def is_total_label(value) -> bool:
    if not isinstance(value, str):
        return False
    toks = tokens(value)
    # "Summe", "Gesamt netto", "Zwischensumme Wohnung 1 (EG links)"
    return bool(toks) and toks[0] in TOTAL_WORDS and len(toks) <= (8 if toks[0] == "zwischensumme" else 4)


BALANCE_WORDS = {"anfangssaldo", "endsaldo", "schlusssaldo", "saldovortrag", "kontostand", "saldo", "uebertrag",
                 "alter saldo", "neuer saldo", "opening balance", "closing balance", "balance"}


def is_balance_label(value) -> bool:
    if not isinstance(value, str) or len(value) > 40:
        return False
    return " ".join(tokens(value)) in BALANCE_WORDS


FIRST_NAMES = set("""
anna anne annika antje alexander alexandra andrea andreas angelika anja ansgar anton antonia arne axel barbara bastian
beate ben benedikt benjamin bernd berit bettina birgit bjoern boris brigitte britta carina carl carla carlotta carolin
caroline charlotte christa christian christiane christina christine christoph clara claudia constanze cornelia daniel
daniela david denise dennis dieter dirk doris dominik doreen edith elena elias elisabeth elke ella ellen emil emilia
emily emma erik erika ernst esther eva fabian felix finn florian frank franz franziska frauke frederik frieda friedrich
fritz gabi gabriele georg gerd gerhard gesa gisela greta gudrun guenter hanna hannah hannes hans harald hauke heike
heiko heinz helga helmut hendrik henning henri henrik herbert hilde holger horst ida ilse ines inga ingo ingrid irene
iris isabel jakob jan jana janina jannik jasmin jens jessica joachim jochen johann johanna johannes jonas jonathan
josef judith julia julian juliane jutta kai karin karl karla karsten katharina kathrin katja katrin kerstin kevin
kim klaus konstantin kristina kurt lara lars laura lea lena leni leo leon leonie lina linda lisa lotta lotte louisa
luca luis luise lukas lutz maja malte manfred manuel manuela marc marcel marco maren margarete maria marie marina
mario marion marius mark markus marlene martha martin martina mathias matthias max maximilian melanie mia michael
michaela mila milan mira mirko moritz nadine nadja natalie nele nick nicole niklas nils nina noah nora norbert ole
olaf oliver oskar otto patricia patrick paul paula peter petra philipp pia rainer ralf ralph rebecca regina reinhard
renate rene richard rita robert robin roland rolf romy ronja rosa ruth sabine sabrina sandra sara sarah sascha
sebastian silke simon simone smilla sofia sophia sophie stefan stefanie steffen stephan susanne sven svenja swen
tanja theo thomas thorsten tilo tim timo tina tobias tom torben torsten ulf ulla ulrich ulrike ursula uta ute uwe
valentin vanessa vera veronika viktor walter werner wiebke wilhelm wolfgang yvonne fiete henry jonte karolina mattis
""".split())

BUSINESS_WORDS = {"cafe", "kaffeebar", "kaffeehaus", "hotel", "restaurant", "bistro", "baeckerei", "konditorei",
                  "feinkost", "buero", "kanzlei", "coworking", "shop", "handel", "service", "technik", "import",
                  "export", "verpackungen", "kontor", "traders", "gruppe", "group", "werk", "werke", "bau", "praxis",
                  "studio", "agentur", "apotheke", "markt", "laden", "haus", "stadtwerke", "bank", "versicherung"}


def looks_like_person(name: str) -> bool:
    """'Hannah Becker' yes, 'Hotel Landungsbrücke' or 'Kaffee Kontor Nord GmbH' no."""
    toks = tokens(name)
    if not 2 <= len(toks) <= 3:
        return False
    if any(t in BUSINESS_WORDS for t in toks):
        return False
    return toks[0] in FIRST_NAMES


def specific_name(text: str, concept: str) -> tuple[str, str] | None:
    """A more specific name than the concept, if the file says so: 'Wartungsverträge' instead of
    'Verträge', 'Lieferantenrechnung' instead of 'Rechnung'. Only when the word *ends* with the
    concept (German compounds put the head last) and is not a container ('Kundenliste')."""
    import re as _re
    from .text import plural_de, singular_de

    words = [w for w in _re.split(r"[^A-Za-zÄÖÜäöüß]+", str(text)) if w]
    own = CONCEPTS.get(concept, {}).get("names") or {}
    for w in words:
        if fold(w) in own:
            return own[fold(w)]  # the firm's own word for it ("Stundenzettel", not "Zeiteintrag")
    for w in words:
        f = fold(w)
        c, rest = _compound_concept(f)
        if c != concept or rest:
            continue  # concept not at the end of the word (rest is e.g. "liste")
        head = {fold(CONCEPTS[c]["sg"]), fold(CONCEPTS[c]["pl"])}
        terms = [t for t in CONCEPTS[c]["terms"] if f.endswith(t) and t in head]
        if not terms:
            continue  # "Volksbank" or "Geschäftskonto" ends with a related word ("bank", "konto"), not the thing
        term = min(terms, key=len)  # the base word ("vertraege"), not the compound listed as a synonym
        if len(f) - len(term) < 3:
            continue
        sg = singular_de(w[:1].upper() + w[1:])
        if fold(sg) == fold(w):
            pl = plural_de(sg)
        else:
            pl = w[:1].upper() + w[1:]
        return sg, pl
    return None


EN_VALUES = {
    "fulfilled": "versendet", "unfulfilled": "nicht versendet", "partial": "teilweise", "partially_fulfilled": "teilweise versendet",
    "paid": "bezahlt", "pending": "ausstehend", "refunded": "erstattet", "partially_refunded": "teilweise erstattet",
    "partially_paid": "teilweise bezahlt", "authorized": "autorisiert", "voided": "storniert", "cancelled": "storniert",
    "canceled": "storniert", "open": "offen", "closed": "abgeschlossen", "done": "erledigt", "draft": "Entwurf",
    "retail": "Einzelhandel", "wholesale": "Großhandel", "office": "Büro", "private": "Privat", "business": "Gewerbe",
    "active": "aktiv", "inactive": "inaktiv", "yes": "ja", "no": "nein", "true": "ja", "false": "nein",
    "scheduled": "geplant", "confirmed": "bestätigt", "in_progress": "in Arbeit", "completed": "erledigt",
}


def show_value(v) -> str:
    """Values from English exports read in German; the original stays in the data."""
    s = str(v)
    return EN_VALUES.get(s.strip().casefold().replace(" ", "_"), s)


def dative_plural(plural: str) -> str:
    """„zwischen den Aufträgen“, „mit den Artikeln“ – German plural nouns take -n in the dative."""
    p = plural.strip()
    if p.endswith(")") and " (" in p:  # "Zeiteinträge (Tickets)" -> "Zeiteinträgen (Tickets)"
        head, tail = p.split(" (", 1)
        return f"{dative_plural(head)} ({tail}"
    return p if not p or p.endswith(("n", "s")) or not p[-1].isalpha() else p + "n"


_UNNAMED = re.compile(r"^(?:spalte|column|col|feld|field|unnamed)[\s_:]*\d+$", re.I)


def is_unnamed(header: str | None) -> bool:
    """'Spalte 2' was made up by the reader for a column without a heading: nobody can say what it means."""
    return bool(header) and bool(_UNNAMED.match(str(header).strip()))


# a status that says a step happened, in the firm's words
STEP_STATES = {
    "berechnet": {"abgerechnet", "berechnet", "fakturiert", "in rechnung gestellt", "rechnung gestellt", "invoiced", "billed"},
    "geliefert": {"geliefert", "versendet", "versandt", "zugestellt", "ausgeliefert", "delivered", "shipped", "fulfilled"},
    "versendet": {"versendet", "versandt", "verschickt", "shipped", "fulfilled"},
    "erledigt": {"erledigt", "fertig", "abgeschlossen", "done", "completed", "finished"},
    "eingegangen": {"eingegangen", "geliefert", "erhalten", "received"},
    "beauftragt": {"beauftragt", "angenommen", "auftrag erteilt", "zugesagt", "accepted", "won", "gewonnen"},
}


def status_reaches(step_label: str, value) -> bool:
    """Does the status value say that this step has happened? ('abgerechnet' -> berechnet)"""
    v = " ".join(fold(str(value or "")).split())
    return bool(v) and v in {" ".join(fold(x).split()) for x in STEP_STATES.get(fold(step_label), ())}
