"""Unification: observations from different files that describe the same kind of thing
become one type ("Kundenliste.xlsx", "CRM_Export.csv" and the customers pulled out of
the order export are all Kunden).
"""
from __future__ import annotations

import re

from collections import Counter
from dataclasses import dataclass, field

from .. import lexicon
from ..text import fold, jaro_winkler, singular_de, slug, tokens
from .observe import Col, Obs, clean_stem, display_header, says_nothing, telling_key

KIND_GROUP = {"text": "text", "id": "text", "phone": "phone", "email": "email", "url": "url", "zip": "zip",
              "iban": "iban", "number": "num", "money": "num", "percent": "pct", "duration": "num", "date": "date",
              "datetime": "date", "bool": "bool"}
STRONG_ROLES = {"email", "phone", "zip", "city", "street", "iban", "person", "country", "url", "vat_id", "bic"}


@dataclass
class AttrDraft:
    name: str
    kind: str
    role: str | None
    concept: str | None
    cols: list[tuple[Obs, Col]] = field(default_factory=list)
    aid: str | None = None
    slug: str = ""

    @property
    def rep(self) -> Col:
        return self.cols[0][1]


@dataclass
class TypeDraft:
    members: list[Obs]
    attrs: list[AttrDraft] = field(default_factory=list)
    name: str = ""
    plural: str = ""
    concept: str | None = None
    kind: str = "master"
    key: AttrDraft | None = None
    title: AttrDraft | None = None
    tid: str | None = None
    merge_log: list = field(default_factory=list)
    silent: bool = False  # named from its columns: the file's name said nothing
    plain: tuple | None = None  # its name before it had to be told apart from another list's

    def attr_of(self, o: Obs, col_name: str) -> AttrDraft | None:
        for a in self.attrs:
            for mo, c in a.cols:
                if mo is o and c.name == col_name:
                    return a
        return None


def _norm_header(c: Col) -> str:
    return " ".join(tokens(display_header(c.name)))


# words that decorate a header without changing what it holds ("Billable Amount (EUR)" is "Amount")
_DECORATION = {"billable", "abrechenbar", "abrechenbare", "eur", "euro", "chf", "usd", "h", "std", "decimal", "dezimal",
               "in", "hours", "stunden", "netto"}  # "EP netto" is the "EP" of a list that only knows net prices


# milestones said in other words: "erledigt" in last year's sheet is "fertig am" in this year's
_SAME_MILESTONE = {"fertig": "erledigt", "fertiggestellt": "erledigt", "abgeschlossen": "erledigt", "done": "erledigt",
                   "completed": "erledigt", "beendet": "erledigt"}
_DATE_FILLER = {"am", "datum", "date", "on", "at", "bis"}


def header_sim(a: Col, b: Col) -> float:
    na, nb = _norm_header(a), _norm_header(b)
    if na == nb and na:
        return 1.0
    sim = _header_sim(a, b, na, nb)
    # "Baustelle / Objekt": two names for one column – either will do
    alts_a = [x for x in re.split(r"\s*/\s*", display_header(a.name)) if x.strip()]
    alts_b = [x for x in re.split(r"\s*/\s*", display_header(b.name)) if x.strip()]
    if len(alts_a) > 1 or len(alts_b) > 1:
        for x in alts_a:
            for y in alts_b:
                if " ".join(tokens(x)) == " ".join(tokens(y)) and tokens(x):
                    sim = max(sim, 0.9)
    return sim


def _header_sim(a: Col, b: Col, na: str, nb: str) -> float:
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    sim = jac * 0.9
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if small and small < big and (big - small) <= _DECORATION and not small <= _DECORATION:
        sim = max(sim, 0.8)
    ca, cb = na.replace(" ", ""), nb.replace(" ", "")
    if ca and cb and len(ta) == len(tb):
        # spelling variants ("Strasse"/"Straße", "E-Mail"/"Email"), not "Kunde" vs "Kunde seit"
        jw = jaro_winkler(ca, cb)
        if jw >= 0.9:
            sim = max(sim, jw - 0.05)
    if a.role == b.role and a.role in STRONG_ROLES:
        sim = max(sim, 0.85)
    elif a.role == b.role == "name":
        sim = max(sim, 0.75)
    if a.prof.concept and a.prof.concept == b.prof.concept and a.role == b.role:
        sim = max(sim, 0.82)
    if a.role == b.role and a.role in ("id",) and a.prof.pattern and a.prof.pattern == b.prof.pattern:
        # the same scheme of numbers: with letters in it ("A25-001", "A26-001") a scheme of its own
        sim = max(sim, 0.8 if re.search(r"[A-Za-z]", a.prof.pattern) and re.search(r"9", a.prof.pattern) else 0.7)
    if a.kind == b.kind and a.kind in ("money", "quantity", "number"):
        # German compounds name their kind last: "Auftragswert" is a "Wert", "Einzelpreis" a "Preis"
        for x in ta:
            if len(x) >= 4 and any(y != x and len(y) >= len(x) + 3 and y.endswith(x) for y in tb) or \
                    len(x) >= 4 and any(len(y) >= 4 and y != x and len(x) >= len(y) + 3 and x.endswith(y) for y in tb):
                sim = max(sim, 0.75)
    if a.kind in ("date", "datetime") and b.kind in ("date", "datetime"):
        ma = {_SAME_MILESTONE.get(x, x) for x in ta - _DATE_FILLER}
        mb = {_SAME_MILESTONE.get(x, x) for x in tb - _DATE_FILLER}
        if ma and ma == mb:
            sim = max(sim, 0.8)
    return sim


def value_overlap(a: Col, b: Col) -> float:
    sa = {k for k in a.keys if k is not None}
    sb = {k for k in b.keys if k is not None}
    if len(sa) < 2 or len(sb) < 2:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def col_sim(a: Col, b: Col) -> float:
    ga, gb = KIND_GROUP.get(a.kind), KIND_GROUP.get(b.kind)
    if ga != gb:
        return 0.0
    h = header_sim(a, b)
    v = value_overlap(a, b) if ga in ("text", "email", "phone", "zip", "iban") else 0.0
    if ga == "text" and a.role in ("notes",) and b.role in ("notes",):
        h = max(h, 0.7)
    names = ("name", "person")
    if ga == "text" and (a.role in names) != (b.role in names) and v < 0.2 and not (h >= 0.99 and _numbers_inside(a, b)):
        h *= 0.6  # a column of names belongs with names, whatever its header says
    if h >= 0.75:
        return min(1.0, h + 0.1 * v)
    if v >= 0.5 and h >= 0.25:
        return 0.6 + 0.4 * v
    if v >= 0.8 and a.role == b.role:
        return 0.7
    return h * 0.85


def _numbers_inside(a: Col, b: Col) -> bool:
    """"A26-079 Wehmeier" under the same header as "A26-079": the number with a word, not a name."""
    ids, texts = (a, b) if a.role == "id" or a.kind == "id" else (b, a)
    shapes = Counter(_shape(str(v)) for v in ids.values if v is not None and str(v).strip())
    if not shapes:
        return False
    shape, n = shapes.most_common(1)[0]
    if n < 0.7 * sum(shapes.values()) or not any(ch == "9" for ch in shape):
        return False
    vals = [str(v) for v in texts.values if isinstance(v, str)]
    hits = sum(1 for v in vals if any(_shape(tok) == shape for tok in v.split()[:3]))
    return bool(vals) and hits >= 0.5 * len(vals)


def _shape(s: str) -> str:
    """"A26-074" -> "A99-999": the way a number is written, not which one."""
    return "".join("9" if ch.isdigit() else "A" if ch.isalpha() else ch for ch in s.strip())


def match_columns(xs: list[Col], ys: list[Col], threshold: float = 0.62) -> list[tuple[Col, Col, float]]:
    cands = []
    for x in xs:
        for y in ys:
            s = col_sim(x, y)
            if s >= threshold:
                cands.append((s, x, y))
    cands.sort(key=lambda t: -t[0])
    used_x, used_y, out = set(), set(), []
    for s, x, y in cands:
        if id(x) in used_x or id(y) in used_y:
            continue
        used_x.add(id(x))
        used_y.add(id(y))
        out.append((x, y, s))
    return out


def _meaningful(o: Obs) -> list[Col]:
    return [c for c in o.cols if not c.is_constant()]


def _ident_overlap(a: Obs, b: Obs) -> tuple[float, str]:
    best, why = 0.0, ""
    ka, kb = (a.col(a.key) if a.key else None), (b.col(b.key) if b.key else None)
    if ka and kb and KIND_GROUP.get(ka.kind) == KIND_GROUP.get(kb.kind):
        v = value_overlap(ka, kb)
        if v > best:
            best, why = v, f"gleiche Nummern in „{ka.name}“ und „{kb.name}“"
    same_master = bool(a.concept and a.concept == b.concept and lexicon.CONCEPTS[a.concept]["kind"] == "master")
    if ka and kb and best < 0.2 and ((ka.prof.pattern or "") == (kb.prof.pattern or "") or not same_master):
        # both have their own numbers of the same kind and they do not match: names in them are
        # references ("Kunde" in an order list), not evidence that the records are the same things.
        # Numbers of different systems ("101" and "res_101") say nothing either way.
        return best, why
    ta, tb = a.title_col(), b.title_col()
    if ta and tb:
        v = value_overlap(ta, tb)
        if v > best:
            best, why = v, f"gleiche Namen in „{ta.name}“ und „{tb.name}“"
    ea, eb = a.email_col(), b.email_col()
    if ea and eb:
        v = value_overlap(ea, eb)
        if v > best:
            best, why = v, "gleiche E-Mail-Adressen"
    return best, why


def obs_similarity(a: Obs, b: Obs) -> dict:
    ma, mb = _meaningful(a), _meaningful(b)
    pairs = match_columns(ma, mb)
    small = max(1, min(len(ma), len(mb)))
    big = max(1, max(len(ma), len(mb)))
    cont = len(pairs) / small
    sym = len(pairs) / big
    ident, why = _ident_overlap(a, b)
    ca, cb = a.concept, b.concept
    same_concept = ca is not None and ca == cb
    conflict = ca is not None and cb is not None and ca != cb
    pa = {c.prof.concept for c in a.cols if c.prof.concept in ("kunde", "lieferant")}
    pb = {c.prof.concept for c in b.cols if c.prof.concept in ("kunde", "lieferant")}
    if pa and pb and not (pa & pb):
        conflict = True  # invoices *to* customers are not invoices *from* suppliers
        same_concept = False
    # positions with a quantity ("Aufmaß": Menge, EP, GP) name articles; they are not the list of articles
    for x, mx, my in ((a, ma, mb), (b, mb, ma)):
        if x.concept in lexicon.CONCEPTS and lexicon.CONCEPTS[x.concept]["kind"] == "master" and \
                not any(c.role == "quantity" for c in mx) and any(c.role == "quantity" for c in my):
            conflict, same_concept = True, False
    kinds = {lexicon.CONCEPTS[c]["kind"] for c in (ca, cb) if c in lexicon.CONCEPTS}
    # master data next to business cases; or two kinds of business case (bank lines and invoices name
    # the same customers – that makes them related, not the same)
    kind_conflict = conflict and (len(kinds) == 2 or (kinds == {"transaction"} and "kontobewegung" in (ca, cb)))
    for x, y in ((a, b), (b, a)):
        if x.kind_hint == "party" and y.kind_hint != "party" and y.concept in lexicon.CONCEPTS and \
                lexicon.CONCEPTS[y.concept]["kind"] == "transaction" and x.concept != y.concept:
            conflict = kind_conflict = True  # whoever is named in rows is no more bank lines or invoices
            same_concept = False
    decision, reason = "no", ""
    if ident >= 0.5 and cont >= 0.3 and not kind_conflict:
        # (a customer list whose names fill the "Kunde" column of an invoice book is what the
        # invoices refer to, not more invoices; a stock list of the articles is about articles)
        decision, reason = "merge", why
    elif ident >= 0.3 and cont >= 0.5 and not conflict:
        decision, reason = "merge", why
    elif cont >= 0.8 and sym >= 0.7 and not conflict:
        decision, reason = "merge", "gleicher Aufbau der Spalten"
    elif same_concept and cont >= 0.6:
        decision, reason = "merge", f"beides {lexicon.CONCEPTS[ca]['pl']}, ähnliche Spalten"
    elif (same_concept and cont >= 0.4) or (not conflict and cont >= 0.6 and sym >= 0.4) or \
            (ident >= 0.2 and cont >= 0.3 and not conflict):
        # (time sheets name the orders' numbers: that makes them refer to orders, not be orders)
        decision, reason = "ask", "ähnliche Spalten" if not same_concept else "gleicher Begriff, teils andere Spalten"
    score = 0.45 * ident + 0.35 * cont + 0.1 * sym + (0.1 if same_concept else 0.0) - (0.15 if conflict else 0.0)
    return dict(decision=decision, reason=reason, score=round(score, 3), cont=round(cont, 2), ident=round(ident, 2),
                pairs=pairs)


def obs_sig(o: Obs) -> str:
    label = o.sig_label or o.label
    stem = clean_stem(label)
    sheet = label.split(" › ")[1] if " › " in label else ""
    return f"{fold(stem)}|{fold(sheet)}|{fold(o.determinant or '')}"


def unify(observations: list[Obs], decisions: dict | None = None, log: list | None = None,
          ask: list | None = None) -> list[TypeDraft]:
    """Cluster observations into types. `decisions` maps frozenset({sig_a, sig_b}) -> 'same'|'different'."""
    decisions = decisions or {}
    # content decides the order, never the order of arrival (ties by name and shape)
    order = sorted(observations, key=lambda o: (o.extracted_from is not None, o.kind_hint == "line", -o.n,
                                                -len(o.cols), fold(o.sig_label or o.label), o.determinant or ""))
    clusters: list[TypeDraft] = []
    home: dict[str, TypeDraft] = {}  # obs id -> its cluster, to find the parents of lines

    def parent_cluster(o: Obs):
        for _col, target in o.links:
            if target in home and home[target] is not None:
                tgt = home[target]
                if tgt.members and tgt.members[0].kind_hint != "line" and tgt.members[0].kind_hint != "party":
                    return id(tgt)
        return None

    for o in order:
        best, best_sim, best_dec = None, None, "no"
        for t in clusters:
            if any(m.table_id == o.table_id for m in t.members):
                continue  # entities pulled out of one table are different things by construction
            if t.kind == "line" or o.kind_hint == "line":
                if not (t.members[0].kind_hint == "line" and o.kind_hint == "line"):
                    continue
                # order lines and invoice lines are different things: lines merge only under the same parent type
                if parent_cluster(t.members[0]) != parent_cluster(o):
                    continue
            if any(decisions.get(frozenset((obs_sig(m), obs_sig(o)))) == "different" for m in t.members):
                continue  # "keep them apart" holds for the whole list, not just for one of its files
            for m in t.members:
                sim = obs_similarity(m, o)
                d = decisions.get(frozenset((obs_sig(m), obs_sig(o))))
                dec = sim["decision"]
                if d == "same":
                    dec = "merge"
                elif d == "different":
                    dec = "no"
                rank = {"merge": 2, "ask": 1, "no": 0}[dec]
                if best is None or (rank, sim["score"]) > ({"merge": 2, "ask": 1, "no": 0}[best_dec], best_sim["score"]):
                    best, best_sim, best_dec = (t, m), sim, dec
        if best is not None and best_dec == "merge":
            t, m = best
            _add_member(t, o)
            home[o.oid] = t
            t.merge_log.append(dict(obs=o.label, into=m.label, reason=best_sim["reason"], score=best_sim["score"]))
            if log is not None:
                log.append(dict(kind="merge", a=m.label, a_name=m.name_hint, b=o.label, b_name=o.name_hint,
                                reason=best_sim["reason"]))
            continue
        if best is not None and best_dec == "ask" and ask is not None:
            t, m = best
            ask.append(dict(a=m, b=o, sim=best_sim, sig=frozenset((obs_sig(m), obs_sig(o)))))
        t = TypeDraft(members=[])
        _add_member(t, o)
        clusters.append(t)
        home[o.oid] = t
    for t in clusters:
        _finish(t)
    _dedupe_names(clusters)
    return clusters


def _add_member(t: TypeDraft, o: Obs):
    t.members.append(o)
    if not t.attrs:
        for c in o.cols:
            t.attrs.append(AttrDraft(name=display_header(c.name), kind=c.kind, role=c.role, concept=c.prof.concept,
                                     cols=[(o, c)]))
        return
    reps = [a.rep for a in t.attrs]
    pairs = match_columns(reps, o.cols, threshold=0.6)
    mapped = {}
    for rep, c, _s in pairs:
        mapped[id(c)] = rep
    for c in o.cols:
        rep = mapped.get(id(c))
        if rep is not None:
            a = next(a for a in t.attrs if a.rep is rep)
            a.cols.append((o, c))
        else:
            t.attrs.append(AttrDraft(name=display_header(c.name), kind=c.kind, role=c.role, concept=c.prof.concept,
                                     cols=[(o, c)]))


def _authority(o: Obs) -> tuple:
    return (o.extracted_from is None, o.n, len(o.cols), _rev(fold(o.sig_label or o.label)))


def _rev(s: str) -> tuple:
    """Sort key that orders strings descending inside a reverse=True sort (alphabetical wins)."""
    return tuple(-ord(ch) for ch in s)


def _finish(t: TypeDraft):
    base = [m for m in t.members if m.extracted_from is None]
    by_auth = sorted(t.members, key=_authority, reverse=True)
    concept = None
    for m in sorted(base, key=lambda m: (-m.n, -len(m.cols), fold(m.sig_label or m.label))):
        if m.concept and m.kind_hint != "line":
            concept = m.concept
            break
    if concept is None:
        for m in by_auth:
            if m.concept and m.kind_hint != "line":
                concept = m.concept
                break
    t.concept = concept
    lead = by_auth[0]
    hint_member = next((m for m in by_auth if m.name_hint), None)
    if lead.kind_hint == "line" and lead.name_hint:
        t.name, t.plural = lead.name_hint[0], lead.name_hint[1] or ""
    elif concept and base and any(m.concept == concept for m in base):
        sg, pl, _ = lexicon.concept_names(concept)
        lead_base = next(m for m in sorted(base, key=lambda m: (-m.n, -len(m.cols), fold(m.sig_label or m.label)))
                         if m.concept == concept)
        spec_name = lexicon.specific_name(clean_stem(lead_base.label), concept)
        if spec_name:
            sg, pl = spec_name
        q = next((m.qualifier for m in base if m.concept == concept and m.qualifier), None)
        t.name, t.plural = (f"{q}-{sg}", f"{q}-{pl}") if q else (sg, pl)
    elif hint_member:
        t.name, t.plural = hint_member.name_hint[0], hint_member.name_hint[1] or ""
    elif concept:
        sg, pl, _ = lexicon.concept_names(concept)
        t.name, t.plural = sg, pl
    else:
        stem = clean_stem(lead.label)
        told = telling_key(lead) if says_nothing(lead.label) else None
        if says_nothing(lead.label):
            t.silent = True
            # "export (5).csv" with a column "Beleg-Nr": a list of "Belege"; without one, the file's own name
            stem = re.sub(r"(?i)[\s.\-_]*(nr|no|nummer|number|id)\.?$", "", display_header(told.name)).strip() \
                if told else lead.label.split(" › ")[0]
        sheet = lead.label.split(" › ", 1)[1].strip() if " › " in lead.label else ""
        if sheet and not re.match(r"^(tabelle|sheet|blatt|table|liste)\s*\d*$", fold(sheet)) and \
                len(sheet) <= 40 and not any(ch.isdigit() for ch in sheet):
            stem = sheet  # "Fuhrpark_Werkzeug › Fahrzeuge": the sheet says what its rows are
        from ..text import plural_de, plural_is_known
        if re.search(r"\s(\+|&|und)\s", stem):
            # "Werkzeug + Geräte": one of them is a "Gerät", the list keeps its name
            last = stem.split()[-1]
            t.name, t.plural = singular_de(last[:1].upper() + last[1:]), stem
        else:
            sg = singular_de(stem[:1].upper() + stem[1:])
            # a file name that cannot be made singular and has no regular plural ("Steinbach", "LIESMICH")
            # is not given an invented ending
            if fold(stem) != fold(sg):
                t.name, t.plural = sg, stem[:1].upper() + stem[1:]
            else:
                t.name, t.plural = sg, plural_de(sg) if plural_is_known(sg) or told else sg
    from ..text import plural_de
    if not t.plural:
        t.plural = plural_de(t.name)
    elif t.plural != plural_de(t.name) and fold(plural_de(t.name)) == fold(t.plural):
        t.plural = plural_de(t.name)  # file names spell "Wartungsvertraege": the list says "Wartungsverträge"
    # kind
    has_date = any(a.kind in ("date", "datetime") for a in t.attrs)
    tc = lead.title_col()
    # master data lists each thing once; a list whose names repeat day after day records events
    repeats = tc is not None and tc.filled >= 10 and tc.distinct / tc.filled < 0.6
    if lead.kind_hint == "line":
        t.kind = "line"
    elif concept:
        t.kind = lexicon.CONCEPTS[concept]["kind"]
    elif lead.kind_hint == "header" or (has_date and any(a.kind == "money" for a in t.attrs)) or \
            (has_date and (repeats or any(a.kind == "time" for a in t.attrs))):
        t.kind = "transaction"
    else:
        t.kind = "master"
    if t.kind == "master" and lead.kind_hint == "header":
        t.kind = "transaction"
    # attribute names: from the most authoritative member that has the column
    for a in t.attrs:
        a.cols.sort(key=lambda mc: _authority(mc[0]), reverse=True)
        a.name = display_header(a.cols[0][1].name)
        kinds = {c.kind for _, c in a.cols}
        if kinds == {"date", "datetime"}:
            a.kind = "datetime"
        else:
            a.kind = a.cols[0][1].kind
        a.role = a.cols[0][1].role
        a.concept = a.cols[0][1].prof.concept
    # key and title
    t.key = None
    for m in by_auth:
        if m.key:
            a = t.attr_of(m, m.key)
            if a is not None and a.kind in ("id", "email", "text"):
                t.key = a
                break
    t.title = None
    for role in ("name", "person"):
        for m in by_auth:
            for a in t.attrs:
                if a is t.key or a.role != role or a.kind != "text" or lexicon.header_role(a.name) == "id":
                    continue  # "Serien-Nr." with odd values is still a number, not what the thing is called
                if any(mo is m for mo, _ in a.cols):
                    t.title = a
                    break
            if t.title:
                break
        if t.title:
            break
    if t.title is None and t.kind == "master":
        # "Gerät", "Fahrzeug": the first column that describes each row in its own words
        t.title = next((a for a in t.attrs if a is not t.key and a.kind == "text" and a.role in (None, "category")
                        and lexicon.header_role(a.name) != "id"
                        and all(c.distinct >= 0.8 * max(c.filled, 1) and c.filled >= 0.8 * mo.n for mo, c in a.cols)),
                       None)
    for a in t.attrs:
        # an identifier hiding under a generic header ("Name" holding #1001 in shop exports)
        if a.kind == "id" and fold(a.name) in ("name", "bezeichnung", "titel", "title", "spalte 1"):
            a.name = "Nummer"
    seen = {}
    for a in t.attrs:
        base_name = a.name
        n = seen.get(fold(base_name), 0)
        seen[fold(base_name)] = n + 1
        if n:
            a.name = f"{base_name} ({n + 1})"
        a.slug = slug(a.name)


def _nested_parts(label: str) -> list[str]:
    """The path inside a nested export: 'export_2026-09-15.tickets.time_entries' -> ['tickets', 'time_entries']."""
    import re as _re
    stem = label.split(" › ")[0]
    parts = stem.split(".")
    out = []
    for p in reversed(parts[1:]):
        if not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{2,}", p) or p.isdigit():
            break
        out.insert(0, p)
    return out


def _dedupe_names(types: list[TypeDraft]):
    by_name: dict[str, list[TypeDraft]] = {}
    for t in types:
        by_name.setdefault(fold(t.name), []).append(t)
    def depth(t: TypeDraft) -> int:  # "export.tickets.time_entries" lies deeper than "export.tickets"
        return min(len(_nested_parts(m.sig_label or m.label)) for m in t.members)

    for group in by_name.values():
        if len(group) < 2:
            continue
        # the main list keeps the plain name; a list nested inside another never takes it, even
        # when a new delivery makes it longer
        group.sort(key=lambda t: (all(m.extracted_from for m in t.members), depth(t), -sum(m.n for m in t.members),
                                  min(fold(m.sig_label or m.label) for m in t.members)))
        for i, t in enumerate(group[1:], start=2):
            t.plain = (t.name, t.plural)
            label = t.members[0].sig_label or t.members[0].label
            parts = _nested_parts(label)
            parent = lexicon.concept_of(parts[-2]) if len(parts) >= 2 else None
            if parent:
                pl = lexicon.CONCEPTS[parent]["pl"]
                t.name, t.plural = f"{t.name} ({pl})", f"{t.plural} ({pl})"  # "Zeiteinträge (Tickets)"
                continue
            stem = clean_stem(label)
            if fold(stem) in (fold(t.name), fold(t.plural)) or not stem:
                # "Rechnungen_2024" next to "Rechnungen": the year tells them apart, not the word
                import re as _re
                y = _re.search(r"(?:19|20)\d\d", label)
                stem = y.group(0) if y else f"Liste {i}"
            t.name = f"{t.name} ({stem})"
            t.plural = f"{t.plural} ({stem})"
