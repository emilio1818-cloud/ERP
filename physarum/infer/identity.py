"""Identity: which rows from which files are the same real-world thing?

Exact identity (same number, same e-mail, same normalised name without contradicting
numbers) is applied directly and logged. Similar-but-not-equal records (typos, legal
forms, "Cafe" vs "Café") are only merged automatically when the evidence is strong; the
uncertain band becomes a question. Two records with different customer numbers are
never merged silently.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .. import lexicon
from ..text import fold, name_similarity, norm_key, norm_name, norm_street, tokens
from .observe import Obs
from .unify import TypeDraft

FREEMAIL = {"gmx.de", "gmx.net", "web.de", "gmail.com", "googlemail.com", "t-online.de", "posteo.de",
            "mailbox.org", "outlook.com", "hotmail.com", "hotmail.de", "yahoo.com", "yahoo.de", "icloud.com",
            "me.com", "aol.com", "freenet.de", "arcor.de", "live.de", "live.com", "online.de", "email.de"}


@dataclass
class Proto:
    member: Obs
    idx: int
    values: dict
    keys: dict
    prov: list
    priority: tuple


@dataclass
class Group:
    protos: list[Proto]
    idents: set = field(default_factory=set)
    values: dict = field(default_factory=dict)
    prov: dict = field(default_factory=dict)       # aid -> [(table_id, line)]
    alts: dict = field(default_factory=dict)       # aid -> [other values]
    lines: list = field(default_factory=list)      # all (table_id, line)
    merges: list = field(default_factory=list)     # explanations for merged identities
    fuzzy: bool = False
    vanished: str | None = None                    # the newest version of its list no longer has it
    implied: list | None = None                    # in no list of its own: named by these ([plural, count])

    def first(self, aid):
        return self.values.get(aid)


class UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)
        return min(ra, rb)


def build_protos(t: TypeDraft) -> list[Proto]:
    protos = []
    for m in t.members:
        colmap = {}
        for a in t.attrs:
            for mo, c in a.cols:
                if mo is m:
                    colmap[c.name] = a
        prio = (m.extracted_from is None, m.asof or "", m.source_id)  # master lists first, then the most recent
        for i in range(m.n):
            vals, keys = {}, {}
            for c in m.cols:
                a = colmap.get(c.name)
                if a is None:
                    continue
                v = c.values[i]
                if v is None or (isinstance(v, str) and not v.strip()):
                    continue
                vals[a.aid] = v
                keys[a.aid] = c.keys[i]
            protos.append(Proto(m, i, vals, keys, list(m.prov[i]), prio))
    return protos


def _key_shape(k: str) -> str:
    out = []
    for ch in str(k):
        out.append("9" if ch.isdigit() else "A" if ch.isalpha() else ch)
    return "".join(out)


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def _content_hash(p: Proto) -> str:
    items = sorted((k, str(v)) for k, v in p.values.items())
    return hashlib.sha1(repr(items).encode()).hexdigest()[:16]


def resolve(t: TypeDraft, protos: list[Proto], decisions: dict | None = None,
            questions: list | None = None, log: list | None = None, stale: dict | None = None) -> list[Group]:
    """`stale`: rows of older versions that the newest version of their list no longer contains,
    (table id, line) -> that version's file. A thing found elsewhere too has moved (a project from
    "Aktiv" to "Abgeschlossen"): its old row no longer speaks. A thing found nowhere else is kept
    and marked – deleted in the other program?"""
    decisions = decisions or {}
    n = len(protos)
    uf = UF(n)
    key_aid = t.key.aid if t.key else None
    email_aids = [a.aid for a in t.attrs if a.kind == "email"]
    title_aid = t.title.aid if t.title else None
    master = t.kind == "master"
    root_keys: dict[int, set] = defaultdict(set)
    root_mails: dict[int, set] = defaultdict(set)
    for i, p in enumerate(protos):
        if key_aid and p.keys.get(key_aid):
            root_keys[i].add(norm_key(p.values[key_aid]))
        for ea in email_aids:
            if p.values.get(ea):
                root_mails[i].add(str(p.values[ea]).strip().casefold())

    def conflict(ra, rb, by_name=False) -> bool:
        ka, kb = root_keys[ra], root_keys[rb]
        if ka and kb and not (ka & kb):
            # two numbers from the same numbering system contradict each other; an old number
            # ("D-1009") and today's ("10023") do not – the firm changed its system
            sa, sb = {_key_shape(k) for k in ka}, {_key_shape(k) for k in kb}
            if not by_name or (sa & sb):
                return True
        if by_name:
            ma, mb = root_mails[ra], root_mails[rb]
            if ma and mb and not (ma & mb):
                da, db = {_domain(x) for x in ma}, {_domain(x) for x in mb}
                if (da & FREEMAIL) or (db & FREEMAIL) or not (da & db):
                    return True
        return False

    def join(a, b, by_name=False) -> bool:
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            return True
        if conflict(ra, rb, by_name):
            return False
        r = uf.union(ra, rb)
        other = rb if r == ra else ra
        root_keys[r] |= root_keys.pop(other, set())
        root_mails[r] |= root_mails.pop(other, set())
        return True

    # 1. same number
    if key_aid:
        first = {}
        for i, p in enumerate(protos):
            v = p.values.get(key_aid)
            if v is None:
                continue
            k = norm_key(v)
            if k in first:
                join(first[k], i)
            else:
                first[k] = i
    # a name or address that repeats inside one list does not identify a row of that list
    # (a timesheet names the same building site every day)
    # (counted per delivered table: two versions of one list name the same supplier once each)
    def table_of(p):
        return p.prov[0][0] if p.prov else id(p.member)
    inside = Counter()
    for p in protos:
        if title_aid and p.values.get(title_aid):
            inside[(table_of(p), "n", norm_name(p.values[title_aid]))] += 1
        for ea in email_aids:
            if p.values.get(ea):
                inside[(table_of(p), "e", str(p.values[ea]).strip().casefold())] += 1
    # 2. same e-mail (master data only: two invoices to one address are two invoices)
    if master and email_aids:
        first = {}
        for i, p in enumerate(protos):
            for ea in email_aids:
                v = p.values.get(ea)
                if not v:
                    continue
                k = str(v).strip().casefold()
                if inside[(table_of(p), "e", k)] > 1:
                    continue
                if k in first:
                    join(first[k], i)
                else:
                    first[k] = i
    # 3. same normalised name (master data, no contradicting numbers or private e-mails)
    if master and title_aid:
        first = {}
        for i, p in enumerate(protos):
            v = p.values.get(title_aid)
            if not v:
                continue
            k = norm_name(v)
            if len(k) < 3 or inside[(table_of(p), "n", k)] > 1:
                continue
            if k in first:
                join(first[k], i, by_name=True)
            else:
                first[k] = i
    # 4. lines: keyless rows of the same file are distinct; keyless transactions by content
    groups_idx: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups_idx[uf.find(i)].append(i)
    groups = [Group(protos=[protos[i] for i in idxs]) for _, idxs in sorted(groups_idx.items())]
    if stale:
        for g in groups:
            old = [p for p in g.protos if p.prov and all(tuple(x) in stale for x in p.prov)]
            if not old:
                continue
            rest = [p for p in g.protos if not any(p is o for o in old)]
            if any(_family(p) in {_family(o) for o in old} for p in rest):
                g.protos = rest  # moved within its list ("Aktiv" -> "Abgeschlossen"): the old row no longer speaks
            else:
                g.vanished = stale[tuple(old[0].prov[0])]  # gone from that program; other sources may still know it
    link_aids, pos_aids = _line_attrs(t) if t.kind == "line" else ({}, {})
    for g in groups:
        _merge_values(t, g)
        _idents(t, g, key_aid, email_aids, title_aid, link_aids, pos_aids)
    # an identity several groups share identifies none of them: such groups are known by content
    shared = Counter(i for g in groups for i in g.idents)
    for g in groups:
        amb = {i for i in g.idents if shared[i] > 1 and not i.startswith(("h~", "l~"))}
        if amb:
            g.idents -= amb
            if not g.idents:
                g.idents = {f"h~{_content_hash(p)}" for p in g.protos}
    _number_occurrences(groups)
    if key_aid and any(m.extracted_from is None for m in t.members) and any(m.extracted_from for m in t.members):
        def rebuild(protos):
            g = Group(protos=protos)
            _merge_values(t, g)
            _idents(t, g, key_aid, email_aids, title_aid, link_aids, pos_aids)
            return g
        groups = _phantoms(t, groups, decisions, questions, rebuild)
    if master and title_aid:
        groups = _aliases(t, groups, decisions, log)
        n_q = len(questions) if questions is not None else 0
        groups = _fuzzy(t, groups, decisions, questions, log)
        # once "Fährhaus Hotel GmbH" and "Hotel Fährhaus GmbH" are one, the short "Fährhaus Hotel" has one home
        groups = _aliases(t, groups, decisions, log)
        if questions is not None and len(questions) > n_q:
            where = {id(p): k for k, g in enumerate(groups) for p in g.protos}
            questions[n_q:] = [q for q in questions[n_q:] if q.get("kind") != "same_record" or
                               where.get(id(q["a"].protos[0])) != where.get(id(q["b"].protos[0]))]
    return groups


def _near_key(a: str, b: str) -> bool:
    """P-2026-031 for P-2026-013: the same number with two digits swapped (one digit off is just
    the next number in a series)."""
    if a == b or re.sub(r"\d", "9", a) != re.sub(r"\d", "9", b):
        return False
    da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    diff = [i for i, (x, y) in enumerate(zip(da, db)) if x != y]
    return len(diff) == 2 and da[diff[0]] == db[diff[1]] and da[diff[1]] == db[diff[0]]


def _compatible(t: TypeDraft, a: Group, b: Group) -> bool:
    """Do the names both know agree? "P-2026-031 Website-Relaunch" for the "Website-Relaunch" of the same
    customer does; "Café Strandperle" for "Bäckerei Hansen" does not."""
    agree = 0
    for at in t.attrs:
        if at is t.key or at.kind != "text" or at.role not in ("name", "person"):
            continue
        va, vb = a.values.get(at.aid), b.values.get(at.aid)
        if not va or not vb:
            continue
        na, nb = norm_name(str(va)), norm_name(str(vb))
        if na == nb or (na and nb and (na in nb or nb in na)) or name_similarity(na, nb) >= 0.8:
            agree += 1
        else:
            return False
    return agree >= 1


def _phantoms(t: TypeDraft, groups: list[Group], decisions: dict, questions: list | None, rebuild) -> list[Group]:
    """A number that only other lists name (40 time entries on "P-2026-031"), while the list of these
    things has a number one swap away ("P-2026-013"): probably a typo. Asked, merged when confirmed."""
    key = t.key.aid
    base, phantom = {}, []
    for gi, g in enumerate(groups):
        k = g.values.get(key)
        if k is None:
            continue
        if any(p.member.extracted_from is None for p in g.protos):
            base[gi] = str(k)
        else:
            phantom.append(gi)
    if not base or not phantom or len(phantom) > 0.3 * len(base):
        return groups
    merged, drop = {}, set()
    for gi in phantom:
        k = str(groups[gi].values.get(key))
        near = [bi for bi, bk in base.items() if _near_key(k, bk)]
        if len(near) != 1:
            continue
        g, b = groups[gi], groups[near[0]]
        if not _compatible(t, g, b):
            continue  # a customer of its own (another name), not a typo
        pk = pair_key(g, b)
        d = decisions.get(pk)
        if d == "same":
            merged.setdefault(near[0], list(b.protos)).extend(g.protos)
            drop.add(gi)
        elif d != "different" and questions is not None:
            n = sum(len(p.prov) for p in g.protos)
            kb = base[near[0]]
            questions.append(dict(kind="same_record", type=t, a=g, b=b, sim=0.9, key=pk, con=[],
                                  pro=[f"„{k}“ steht nur in {n} Zeilen anderer Listen", f"„{kb}“ hat dieselben Ziffern"],
                                  text=f"„{k}“ kommt nur in {n} Zeilen anderer Listen vor, nicht in der Liste der "
                                       f"{t.plural or t.name} – ist „{kb}“ gemeint?"))
    if not merged:
        return groups
    out = []
    for gi, g in enumerate(groups):
        if gi in drop:
            continue
        out.append(rebuild(merged[gi]) if gi in merged else g)
    return out


def _family(p: Proto) -> str:
    """The list a row belongs to, whatever the sheet or the date in the file name."""
    label = (p.member.sig_label or p.member.label or "").split(" › ")[0]
    return re.sub(r"[^a-zäöüß]+", "", label.casefold())


_ADDRESS_ROLES = ("street", "zip", "city")


def _edit1(a: str, b: str) -> bool:
    """At most two letters apart (a typo), for words long enough that this is not a different word."""
    if a == b or min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 2:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 2


def is_typo_of(v, w) -> bool:
    """'Bistro Krabenkutter' and 'Bistro Krabbenkutter': same words, one of them misspelt.
    'Bistro Leuchtturm' and 'Bistro Leuchtturm GmbH' is a change, not a typo."""
    a, b = norm_name(v).split(), norm_name(w).split()
    if len(a) != len(b) or a == b:
        return False
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    return len(diff) == 1 and _edit1(*diff[0])


_LEGAL = {"gmbh", "mbh", "ag", "kg", "ug", "ek", "e k", "gbr", "ohg", "ev", "e v", "eg", "kgaa", "se", "co", "co kg",
          "gmbh co kg", "partg", "partgmbb", "haftungsbeschraenkt", "ltd", "inc", "llc", "bv", "sarl", "srl"}


def fuller_legal_name(a, b):
    """'Feinkost Tidenhub' and 'Feinkost Tidenhub GmbH': the second, which names the legal form, belongs on
    an invoice. Returns the fuller of the two, or None if they are not that kind of pair."""
    if not isinstance(a, str) or not isinstance(b, str):
        return None
    wa, wb = fold(a).replace(".", " ").replace("&", " ").split(), fold(b).replace(".", " ").replace("&", " ").split()
    short, long_, longer = (wa, wb, b) if len(wa) < len(wb) else (wb, wa, a)
    if short and long_[:len(short)] == short and len(long_) > len(short) and " ".join(long_[len(short):]) in _LEGAL:
        return longer
    return None


def _merge_values(t: TypeDraft, g: Group):
    g.protos.sort(key=lambda p: p.priority, reverse=True)
    roles = {a.aid: a.role for a in t.attrs}
    addr = {aid for aid, r in roles.items() if r in _ADDRESS_ROLES}
    # an address moves as a whole: street, postcode and town from the same (most current) source
    owner = next((p for p in g.protos if addr & set(p.values)), None)
    for p in g.protos:
        g.lines.extend(p.prov)
        for aid, v in p.values.items():
            mixed = aid in addr and owner is not None and p is not owner and addr & set(owner.values) and \
                any(owner.values.get(x) is not None and p.values.get(x) is not None and
                    norm_name(owner.values[x]) != norm_name(p.values[x]) for x in addr)
            if aid not in g.values and not mixed:
                g.values[aid] = v
                g.prov[aid] = list(p.prov[:3])
            elif aid not in g.values or norm_key(v) != norm_key(g.values.get(aid)) and norm_name(v) != norm_name(g.values.get(aid)):
                alts = g.alts.setdefault(aid, [])
                if len(alts) < 5 and all(norm_key(x) != norm_key(v) for x, _ in alts):
                    alts.append((v, p.prov[:1]))
    # a typo in the newest file does not overwrite the name every other source spells the same
    ta = t.title.aid if t.title is not None and t.kind == "master" else None
    if ta and ta in g.values:
        for p in g.protos:
            full = fuller_legal_name(g.values[ta], p.values.get(ta))
            if full is not None and full != g.values[ta]:
                g.values[ta] = full  # the name with its legal form
                g.prov[ta] = list(p.prov[:3])
    if ta and ta in g.values and len(g.protos) >= 3:
        votes = Counter(norm_name(p.values[ta]) for p in g.protos if p.values.get(ta) is not None)
        cur = norm_name(g.values[ta])
        best, n = max(votes.items(), key=lambda kv: (kv[1], kv[0] == cur))
        if best != cur and n >= 2 and votes[cur] == 1 and is_typo_of(g.values[ta], best):
            winner = next(p for p in g.protos if norm_name(p.values.get(ta) or "") == best)
            g.alts.setdefault(ta, []).insert(0, (g.values[ta], g.prov.get(ta, [])[:1]))
            g.values[ta] = winner.values[ta]
            g.prov[ta] = list(winner.prov[:3])


_POS_WORDS = {"pos", "position", "zeile", "lfd", "posnr", "line", "positionsnr"}


def _line_attrs(t: TypeDraft) -> tuple[dict, dict]:
    """Per member: the attribute holding the parent's number, and a position column if any."""
    from ..text import tokens
    link, pos = {}, {}
    for m in t.members:
        for col, _target in m.links:
            a = t.attr_of(m, col)
            if a is not None:
                link[id(m)] = a.aid
                break
        for c in m.cols:
            if set(tokens(c.name)) & _POS_WORDS:
                a = t.attr_of(m, c.name)
                if a is not None:
                    pos[id(m)] = a.aid
                    break
    return link, pos


def _number_occurrences(groups: list[Group]):
    """Identical rows without any key (two equal bookings on one day) are told apart by their
    order of appearance, so they keep their identities from one growth to the next."""
    pending = [g for g in groups if any(i.startswith("h~") or i.startswith("l~") for i in g.idents)]
    pending.sort(key=lambda g: (min(g.lines) if g.lines else (0, 0)))
    seen: dict[str, int] = defaultdict(int)
    for g in pending:
        fixed = set()
        for i in g.idents:
            if i[1] == "~":
                seen[i] += 1
                fixed.add(f"{i[0]}:{i[2:]}:{seen[i]}")
            else:
                fixed.add(i)
        g.idents = fixed


def _idents(t: TypeDraft, g: Group, key_aid, email_aids, title_aid, link_aids=None, pos_aids=None):
    g.idents = set()
    for p in g.protos:
        if key_aid and p.values.get(key_aid) is not None:
            g.idents.add("k:" + norm_key(p.values[key_aid]))
        if t.kind == "master":
            for ea in email_aids:
                if p.values.get(ea):
                    g.idents.add("e:" + str(p.values[ea]).strip().casefold())
            if title_aid and p.values.get(title_aid):
                nk = norm_name(p.values[title_aid])
                if len(nk) >= 3:
                    g.idents.add("n:" + nk)
    if not g.idents:
        if t.kind == "line":
            # a line is identified by its parent's number and its position (or its content), so a
            # new version of the file finds the same lines; without a parent number, by its place
            for p in g.protos:
                la = (link_aids or {}).get(id(p.member))
                parent = norm_key(p.values.get(la)) if la and p.values.get(la) is not None else None
                if parent:
                    pa = (pos_aids or {}).get(id(p.member))
                    if pa and p.values.get(pa) is not None:
                        g.idents.add(f"l:{parent}:p{norm_key(p.values[pa])}")
                    else:
                        g.idents.add(f"l~{parent}:{_content_hash(p)}")
                else:
                    tid, line = p.prov[0] if p.prov else (p.member.table_id, p.idx)
                    g.idents.add(f"r:{tid}:{line}")
        else:
            for p in g.protos:
                g.idents.add(f"h~{_content_hash(p)}")


def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))[-7:]


def _evidence(t: TypeDraft, a: Group, b: Group) -> tuple[list[str], list[str]]:
    pro, con = [], []
    for attr in t.attrs:
        va, vb = a.values.get(attr.aid), b.values.get(attr.aid)
        if va is None or vb is None:
            continue
        if attr.role == "phone" and _digits(va) and _digits(vb):
            if _digits(va) == _digits(vb):
                pro.append("gleiche Telefonnummer")
            else:
                con.append("andere Telefonnummer")
        elif attr.kind == "email":
            if str(va).casefold() == str(vb).casefold():
                pro.append("gleiche E-Mail")
            elif _domain(str(va)) == _domain(str(vb)) and _domain(str(va)) not in FREEMAIL:
                pro.append("gleiche E-Mail-Domain")
            else:
                con.append("verschiedene E-Mail-Adressen")
        elif attr.role == "street":
            if norm_street(va) == norm_street(vb):
                pro.append("gleiche Straße")
            else:
                con.append("andere Straße")
        elif attr.role == "zip":
            if norm_key(va) == norm_key(vb):
                pro.append("gleiche PLZ")
            else:
                con.append("andere PLZ")
        elif attr.role == "city":
            if norm_name(va) == norm_name(vb):
                pro.append("gleicher Ort")
            else:
                con.append("anderer Ort")
        elif attr is t.key and norm_key(va) != norm_key(vb):
            if _key_shape(norm_key(va)) == _key_shape(norm_key(vb)):
                con.append(f"verschiedene {attr.name} ({va} / {vb})")
            else:
                pro.append(f"alte und neue {attr.name} ({va} / {vb})")
    return sorted(set(pro)), sorted(set(con))


def pair_key(a: Group, b: Group) -> str:
    ia = min(a.idents) if a.idents else ""
    ib = min(b.idents) if b.idents else ""
    return "|".join(sorted((ia, ib)))


def _fuzzy(t: TypeDraft, groups: list[Group], decisions: dict, questions: list | None, log: list | None):
    title = t.title.aid
    blocks: dict[str, list[int]] = defaultdict(list)
    names = []
    # a name that repeats inside one list names no single thing there ("Heizung / FBH" in every flat
    # of a measurement sheet): such rows are not asked about
    tables = [{ln[0] for ln in g.lines} for g in groups]
    positions = any(set(tokens(a.name)) & _POS_WORDS for a in t.attrs)  # lines of a measurement or offer
    inside = Counter()
    for i, g in enumerate(groups):
        nm = norm_name(g.values.get(title, "")) if g.values.get(title) else ""
        for tb in tables[i]:
            inside[(tb, nm)] += 1
    for i, g in enumerate(groups):
        nm = norm_name(g.values.get(title, "")) if g.values.get(title) else ""
        names.append(nm)
        if not nm:
            continue
        for tok in nm.split():
            if len(tok) >= 4 and (not blocks[tok[:4]] or blocks[tok[:4]][-1] != i):
                blocks[tok[:4]].append(i)
    seen_pairs = set()
    merges = []
    for idxs in blocks.values():
        if len(idxs) > 60:
            continue  # too generic ("cafe")
        for x in range(len(idxs)):
            for y in range(x + 1, len(idxs)):
                i, j = idxs[x], idxs[y]
                if i == j or (i, j) in seen_pairs:
                    continue
                seen_pairs.add((i, j))
                shared = tables[i] & tables[j]
                if shared and any(max(inside[(tb, names[i])], inside[(tb, names[j])]) > (1 if positions else 2)
                                  for tb in shared):
                    continue
                sim = name_similarity(names[i], names[j])
                if sim < 0.8:
                    continue
                pro, con = _evidence(t, groups[i], groups[j])
                ta, tb = groups[i].values.get(title), groups[j].values.get(title)
                if lexicon.looks_like_person(str(ta)) or lexicon.looks_like_person(str(tb)):
                    fa, fb = names[i].split()[0], names[j].split()[0]
                    if fa != fb:
                        continue  # Hannah Brandt is not Anna Brandt
                    strong = {"gleiche Telefonnummer", "gleiche Straße", "gleiche E-Mail"}
                    if "verschiedene E-Mail-Adressen" in con and not (set(pro) & strong):
                        continue  # same name, different private addresses: most likely two people
                key_conflict = any(c.startswith("verschiedene") and "E-Mail" not in c for c in con)
                strong_pro = set(pro) & {"gleiche Telefonnummer", "gleiche Straße", "gleiche E-Mail"}
                strong_con = set(con) & {"andere Straße", "verschiedene E-Mail-Adressen"}
                if key_conflict and not strong_pro:
                    continue  # two numbers and nothing else in common: two things
                score = sim + 0.06 * len(pro) - 0.1 * len(con)
                pk = pair_key(groups[i], groups[j])
                d = decisions.get(pk)
                if d == "different":
                    continue
                # a new phone number does not make a new person: the address speaks louder
                if d == "same" or (not key_conflict and sim >= 0.95 and pro and
                                   (not con or (strong_pro and not strong_con and len(pro) >= 2))):
                    merges.append((i, j, sim, pro, d == "same"))
                elif score >= 0.86 and questions is not None:
                    questions.append(dict(kind="same_record", type=t, a=groups[i], b=groups[j], sim=round(sim, 3),
                                          pro=pro, con=con, key=pk))
    if not merges:
        return groups
    uf = UF(len(groups))
    members: dict[int, list[int]] = {i: [i] for i in range(len(groups))}
    for i, j, sim, pro, decided in merges:
        ri, rj = uf.find(i), uf.find(j)
        if ri == rj:
            continue
        if not decided:
            ok = True
            for x in members[ri]:
                for y in members[rj]:
                    if (x, y) in ((i, j), (j, i)):
                        continue
                    if name_similarity(names[x], names[y]) < 0.9 or \
                            set(_evidence(t, groups[x], groups[y])[1]) & {"andere Straße", "verschiedene E-Mail-Adressen"} or \
                            any(c.startswith("verschiedene") and "E-Mail" not in c
                                for c in _evidence(t, groups[x], groups[y])[1]):
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                continue  # A~B and B~C does not make A~C
        r = uf.union(ri, rj)
        members[r] = members.pop(ri if r != ri else rj, []) + members.get(r, [])
        if log is not None:
            log.append(dict(kind="dedupe", type=t.name, a=groups[i].values.get(title), b=groups[j].values.get(title),
                            sim=round(sim, 3), why=pro, decided=decided))
    merged: dict[int, Group] = {}
    for i, g in enumerate(groups):
        r = uf.find(i)
        if r not in merged:
            merged[r] = Group(protos=list(g.protos), idents=set(g.idents), merges=list(g.merges), fuzzy=g.fuzzy,
                              vanished=g.vanished)
        else:
            merged[r].protos.extend(g.protos)
            merged[r].idents |= g.idents
            merged[r].merges.extend(g.merges)
            merged[r].fuzzy = True
            merged[r].vanished = merged[r].vanished or g.vanished
    for i, j, sim, pro, decided in merges:
        r = uf.find(i)
        if not decided and r == uf.find(j) and r in merged:
            merged[r].merges.append(dict(key=pair_key(groups[i], groups[j]), name=groups[j].values.get(title),
                                         other=groups[i].values.get(title), why=", ".join(pro) or "ähnlicher Name"))
    out = []
    for g in merged.values():
        _merge_values(t, g)
        out.append(g)
    return out


# what makes a row more than a name: a ticket system's "Wattwurm" has none of it, the customer list has all
_SUBSTANCE_ROLES = {"email", "phone", "street", "zip", "city", "iban", "url", "vat_id"}


def _thin(t: TypeDraft, g: Group, title: str) -> bool:
    """Only a name (and perhaps another program's own number for it): how a ticket system, a time tracker
    or a project list names a customer it knows by its short name."""
    if t.key is not None and g.values.get(t.key.aid) is not None:
        return False
    return not any(g.values.get(a.aid) is not None for a in t.attrs
                   if a.aid != title and (a.role in _SUBSTANCE_ROLES or a.kind in _SUBSTANCE_ROLES))


_INFLECTIONS = ("er", "s", "es", "n", "en", "e", "ern", "sche", "scher", "isch")


def _same_word(w: str, x: str) -> bool:
    """"Lokstedt" and "Lokstedter" are one word; "Alster" and "Alsterblick" are not."""
    if w == x:
        return True
    a, b = (w, x) if len(w) < len(x) else (x, w)
    return len(a) >= 4 and b.startswith(a) and b[len(a):] in _INFLECTIONS


def _part_of(w: str, x: str) -> bool:
    """"Optik" in "Augenoptik", "Dach" in "Dachdeckerei": one part of a compound."""
    return len(w) >= 4 and len(x) >= len(w) + 4 and (x.startswith(w) or x.endswith(w))


def _within(small: set, big: set) -> bool:
    """Every word of the short name is in the long one ("Druckhaus Lokstedt" in "Lokstedter Druckhaus");
    beside a word found as it is, a part of a compound will do ("Optik Schulz" in "Augenoptik Schulz")."""
    found = {w for w in small if any(_same_word(w, x) for x in big)}
    if not found:
        return False
    return all(any(_part_of(w, x) for x in big) for w in small - found)


def _aliases(t: TypeDraft, groups: list[Group], decisions: dict, log: list | None) -> list[Group]:
    """Short names: the ticket system and the time tracker say "Wattwurm", the customer list says
    "Wattwurm Reisen GmbH". A row that is nothing but such a name joins the one thing whose name contains
    all its words – if there is exactly one. "Hafenkontor" stays apart when there is a Hafenkontor
    Logistik and a Hafenkontor Immobilien. The join is shown on the record and can be undone."""
    title = t.title.aid
    names = [norm_name(g.values.get(title) or "") for g in groups]
    toks = [set(n.split()) for n in names]
    index: dict[str, set] = defaultdict(set)
    for i, ws in enumerate(toks):
        for w in ws:
            index[w[:5]].add(i)
    into: dict[int, int] = {}
    for i, g in enumerate(groups):
        small = toks[i]
        if not small or sum(len(w) for w in small) < 6 or not _thin(t, g, title):
            continue
        if lexicon.looks_like_person(str(g.values.get(title))) and len(small) > 1:
            continue  # "Anna Brandt" is not "Brandt Media Group"
        cands = set().union(*(index.get(w[:5], set()) for w in small)) - {i}
        cands = {j for j in cands if names[j] != names[i] and _within(small, toks[j])
                 and (len(toks[j]) > len(small) or len(names[j]) > len(names[i]))}
        if len(cands) != 1:
            continue  # nothing, or two firms with that word: the short name says too little
        j = next(iter(cands))
        if decisions.get(pair_key(g, groups[j])) == "different":
            continue
        into[i] = j
    if not into:
        return groups
    # a chain (A -> B -> C) ends at the fullest name
    def root(i):
        seen = set()
        while i in into and i not in seen:
            seen.add(i)
            i = into[i]
        return i
    joined: dict[int, list[int]] = defaultdict(list)
    for i in into:
        joined[root(i)].append(i)
    out = []
    for i, g in enumerate(groups):
        if i in into:
            continue
        if i not in joined:
            out.append(g)
            continue
        m = Group(protos=list(g.protos), idents=set(g.idents), merges=list(g.merges), fuzzy=True, vanished=g.vanished)
        for k in joined[i]:
            m.protos.extend(groups[k].protos)
            m.idents |= groups[k].idents
            m.merges.append(dict(key=pair_key(groups[k], g), name=groups[k].values.get(title), why="Kurzform"))
        _merge_values(t, m)
        long_name = g.values.get(title)
        if long_name is not None:
            m.values[title] = long_name  # the full name stays the name; the short one is no contradiction
            m.prov[title] = list(g.prov.get(title, [])[:3])
            shorts = {norm_name(groups[k].values.get(title) or "") for k in joined[i]}
            kept = [(v, pv) for v, pv in m.alts.get(title, []) if norm_name(v) not in shorts]
            if kept:
                m.alts[title] = kept
            else:
                m.alts.pop(title, None)
        if log is not None:
            for k in joined[i]:
                log.append(dict(kind="dedupe", type=t.name, a=groups[k].values.get(title), b=long_name, sim=None,
                                why=["Kurzform"], decided=False))
        out.append(m)
    return out


def fold_email(v) -> str:
    return fold(str(v)).strip()
