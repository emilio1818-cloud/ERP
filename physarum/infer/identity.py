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
from collections import defaultdict
from dataclasses import dataclass, field

from .. import lexicon
from ..text import fold, name_similarity, norm_key, norm_name
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


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def _content_hash(p: Proto) -> str:
    items = sorted((k, str(v)) for k, v in p.values.items())
    return hashlib.sha1(repr(items).encode()).hexdigest()[:16]


def resolve(t: TypeDraft, protos: list[Proto], decisions: dict | None = None,
            questions: list | None = None, log: list | None = None) -> list[Group]:
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
    # 2. same e-mail (master data only: two invoices to one address are two invoices)
    if master and email_aids:
        first = {}
        for i, p in enumerate(protos):
            for ea in email_aids:
                v = p.values.get(ea)
                if not v:
                    continue
                k = str(v).strip().casefold()
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
            if len(k) < 3:
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
    link_aids, pos_aids = _line_attrs(t) if t.kind == "line" else ({}, {})
    for g in groups:
        _merge_values(t, g)
        _idents(t, g, key_aid, email_aids, title_aid, link_aids, pos_aids)
    _number_occurrences(groups)
    if master and title_aid:
        groups = _fuzzy(t, groups, decisions, questions, log)
    return groups


def _merge_values(t: TypeDraft, g: Group):
    g.protos.sort(key=lambda p: p.priority, reverse=True)
    for p in g.protos:
        g.lines.extend(p.prov)
        for aid, v in p.values.items():
            if aid not in g.values:
                g.values[aid] = v
                g.prov[aid] = list(p.prov[:3])
            else:
                if norm_key(v) != norm_key(g.values[aid]) and norm_name(v) != norm_name(g.values[aid]):
                    alts = g.alts.setdefault(aid, [])
                    if len(alts) < 5 and all(norm_key(x) != norm_key(v) for x, _ in alts):
                        alts.append((v, p.prov[:1]))


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
            if norm_name(va) == norm_name(vb):
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
            con.append(f"verschiedene {attr.name} ({va} / {vb})")
    return sorted(set(pro)), sorted(set(con))


def pair_key(a: Group, b: Group) -> str:
    ia = min(a.idents) if a.idents else ""
    ib = min(b.idents) if b.idents else ""
    return "|".join(sorted((ia, ib)))


def _fuzzy(t: TypeDraft, groups: list[Group], decisions: dict, questions: list | None, log: list | None):
    title = t.title.aid
    blocks: dict[str, list[int]] = defaultdict(list)
    names = []
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
                score = sim + 0.06 * len(pro) - 0.1 * len(con)
                pk = pair_key(groups[i], groups[j])
                d = decisions.get(pk)
                if d == "different":
                    continue
                if d == "same" or (not key_conflict and sim >= 0.95 and pro and not con):
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
                    if name_similarity(names[x], names[y]) < 0.9 or _evidence(t, groups[x], groups[y])[1]:
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
            merged[r] = Group(protos=list(g.protos), idents=set(g.idents))
        else:
            merged[r].protos.extend(g.protos)
            merged[r].idents |= g.idents
            merged[r].fuzzy = True
    out = []
    for g in merged.values():
        _merge_values(t, g)
        out.append(g)
    return out


def fold_email(v) -> str:
    return fold(str(v)).strip()
