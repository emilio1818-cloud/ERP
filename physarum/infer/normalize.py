"""Normalisation by compression: pull embedded entities out of flat tables.

A flat export repeats the same customer name and address on every order row. If a
column X determines other columns Y (a functional dependency X -> Y, tolerant to typos
and to Shopify-style "only the first line is filled"), the Y values can be stored once
per X instead of once per row. Extraction happens only when it pays for itself:

    savings = sum_Y (n - g) * bits(Y)        (redundancy removed)
    cost    = TYPE_COST + g * bits(X)        (a new kind of thing + its keys)

TYPE_COST is the cognitive price of one more concept in the user's ERP. This is the
minimum-description-length principle applied to ERP design.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .. import lexicon
from ..text import fold, name_similarity, plural_de, singular_de, slug, tokens
from ..values import Profile
from .observe import ENTITY_ROLES, NEVER_DETERMINANT, SILENT_HEADERS, Col, Obs, display_header, heading_name, pick_key

TYPE_COST = 64.0   # bits; small on purpose: a visible header/line structure is worth a concept
CONSISTENCY = 0.93
MIN_GROUP_SIZE = 1.3
TRANSACTION_FACTS = {"money", "quantity", "date", "due", "percent", "number", "status", "flag", "duration"}
KEY_RANK = {"id": 3, "email": 2}


def _groups(col: Col) -> dict[str, list[int]]:
    g: dict[str, list[int]] = defaultdict(list)
    for i, k in enumerate(col.keys):
        if k is not None:
            g[k].append(i)
    return g


def depends(groups: dict[str, list[int]], col: Col, n_groups_total: int) -> tuple[bool | None, float]:
    """Is `col` (almost) functionally determined by the grouping?

    Base-rate aware: a column that is "bezahlt" in 90 % of all rows looks consistent
    inside any grouping. We require the grouping to remove most of the disagreement
    that exists without it.
    """
    name_like = col.kind == "text" and col.role in ("name", "person", "street", "city")
    present_n = sum(1 for k in col.keys if k is not None)
    budget = max(1.0, (1 - CONSISTENCY) * present_n)  # disagreement we can afford before giving up
    total = agree = multi = 0
    filled_groups = 0
    for idxs in groups.values():
        vals = [col.keys[i] for i in idxs if col.keys[i] is not None]
        if vals:
            filled_groups += 1
        if len(vals) < 2:
            continue
        multi += 1
        cnt = Counter(vals)
        mode, mc = cnt.most_common(1)[0]
        if name_like and mc < len(vals) and len(cnt) <= 3:
            # a few spelling variants of one name ("Cafe"/"Café") still agree
            mc = sum(c for v, c in cnt.items() if v == mode or _similar(v, mode))
        total += len(vals)
        agree += mc
        if total - agree > budget:
            return False, agree / total  # clearly not a dependency: stop early
    if multi == 0:
        # header fields filled only on the first row of each group (shop exports); a rare one
        # ("Cancelled at" on one order in seventy) is None: the caller sees where it stands
        if col.filled > 1.05 * n_groups_total:
            return False, 0.0
        if filled_groups >= 0.5 * n_groups_total:
            return True, 1.0
        return (None, 1.0) if filled_groups >= 2 else (False, 0.0)
    cons = agree / total
    present = [k for k in col.keys if k is not None]
    base = Counter(present).most_common(1)[0][1] / len(present) if present else 1.0
    err_group, err_base = 1.0 - cons, 1.0 - base
    ok = cons >= CONSISTENCY and err_group <= max(0.015, 0.3 * err_base)
    return ok, cons


_SIM_CACHE: dict[tuple[str, str], bool] = {}


def _similar(a: str, b: str) -> bool:
    k = (a, b) if a <= b else (b, a)
    r = _SIM_CACHE.get(k)
    if r is None:
        if len(_SIM_CACHE) > 200000:
            _SIM_CACHE.clear()
        r = _SIM_CACHE[k] = name_similarity(a, b) >= 0.88
    return r


def _mode_value(col: Col, idxs: list[int]):
    vals = [(col.keys[i], col.values[i]) for i in idxs if col.keys[i] is not None]
    if not vals:
        return None, None
    kc = Counter(k for k, _ in vals)
    mk = kc.most_common(1)[0][0]
    originals = Counter(str(v) for k, v in vals if k == mk)
    best = originals.most_common(1)[0][0]
    for k, v in vals:
        if k == mk and str(v) == best:
            return k, v
    return mk, vals[0][1]


_EVENT_CONCEPTS = {"zeiteintrag", "stundenzettel", "zeiterfassung"}


def candidate_extractions(o: Obs) -> list[dict]:
    if (o.concept or o.file_concept) == "kontobewegung":
        # whoever paid or was paid – customers, suppliers, staff, the tax office – is no kind of
        # thing of its own; the names are matched against the firm's lists instead
        return []
    link_cols = {c for c, _ in o.links}
    own = o.col(o.key) if o.key else None
    own_concept = own.prof.concept if own is not None and own.distinct >= 0.95 * max(own.filled, 1) else None
    out = []
    for x in o.cols:
        if x.name in link_cols or x.name == o.key and o.n == x.filled == x.distinct:
            continue
        if own_concept and x is not own and x.prof.concept == own_concept:
            continue  # "Projekt" next to a unique "Projekt-Nr.": the rows are these things themselves
        if x.role in NEVER_DETERMINANT or (x.role not in ENTITY_ROLES and x.kind != "id"):
            continue
        if x.kind not in ("id", "text", "email"):
            continue
        filled = x.filled
        if filled < 0.6 * o.n or filled < 4:
            continue
        groups = _groups(x)
        g = len(groups)
        if g < 2 or filled / g < MIN_GROUP_SIZE:
            continue
        transactional = o.kind_hint in ("line", "header") or any(
            c.kind in ("date", "datetime") or c.role == "quantity" for c in o.cols)
        party = not _is_header(o, x, [c for c in o.cols if c is not x], groups)
        deps, rare = [], []
        for y in o.cols:
            if y is x or y.name in link_cols or y.is_constant():
                continue
            if party and transactional and y.role in TRANSACTION_FACTS:
                continue  # the price at the time of sale is a fact of the sale
            if party and y.prof.concept and y.prof.concept != x.prof.concept and \
                    lexicon.CONCEPTS[y.prof.concept]["kind"] == "transaction":
                continue  # the project a ticket is about belongs to the ticket, not to the customer
            ok, cons = depends(groups, y, g)
            if ok and y.kind != "id" and y.origin != x.origin and _inside(x, y):
                continue  # "Unterhaltsreinigung lt. Vertrag 01/2026" and "01/2026": part of the words, not of a thing
            if ok:
                deps.append((y, cons))
            elif ok is None:
                rare.append(y)
        # a rare value that stands only where the header stands belongs to the header (the header: the
        # order's fields, filled on its first line, not on every line)
        heads = [y for y, _ in deps if sum(1 for k in y.keys if k is not None) < 0.9 * filled]
        head_rows = {i for y in heads for i, k in enumerate(y.keys) if k is not None}
        if heads:
            deps += [(y, 1.0) for y in rare if all(i in head_rows for i, k in enumerate(y.keys) if k is not None)]
        if not deps:
            continue
        dep_cols = [y for y, _ in deps]
        if not any(y.role not in lexicon.ADDRESS_ROLES and y.role != "id" for y in dep_cols):
            continue  # an IBAN per payee is not a new kind of thing
        if (o.concept or o.file_concept) in _EVENT_CONCEPTS and not any(
                y.role in ("email", "person") or (y.prof.concept and lexicon.CONCEPTS[y.prof.concept]["kind"] == "master")
                or y.origin == x.origin  # "P-2026-031 Website-Relaunch": the project's number and its name
                for y in dep_cols):
            continue  # a time sheet's site and activity describe the day, not the order they refer to
        if x.kind == "email" and not any(y.role in ("name", "person") for y in dep_cols):
            continue
        n_x = filled
        savings = sum((n_x - g) * y.bits() for y in dep_cols)
        cost = TYPE_COST + g * x.bits()
        net = savings - cost
        score = net * (1.15 if x.kind == "id" else 1.0) * (1.1 if x.prof.concept else 1.0)
        out.append(dict(x=x, deps=dep_cols, groups=groups, g=g, savings=savings, cost=cost, net=net, score=score,
                        consistency={y.name: c for y, c in deps}))
    every = out
    out = sorted((e for e in out if e["net"] > 0), key=lambda e: -e["score"])
    if out:
        # a chain: the object's number determines its customer's number, and that one the customer's name and
        # terms – those belong to the customer (third normal form), the object only points to it; what the
        # object's columns save pays for the customer, however few rows there are
        best, names = out[0], lambda cols: {c.name for c in cols}
        for e in every:
            rest = names(best["deps"]) - {e["x"].name}
            if e is not best and e["x"].kind == "id" and e["x"].name in names(best["deps"]) and \
                    best["x"].name not in names(e["deps"]) and rest and len(rest & names(e["deps"])) >= 0.8 * len(rest):
                if e in out:
                    out.remove(e)
                out.insert(0, e)
                break
    if len(out) > 1:
        best = out[0]
        for e in out[1:]:
            # same entity seen through a better key (email instead of name, number instead of name)
            if e["score"] >= 0.8 * best["score"] and best["x"] in e["deps"] and e["x"] in best["deps"] and \
                    KEY_RANK.get(e["x"].kind, 1) > KEY_RANK.get(best["x"].kind, 1):
                out.remove(e)
                out.insert(0, e)
                break
    return out


def _inside(x: Col, y: Col) -> bool:
    """On most rows the dependent's value stands written in the determinant's own text."""
    pairs = [(fold(str(a)), fold(str(b))) for a, b, k in zip(x.values, y.values, y.keys) if k is not None and a is not None]
    return len(pairs) >= 4 and sum(1 for a, b in pairs if b and b in a) >= 0.8 * len(pairs)


def _own_events(o: Obs, x: Col, groups: dict[str, list[int]] | None) -> bool:
    """Rows that each happened on their own day (time entries of a project, bookings of an order)
    are events that refer to X – not the lines of a document X."""
    if not groups:
        return False
    multi = [idxs for idxs in groups.values() if len(idxs) >= 2]
    if not multi:
        return False
    for c in o.cols:
        if c is x or c.kind not in ("date", "datetime") or c.filled < 0.5 * o.n:
            continue
        varied = sum(1 for idxs in multi if len({c.keys[i] for i in idxs if c.keys[i] is not None}) > 1)
        if varied >= 0.3 * len(multi):
            return True
    return False


def _is_header(o: Obs, x: Col, deps: list[Col], groups: dict[str, list[int]] | None = None) -> bool:
    if _own_events(o, x, groups):
        return False
    if x.prof.concept and lexicon.CONCEPTS[x.prof.concept]["kind"] == "transaction":
        return True
    has_date = any(y.kind in ("date", "datetime") for y in deps)
    if x.prof.concept and lexicon.CONCEPTS[x.prof.concept]["kind"] == "master":
        return False
    if has_date and x.kind == "id":
        return True
    if o.file_concept and lexicon.CONCEPTS[o.file_concept]["kind"] == "transaction" and has_date:
        return True
    return False


def _people(c: Col | None) -> bool:
    vals = [v for v in c.values if isinstance(v, str)][:300] if c is not None else []
    return bool(vals) and sum(1 for v in vals if lexicon.looks_like_person(v)) >= 0.6 * len(vals)


def _party_concept(o: Obs, x: Col, deps: list[Col]) -> str | None:
    cols = [x] + deps
    title = next((y for y in cols if y.kind == "text" and y.role in ("name", "person")), None)
    org = next((y for y in cols if y is not title and y.kind == "text" and y.role == "name" and not _people(y)), None)
    if title is not None and (title.role == "person" or _people(title)) and org is not None and \
            any(y.kind == "email" for y in cols):
        return "kontakt"  # people with an e-mail address who belong to a firm: contacts, whoever exported them
    if x.prof.concept:
        return x.prof.concept
    vals = [str(v) for v in x.values if v not in (None, "")]
    if heading_name(x.name) and any(y.kind == "id" and y.prof.concept for y in deps) and vals and \
            sum(any(ch.isdigit() for ch in v) for v in vals) >= 0.8 * len(vals):
        return None  # codes ("LP-TB 412") with the owner's number beside them: plates, not customers
    for y in deps:
        if y.role in ("name", "person") and y.prof.concept:
            return y.prof.concept
    base = o.concept or o.file_concept
    if base and lexicon.CONCEPTS[base].get("party"):
        return lexicon.CONCEPTS[base]["party"]
    return None


def extract(o: Obs, e: dict) -> tuple[Obs, Obs]:
    x: Col = e["x"]
    deps: list[Col] = e["deps"]
    groups: dict[str, list[int]] = e["groups"]
    order = sorted(groups, key=lambda k: min(groups[k]))
    header = _is_header(o, x, deps, groups)
    pcols = []
    for c in [x] + deps:
        keys, vals = [], []
        for k in order:
            mk, mv = _mode_value(c, groups[k])
            keys.append(mk)
            vals.append(mv)
        prof = _restat(c.prof, vals, keys)
        pcols.append(Col(name=c.name, prof=prof, values=vals, keys=keys, origin=c.origin))
    prov = [sorted({tl for i in groups[k] for tl in o.prov[i]}) for k in order]
    parent = Obs(oid=f"{o.oid}/{slug(x.name)}", table_id=o.table_id, label=o.label, file_concept=o.file_concept,
                 qualifier=o.qualifier, cols=pcols, prov=prov, n=len(order), key=x.name, determinant=x.name,
                 extracted_from=o.oid, source_id=o.source_id, asof=o.asof, tables=o.tables, sig_label=o.sig_label)
    dep_names = {c.name for c in deps}
    rest_cols = [c for c in o.cols if c.name not in dep_names]
    # rows without a value in X must not lose what they say: the name goes into the link
    # column (it is resolved by name later), everything else is kept as a residual column
    null_rows = [i for i, k in enumerate(x.keys) if k is None]
    if null_rows:
        null_set = set(null_rows)
        title_dep = next((y for y in deps if y.kind == "text" and y.role in ("name", "person")), None)
        if title_dep is not None:
            xv, xk = list(x.values), list(x.keys)
            for i in null_rows:
                if title_dep.values[i] is not None:
                    xv[i] = title_dep.values[i]
                    xk[i] = title_dep.keys[i]
            nx = Col(name=x.name, prof=x.prof, values=xv, keys=xk, origin=x.origin)
            rest_cols = [nx if c is x else c for c in rest_cols]
        for y in deps:
            if y is title_dep:
                continue
            vals = [y.values[i] if i in null_set else None for i in range(o.n)]
            keys = [y.keys[i] if i in null_set else None for i in range(o.n)]
            if any(v is not None for v in vals):
                rest_cols.append(Col(name=y.name, prof=_restat(y.prof, vals, keys), values=vals, keys=keys,
                                     origin=y.origin, residual=True))
    rest = Obs(oid=o.oid, table_id=o.table_id, label=o.label, file_concept=o.file_concept, qualifier=o.qualifier,
               cols=rest_cols, prov=o.prov, n=o.n, key=None,
               determinant=o.determinant, extracted_from=o.extracted_from, kind_hint=o.kind_hint,
               links=list(o.links) + [(x.name, parent.oid)], name_hint=o.name_hint, concept=o.concept,
               source_id=o.source_id, asof=o.asof, tables=o.tables, sig_label=o.sig_label)
    rest.key = pick_key(rest)
    if header:
        concept = x.prof.concept or o.concept or o.file_concept
        if concept and lexicon.CONCEPTS[concept]["kind"] != "transaction" and o.file_concept and \
                lexicon.CONCEPTS[o.file_concept]["kind"] == "transaction":
            concept = o.file_concept
        parent.kind_hint = "header"
        parent.concept = concept
        parent.links = []
        if concept:
            sg, pl, stem = lexicon.concept_names(concept)
        elif " ".join(tokens(x.name)) in SILENT_HEADERS:
            sg, pl, stem = "Beleg", "Belege", "Beleg"  # Shopify calls the order number "Name"
        else:
            word = heading_name(x.name)
            sg = singular_de(word[:1].upper() + word[1:]) if word else singular_de(display_header(x.name))
            pl, stem = (plural_de(sg) if word else None), sg
        q = o.qualifier + "-" if o.qualifier else ""
        unnamed = lexicon.is_unnamed(x.name) and not concept  # "Spalte 1" names nothing: the lists say what they are
        parent.name_hint = None if unnamed else (q + sg, (q + pl) if pl else None)
        rest.kind_hint = "line"
        rest.concept = None
        rest.name_hint = None if unnamed else (f"{q}{stem}position", f"{q}{stem}positionen")
    else:
        concept = _party_concept(o, x, deps)
        parent.kind_hint = "party"
        parent.concept = concept
        if concept:
            sg, pl, _stem = lexicon.concept_names(concept)
            parent.name_hint = (sg, pl)
        else:
            word = heading_name(x.name)
            sg = singular_de(word[:1].upper() + word[1:]) if word else singular_de(display_header(x.name))
            parent.name_hint = (sg, plural_de(sg) if word else None)
    parent.label = f"{o.label}"
    return parent, rest


def _restat(prof: Profile, values: list, keys: list) -> Profile:
    p = Profile(name=prof.name, kind=prof.kind, role=prof.role, concept=prof.concept, locale=prof.locale,
                date_order=prof.date_order, currency=prof.currency, milestone=prof.milestone, integer=prof.integer,
                pattern=prof.pattern, pattern_share=prof.pattern_share)
    p.values = values
    p.keys = keys
    p.n = len(values)
    p.filled = sum(1 for k in keys if k is not None)
    cnt = Counter(k for k in keys if k is not None)
    p.distinct = len(cnt)
    from ..values import _entropy
    p.entropy = _entropy(cnt)
    first = {}
    for k, v in zip(keys, values):
        if k is not None and k not in first:
            first[k] = v
    p.top = [(first[k], c) for k, c in cnt.most_common(8)]
    present = [v for v in values if v is not None]
    p.avg_len = sum(len(str(v)) for v in present) / len(present) if present else 0.0
    if prof.enum is not None:
        p.enum = [v for v, _ in Counter(v for v in values if v is not None).most_common()]
    return p


def normalize(o: Obs, log: list | None = None) -> list[Obs]:
    """Split one observation into its entities (header, lines, parties, articles ...)."""
    out, queue = [], [o]
    guard = 0
    while queue and guard < 20:
        guard += 1
        cur = queue.pop(0)
        cands = candidate_extractions(cur)
        if not cands:
            out.append(cur)
            continue
        e = cands[0]
        parent, rest = extract(cur, e)
        if log is not None:
            log.append(dict(kind="extract", table=cur.label, determinant=e["x"].name,
                            deps=[c.name for c in e["deps"]], groups=e["g"], rows=cur.n,
                            savings=round(e["savings"]), cost=round(e["cost"]),
                            name=parent.name_hint[0] if parent.name_hint else e["x"].name,
                            header=parent.kind_hint == "header"))
        queue.append(parent)
        queue.append(rest)
    out.extend(queue)
    return out
