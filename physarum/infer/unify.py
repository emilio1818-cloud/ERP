"""Unification: observations from different files that describe the same kind of thing
become one type ("Kundenliste.xlsx", "CRM_Export.csv" and the customers pulled out of
the order export are all Kunden).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import lexicon
from ..text import fold, jaro_winkler, singular_de, slug, tokens
from .observe import Col, Obs, clean_stem, display_header

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

    def attr_of(self, o: Obs, col_name: str) -> AttrDraft | None:
        for a in self.attrs:
            for mo, c in a.cols:
                if mo is o and c.name == col_name:
                    return a
        return None


def _norm_header(c: Col) -> str:
    return " ".join(tokens(display_header(c.name)))


def header_sim(a: Col, b: Col) -> float:
    na, nb = _norm_header(a), _norm_header(b)
    if na == nb and na:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    sim = jac * 0.9
    ca, cb = na.replace(" ", ""), nb.replace(" ", "")
    if ca and cb:
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
        sim = max(sim, 0.7)
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
    if h >= 0.75:
        return min(1.0, h + 0.1 * v)
    if v >= 0.5 and h >= 0.25:
        return 0.6 + 0.4 * v
    if v >= 0.8 and a.role == b.role:
        return 0.7
    return h * 0.85


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
    if ka and kb and best < 0.2:
        # both have their own numbers and they do not match: names in them are references
        # ("Kunde" in an order list), not evidence that the records are the same things
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
    decision, reason = "no", ""
    if ident >= 0.5 and cont >= 0.3:
        decision, reason = "merge", why
    elif ident >= 0.3 and cont >= 0.5 and not conflict:
        decision, reason = "merge", why
    elif cont >= 0.8 and sym >= 0.7 and not conflict:
        decision, reason = "merge", "gleicher Aufbau der Spalten"
    elif same_concept and cont >= 0.6:
        decision, reason = "merge", f"beides {lexicon.CONCEPTS[ca]['pl']}, ähnliche Spalten"
    elif (same_concept and cont >= 0.4) or (not conflict and cont >= 0.6 and sym >= 0.4) or \
            (ident >= 0.2 and cont >= 0.3):
        decision, reason = "ask", "ähnliche Spalten" if not same_concept else "gleicher Begriff, teils andere Spalten"
    score = 0.45 * ident + 0.35 * cont + 0.1 * sym + (0.1 if same_concept else 0.0) - (0.15 if conflict else 0.0)
    return dict(decision=decision, reason=reason, score=round(score, 3), cont=round(cont, 2), ident=round(ident, 2),
                pairs=pairs)


def obs_sig(o: Obs) -> str:
    stem = clean_stem(o.label)
    sheet = o.label.split(" › ")[1] if " › " in o.label else ""
    return f"{fold(stem)}|{fold(sheet)}|{fold(o.determinant or '')}"


def unify(observations: list[Obs], decisions: dict | None = None, log: list | None = None,
          ask: list | None = None) -> list[TypeDraft]:
    """Cluster observations into types. `decisions` maps frozenset({sig_a, sig_b}) -> 'same'|'different'."""
    decisions = decisions or {}
    order = sorted(observations, key=lambda o: (o.extracted_from is not None, o.kind_hint == "line", -o.n))
    clusters: list[TypeDraft] = []
    for o in order:
        best, best_sim, best_dec = None, None, "no"
        for t in clusters:
            if any(m.table_id == o.table_id for m in t.members):
                continue  # entities pulled out of one table are different things by construction
            if t.kind == "line" or o.kind_hint == "line":
                if not (t.members[0].kind_hint == "line" and o.kind_hint == "line"):
                    continue
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
    return (o.extracted_from is None, o.n)


def _finish(t: TypeDraft):
    base = [m for m in t.members if m.extracted_from is None]
    by_auth = sorted(t.members, key=_authority, reverse=True)
    concept = None
    for m in sorted(base, key=lambda m: -m.n):
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
        lead_base = next(m for m in sorted(base, key=lambda m: -m.n) if m.concept == concept)
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
        sg = singular_de(stem[:1].upper() + stem[1:])
        t.name, t.plural = sg, stem[:1].upper() + stem[1:] if fold(stem) != fold(sg) else ""
    if not t.plural:
        from ..text import plural_de
        t.plural = plural_de(t.name)
    # kind
    has_date = any(a.kind in ("date", "datetime") for a in t.attrs)
    if lead.kind_hint == "line":
        t.kind = "line"
    elif concept:
        t.kind = lexicon.CONCEPTS[concept]["kind"]
    elif lead.kind_hint == "header" or (has_date and any(a.kind == "money" for a in t.attrs)):
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
                if a is t.key or a.role != role or a.kind != "text":
                    continue
                if any(mo is m for mo, _ in a.cols):
                    t.title = a
                    break
            if t.title:
                break
        if t.title:
            break
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


def _dedupe_names(types: list[TypeDraft]):
    by_name: dict[str, list[TypeDraft]] = {}
    for t in types:
        by_name.setdefault(fold(t.name), []).append(t)
    for group in by_name.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda t: -sum(m.n for m in t.members))
        for t in group[1:]:
            stem = clean_stem(t.members[0].label)
            t.name = f"{t.name} ({stem})"
            t.plural = f"{t.plural} ({stem})"
