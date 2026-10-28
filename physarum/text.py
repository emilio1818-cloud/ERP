"""Text normalisation, similarity and a little German morphology."""
from __future__ import annotations

import re
import unicodedata

_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue", "ı": "i", "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "æ": "ae", "Æ": "Ae", "œ": "oe", "þ": "th", "ŀ": "l"})
_CAMEL = re.compile(r"(?<=[a-zäöüß])(?=[A-ZÄÖÜ])")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")

LEGAL_FORMS = [
    "gmbh & co. kgaa", "gmbh & co. kg", "gmbh & co kg", "gmbh u. co. kg", "ug (haftungsbeschraenkt)",
    "ug (haftungsbeschränkt)", "partg mbb", "gmbh", "mbh", "kgaa", "ag", "kg", "ohg", "gbr", "ug", "e.k.", "e. k.",
    "e.kfm.", "e.v.", "e. v.", "inc.", "inc", "ltd.", "ltd", "llc", "s.a.", "sarl", "b.v.", "se", "& co.", "& co",
    "und co.", "u. co.", "co.",
]
_LEGAL_FOLDED = sorted({l.translate(_FOLD).lower() for l in LEGAL_FORMS}, key=len, reverse=True)
_LEGAL_RE = re.compile(r"(?<![0-9a-z])(" + "|".join(re.escape(x) for x in _LEGAL_FOLDED) + r")(?![0-9a-z])")
_UND_RE = re.compile(r"(?:^|\s)(?:und|u)(?=\s|$)")


def fold(s: str) -> str:
    """Lowercase, umlauts to ae/oe/ue/ss, strip all other diacritics."""
    s = s.translate(_FOLD).lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def tokens(s: str, camel: bool = True) -> list[str]:
    """Folded word tokens. camelCase is split ("customerEmail"), unless camel=False
    (German abbreviations like "MwSt" or "KdNr" must stay whole)."""
    s = str(s)
    if camel:
        s = _CAMEL.sub(" ", s)
    return [t for t in _NON_ALNUM.split(fold(s)) if t]


def slug(s: str) -> str:
    return "_".join(tokens(s)) or "x"


def norm_key(v) -> str:
    """Normalise an identifier for matching: case-insensitive, whitespace-insensitive,
    leading zeros of pure numbers ignored (Excel likes to drop them), 1001.0 == 1001."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip().casefold()
    s = re.sub(r"\s+", "", s)
    if s.isdigit():
        s = s.lstrip("0") or "0"
    return s


_LAST_FIRST = re.compile(r"^\s*([a-z][a-z\-]+(?:\s[a-z][a-z\-]+)?)\s*,\s*([a-z][a-z\-.]+(?:\s[a-z][a-z\-.]+)?)\s*$")
_STREET_WORDS = {"str", "strasse", "weg", "platz", "allee", "ring", "gasse", "damm", "ufer", "chaussee"}


def norm_name(v) -> str:
    """Normalise a company or person name: fold, drop legal forms and punctuation."""
    if v is None:
        return ""
    s = fold(str(v))
    m = _LAST_FIRST.match(s)
    if m and not any(w in _STREET_WORDS for w in m.group(2).replace(".", " ").split()):
        s = f"{m.group(2)} {m.group(1)}"  # "Schulze, Gerda" is "Gerda Schulze"
    s = _LEGAL_RE.sub(" ", s)
    s = s.replace("+", " und ").replace("&", " und ")
    s = _NON_ALNUM.sub(" ", s)
    s = _UND_RE.sub(" ", s)
    return " ".join(s.split())


def jaro_winkler(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    match_dist = max(la, lb) // 2 - 1
    a_flags = [False] * la
    b_flags = [False] * lb
    matches = 0
    for i, ca in enumerate(a):
        lo, hi = max(0, i - match_dist), min(lb, i + match_dist + 1)
        for j in range(lo, hi):
            if not b_flags[j] and b[j] == ca:
                a_flags[i] = b_flags[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    t = 0
    k = 0
    for i in range(la):
        if a_flags[i]:
            while not b_flags[k]:
                k += 1
            if a[i] != b[k]:
                t += 1
            k += 1
    t /= 2
    jaro = (matches / la + matches / lb + (matches - t) / matches) / 3
    prefix = 0
    for ca, cb in zip(a[:4], b[:4]):
        if ca != cb:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def name_similarity(a: str, b: str) -> float:
    """Similarity of two (already normalised) names.

    Tokens are aligned greedily and only count when nearly identical (typos), so
    "bistro krabbenkutter" and "buero krabbenkutter" stay apart while
    "hotel elbblick" and "hotel elbblik" match. Containment of a multi-token name
    in a longer one ("cafe hafenblick" in "cafe hafenblick hamburg") scores high.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    da, db = sorted(_DIGITS.findall(a)), sorted(_DIGITS.findall(b))
    if da != db:
        # "Filiale 1" and "Filiale 10", "Hotel Seeblick 1" and "2" are different places
        return min(0.5 if (da and db) else 0.85, _name_similarity(a, b))
    return _name_similarity(a, b)


_DIGITS = re.compile(r"\d+")


def _name_similarity(a: str, b: str) -> float:
    ta, tb = a.split(), b.split()
    used: set[int] = set()
    matched = 0.0
    for t in sorted(ta, key=len, reverse=True):
        best, bj = 0.0, None
        for j, u in enumerate(tb):
            if j in used:
                continue
            s = 1.0 if t == u else jaro_winkler(t, u)
            if s > best:
                best, bj = s, j
        if bj is not None and best >= 0.88:
            used.add(bj)
            matched += best * (len(t) + len(tb[bj])) / 2
    wa, wb = sum(map(len, ta)), sum(map(len, tb))
    soft_jaccard = matched / max(1e-9, wa + wb - matched)
    contain = matched / max(1e-9, min(wa, wb))
    c_weight = 0.92 if min(len(ta), len(tb)) >= 2 else 0.6
    compact = jaro_winkler(a.replace(" ", ""), b.replace(" ", ""))
    return max(soft_jaccard, c_weight * contain, compact if compact >= 0.97 else 0.0)


# --- German nouns -------------------------------------------------------------------------

_PLURAL_EXCEPTIONS = {
    "kunde": "Kunden", "artikel": "Artikel", "auftrag": "Aufträge", "mitarbeiter": "Mitarbeiter",
    "lieferant": "Lieferanten", "einkauf": "Einkäufe", "vertrag": "Verträge", "projekt": "Projekte",
    "produkt": "Produkte", "kontakt": "Kontakte", "dokument": "Dokumente", "angebot": "Angebote",
    "lieferschein": "Lieferscheine", "beleg": "Belege", "termin": "Termine", "auftragsposition": "Auftragspositionen",
    "e-mail": "E-Mails", "konto": "Konten", "lager": "Lager", "fahrzeug": "Fahrzeuge", "geraet": "Geräte",
    "gerät": "Geräte", "material": "Materialien", "posten": "Posten", "kontobewegung": "Kontobewegungen",
    "maschine": "Maschinen", "wartungsvertrag": "Wartungsverträge", "einsatz": "Einsätze", "auftraggeber": "Auftraggeber",
    "bestand": "Bestände", "dienstleistung": "Dienstleistungen", "objekt": "Objekte", "raum": "Räume",
    "zimmer": "Zimmer", "buchung": "Buchungen", "gast": "Gäste", "patient": "Patienten", "mandant": "Mandanten",
    "kurs": "Kurse", "teilnehmer": "Teilnehmer", "schueler": "Schüler", "mitglied": "Mitglieder",
    "rechnungsposition": "Rechnungspositionen", "position": "Positionen", "order": "Orders", "item": "Items",
    "customer": "Customers", "product": "Products", "invoice": "Invoices", "ticket": "Tickets",
}


def _split_suffix(word: str, suffix_folded: str) -> str | None:
    """Return the stem of `word` if its folded tail equals `suffix_folded` (umlaut-safe)."""
    for i in range(len(word)):
        if fold(word[i:]) == suffix_folded:
            return word[:i]
    return None


def _match_case(template: str, word: str) -> str:
    return word if template[:1].isupper() else word.lower()


def plural_de(singular: str) -> str:
    key = fold(singular)
    if key in _PLURAL_EXCEPTIONS:
        return _match_case(singular, _PLURAL_EXCEPTIONS[key])
    for suffix in sorted(_PLURAL_EXCEPTIONS, key=len, reverse=True):
        if len(suffix) >= 5 and key.endswith(suffix) and key != suffix:
            stem = _split_suffix(singular, suffix)
            if stem:
                return stem + _PLURAL_EXCEPTIONS[suffix].lower()
    low = singular.lower()
    if low.endswith(("ung", "heit", "keit", "schaft", "ion", "ität", "tät")):
        return singular + "en"
    if low.endswith("e"):
        return singular + "n"
    if low.endswith(("er", "el", "en", "chen", "lein")):
        return singular
    if low.endswith("in"):
        return singular + "nen"
    if low.endswith(("s", "x", "z")):
        return singular
    if low.endswith(("a", "i", "o", "u", "y")):
        return singular + "s"
    return singular + "e"


_SINGULAR_EXCEPTIONS = {fold(v): k for k, v in _PLURAL_EXCEPTIONS.items()}


def singular_de(word: str) -> str:
    """Best-effort singular of a German (or English) noun. Returns word unchanged if unsure."""
    key = fold(word)
    if key in _SINGULAR_EXCEPTIONS:
        return _match_case(word, capitalize_first(_SINGULAR_EXCEPTIONS[key]))
    for plural_f in sorted(_SINGULAR_EXCEPTIONS, key=len, reverse=True):
        if len(plural_f) >= 6 and key.endswith(plural_f) and key != plural_f:
            stem = _split_suffix(word, plural_f)
            if stem:
                return stem + _SINGULAR_EXCEPTIONS[plural_f]
    low = word.lower()
    for suf, rep in (("ungen", "ung"), ("heiten", "heit"), ("keiten", "keit"), ("ionen", "ion"),
                     ("schaften", "schaft"), ("innen", "in")):
        if low.endswith(suf):
            return word[: len(word) - len(suf)] + rep
    if low.endswith("ies") and len(low) > 4:
        return word[:-3] + "y"
    if low.endswith("s") and not low.endswith(("ss", "us", "is")) and len(low) > 3:
        return word[:-1]
    return word


def capitalize_first(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def human_join(items: list[str], last: str = "und") -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]
