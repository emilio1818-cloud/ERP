"""Growth: from the substrate (everything ever dumped in) to the organism (the ERP model)
and its records. Runs completely and deterministically on every new dump, so the result
never depends on the order in which files arrived. Human decisions are constraints that
every run respects.
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import date, datetime

from . import lexicon
from .infer.identity import Group, build_protos, resolve
from .infer.normalize import normalize
from .infer.observe import Obs, display_header, obs_from_table
from .infer.relations import MentionIndex, RelDraft, discover, discover_mentions
from .infer.unify import AttrDraft, TypeDraft, obs_sig, unify
from .ingest import read_file
from .store import Store, dumps, loads, now_iso
from .text import fold, norm_key, norm_name, slug, tokens
from .values import profile_table

DOC_TYPE = "doc"
DOC_ATTRS = [
    ("doc_title", "Titel", "text", "name"), ("doc_kind", "Art", "text", "category"),
    ("doc_from", "Von", "text", "person"), ("doc_to", "An", "text", "person"),
    ("doc_date", "Datum", "datetime", "date"), ("doc_text", "Text", "text", "notes"),
    ("doc_file", "Datei", "text", "file"),
]
DOC_KIND_LABEL = {"email": "E-Mail", "pdf": "PDF", "text": "Text", "docx": "Word", "bild": "Bild"}


class Progress:
    def __init__(self, cb=None):
        self.cb = cb
        self.lines: list[str] = []

    def __call__(self, msg: str, frac: float | None = None):
        self.lines.append(msg)
        if self.cb:
            self.cb(msg, frac)


# --- ingestion -----------------------------------------------------------------------------------

def ingest(store: Store, files: list[tuple[str, bytes]], actor: str | None = None,
           progress: Progress | None = None) -> list[dict]:
    """Store originals and digest them into the substrate. Nested files (zip members, e-mail
    attachments) become sources of their own."""
    out = []
    queue = [(name, data, None) for name, data in files]
    guard = 0
    while queue and guard < 5000:
        guard += 1
        name, data, parent = queue.pop(0)
        with store.tx() as c:
            sid, new = store.add_source(name, data, parent_id=parent, actor=actor, c=c)
            if not new:
                out.append(dict(id=sid, name=name, new=False))
                continue
            d = read_file(name, data)
            store.save_digest(sid, d, c)
        if progress:
            what = []
            if d.tables:
                what.append(f"{sum(len(t.rows) for t in d.tables)} Zeilen in {len(d.tables)} Tabelle(n)")
            if d.docs:
                what.append(f"{len(d.docs)} Dokument(e)")
            progress(f"{name}: " + (", ".join(what) or "kein lesbarer Inhalt"))
        out.append(dict(id=sid, name=name, new=True, tables=len(d.tables), docs=len(d.docs), notes=d.notes))
        for an, ad in d.attachments:
            queue.append((an, ad, sid))
    return out


# --- regrow ----------------------------------------------------------------------------------------

def _premerge(raw: list[dict]) -> list[dict]:
    """Tables with identical columns (one sheet per year, one file per month) are one table."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for t in raw:
        sig = tuple(" ".join(tokens(c)) for c in t["columns"])
        groups[sig].append(t)
    out = []
    for sig, ts in groups.items():
        if len(ts) == 1:
            t = ts[0]
            out.append(dict(t, lines=[(t["id"], l) for l in t["lines"]], tables=[t["id"]]))
            continue
        first = ts[0]
        rows, lines = [], []
        for t in ts:
            rows += t["rows"]
            lines += [(t["id"], l) for l in t["lines"]]
        stems = {t["name"].split(" › ")[0] for t in ts}
        if len(stems) == 1 and all(t["sheet"] for t in ts):
            label = f"{first['name'].split(' › ')[0]} › " + " + ".join(t["sheet"] for t in ts)
        else:
            label = " + ".join(t["name"] for t in ts)
        out.append(dict(first, name=label, rows=rows, lines=lines, tables=[t["id"] for t in ts],
                        source_id=max(t["source_id"] for t in ts)))
    return out


def _assign_ids(store: Store, types: list[TypeDraft], c):
    reg_t = store.registry("type")
    reg_a = store.registry("attr")
    used_t = set()
    new_t, new_a = {}, {}
    for t in sorted(types, key=lambda t: -sum(m.n for m in t.members)):
        sigs = [obs_sig(m) for m in t.members]
        cand = Counter(reg_t[s] for s in sigs if s in reg_t and reg_t[s] not in used_t)
        tid = cand.most_common(1)[0][0] if cand else f"t{store.next_id('type', c)}"
        used_t.add(tid)
        t.tid = tid
        for s in sigs:
            new_t[s] = tid
        used_a = set()
        for a in t.attrs:
            keys = [f"{tid}|{obs_sig(m)}|{fold(col.name)}" for m, col in a.cols]
            ca = Counter(reg_a[k] for k in keys if k in reg_a and reg_a[k] not in used_a)
            aid = ca.most_common(1)[0][0] if ca else f"a{store.next_id('attr', c)}"
            used_a.add(aid)
            a.aid = aid
            for k in keys:
                new_a[k] = aid
    store.register("type", new_t, c)
    store.register("attr", new_a, c)


def _jsonable(v):
    if isinstance(v, datetime):
        return v.isoformat(timespec="minutes")
    if isinstance(v, date):
        return v.isoformat()
    return v


def regrow(store: Store, progress: Progress | None = None, actor: str = "Physarum") -> dict:
    t0 = time.time()
    progress = progress or Progress()
    log: list[dict] = []
    raw = _premerge(store.raw_tables())
    progress(f"Lese {len(raw)} Tabellen …", 0.05)
    observations: list[Obs] = []
    table_meta = {}
    for t in raw:
        profs = profile_table(t["columns"], t["rows"], t["meta"])
        o = obs_from_table(t["id"], t["name"], t["columns"], profs, t["lines"], source_id=t["source_id"])
        from .values import asof_date
        newest = None
        for pr in profs:
            if pr.kind in ("date", "datetime"):
                ds = [v for v in pr.values if v is not None and hasattr(v, "year")]
                if ds:
                    m = max(d.date() if isinstance(d, datetime) else d for d in ds)
                    newest = m if newest is None or m > newest else newest
        asof = asof_date(t["meta"].get("title")) or asof_date(t["source_name"])
        table_meta[t["id"]] = dict(source=t["source_name"], name=t["name"], title=t["meta"].get("title"),
                                   added_at=t["added_at"], tables=t["tables"],
                                   asof=asof.isoformat() if asof else None,
                                   newest=newest.isoformat() if newest else None)
        o.asof = (asof or newest).isoformat() if (asof or newest) else None
        observations.extend(normalize(o, log))
    progress(f"{len(observations)} Beobachtungen nach dem Herauslösen eingebetteter Dinge", 0.25)

    dec_types = {}
    for subj, val in store.decisions("same_type").items():
        a, b = subj.split("||")
        dec_types[frozenset((a, b))] = val
    asks: list[dict] = []
    types = unify(observations, dec_types, log, asks)
    progress(f"{len(types)} Arten von Dingen erkannt: " + ", ".join(t.plural for t in types[:12]), 0.4)

    with store.tx() as c:
        _assign_ids(store, types, c)
    renames = store.decisions("rename_type")
    for t in types:
        if t.tid in renames:
            r = renames[t.tid]
            t.name, t.plural = r.get("name", t.name), r.get("plural", t.plural)

    # identity
    ent_dec = store.decisions("same_record")
    questions: list[dict] = []
    groups: dict[int, list[Group]] = {}
    for t in types:
        protos = build_protos(t)
        groups[id(t)] = resolve(t, protos, ent_dec, questions, log)
    progress("Dubletten geprüft", 0.5)

    obs_type = {o.oid: t for t in types for o in t.members}
    rel_dec = store.decisions("relation")
    rels = discover(types, groups, obs_type, rel_dec, log, asks)
    taken = {(id(r.src), id(r.attr)) for r in rels}
    asks = [a for a in asks if not (a.get("kind") == "relation" and (id(a["rel"].src), id(a["rel"].attr)) in taken)]
    mindex = MentionIndex(types, groups)
    mrels = discover_mentions(types, groups, mindex, taken, log)
    progress(f"{len(rels)} Verweise und {len(mrels)} Erwähnungen gefunden", 0.6)

    derived = _lookup_copies(types, groups, rels)
    model = _build_model(store, types, groups, rels, mrels, derived, table_meta, log)
    docs = store.documents()
    with store.tx() as c:
        stats = _materialize(store, model, types, groups, rels, mrels, docs, mindex, c, actor)
    progress(f"{stats['records']} Datensätze geschrieben ({stats['new']} neu, {stats['changed']} geändert)", 0.75)

    from .behavior import infer_behavior
    from .physarum import grow_network
    from .process import infer_processes
    records = store.all_records()
    infer_behavior(model, records)
    infer_processes(model, records, store)
    grow_network(model, store)
    progress("Formeln, Abläufe und Rückgrat gelernt", 0.9)

    from .reconcile import find_matches
    mention_map = defaultdict(lambda: defaultdict(list))
    for r in store.q("SELECT from_id, attr, to_id FROM refs WHERE kind='mention' AND attr!='doc'"):
        mention_map[r["attr"]][r["to_id"]].append(r["from_id"])
    specs = {t["id"]: t for t in model["types"]}
    titles = {r["id"]: record_title(specs[t], r["data"], r["id"]) for t, rs in records.items() if t in specs for r in rs}
    matches = find_matches(model, records, mention_map, titles)
    progress(f"{len(matches)} Zahlungen ohne Rechnungsnummer über den Betrag zugeordnet (zur Bestätigung)", 0.92)

    from .questions import collect_questions
    with store.tx() as c:
        nq = collect_questions(store, model, asks, questions, c, matches=matches, titles=titles)
        prev = store.model()
        summary = _growth_summary(prev, model, stats, log, time.time() - t0)
        model["log"] = log[-400:]
        store.save_model(model, summary, c)
        store.kv_set("dirty", False, c)
    progress(f"Fertig in {time.time() - t0:.1f} s. {nq} offene Fragen.", 1.0)
    return summary


# --- derived columns ---------------------------------------------------------------------------------

def _lookup_copies(types, groups, rels) -> dict[tuple[int, int], tuple]:
    """A column that only repeats something reachable via a reference ('Kunde' name next to 'Kd-Nr')
    is a lookup, not information. It is hidden and filled automatically."""
    out = {}
    by_src = defaultdict(list)
    for r in rels:
        by_src[id(r.src)].append(r)
    for t in types:
        for a in t.attrs:
            if a.kind != "text" or any(r.attr is a for r in by_src[id(t)]):
                continue
            for r in by_src[id(t)]:
                dst_groups = groups[id(r.dst)]
                for b in r.dst.attrs:
                    if b.kind != "text":
                        continue
                    both = agree = 0
                    for gi, g in enumerate(groups[id(t)]):
                        v = g.values.get(a.aid)
                        ti = r.targets.get(gi)
                        if v is None or ti is None:
                            continue
                        w = dst_groups[ti].values.get(b.aid)
                        if w is None:
                            continue
                        both += 1
                        if norm_name(v) == norm_name(w):
                            agree += 1
                    if both >= 5 and agree / both >= 0.9:
                        out[(id(t), id(a))] = (r, b)
                        break
                if (id(t), id(a)) in out:
                    break
    return out


# --- model ---------------------------------------------------------------------------------------------

def _attr_spec(t: TypeDraft, a: AttrDraft, groups: list[Group]) -> dict:
    vals = [g.values.get(a.aid) for g in groups]
    present = [v for v in vals if v is not None]
    filled = len(present) / len(vals) if vals else 0.0
    keys = [norm_key(v) for v in present]
    distinct = len(set(keys))
    enum = None
    prof = a.rep.prof
    if prof.enum is not None and a.kind == "text":
        cnt = Counter(str(v) for v in present)
        if len(cnt) <= 30:
            enum = [v for v, _ in cnt.most_common()]
    constant = len(present) >= 3 and distinct == 1
    sources = []
    for m, col in a.cols:
        sources.append(dict(obs=m.label, column=col.name, table=m.table_id))
    spec = dict(id=a.aid, name=a.name, kind=a.kind, role=a.role, concept=a.concept, fill=round(filled, 3),
                distinct=distinct, enum=enum, constant=constant, sources=sources[:8],
                currency=getattr(prof, "currency", None), milestone=prof.milestone if a.kind in ("date", "datetime") else None)
    if constant:
        spec["value"] = _jsonable(present[0])
    return spec


def _build_model(store, types, groups, rels, mrels, derived, table_meta, log) -> dict:
    hidden_dec = store.decisions("hide_attr")
    rename_attr = store.decisions("rename_attr")
    tmodel = []
    for t in types:
        gs = groups[id(t)]
        attrs = []
        for a in t.attrs:
            spec = _attr_spec(t, a, gs)
            d = derived.get((id(t), id(a)))
            if d:
                r, b = d
                spec["derived"] = dict(via=r.attr.aid, attr=b.aid)
            residual = all(col.residual for _, col in a.cols)
            spec["hidden"] = bool(spec["constant"] or d or hidden_dec.get(a.aid) or residual)
            if residual:
                spec["residual"] = True
            if a.aid in rename_attr:
                spec["name"] = rename_attr[a.aid]
            attrs.append(spec)
        members = []
        for m in t.members:
            meta = table_meta.get(m.table_id, {})
            members.append(dict(label=m.label, sig=obs_sig(m), rows=m.n, extracted=m.extracted_from is not None,
                                determinant=m.determinant, source=meta.get("source"), title=meta.get("title"),
                                tables=meta.get("tables", [m.table_id]), asof=meta.get("asof"),
                                newest=meta.get("newest")))
        tmodel.append(dict(id=t.tid, name=t.name, plural=t.plural, concept=t.concept, kind=t.kind,
                           key=t.key.aid if t.key else None, title=t.title.aid if t.title else None,
                           attrs=attrs, members=members, count=len(gs), merge_log=t.merge_log))
    by_tid = {t["id"]: t for t in tmodel}
    rmodel = []
    for i, r in enumerate(rels):
        rid = f"r_{r.src.tid}_{r.attr.aid}"
        r.rid = rid
        targets = [r.dst.tid] + [d.tid for d, _ in r.extra]
        rmodel.append(dict(id=rid, src=r.src.tid, attr=r.attr.aid, dst=r.dst.tid, targets=targets, kind=r.kind,
                           via=r.via, inclusion=round(r.inclusion, 3), coverage=round(r.coverage, 3),
                           structural=r.structural, evidence=r.evidence, fuzzy=r.fuzzy,
                           unresolved=len(r.unresolved)))
        spec = next(a for a in by_tid[r.src.tid]["attrs"] if a["id"] == r.attr.aid)
        spec["kind"] = "ref"
        spec["ref"] = r.dst.tid
        spec["ref_kind"] = r.dst.kind
        spec["refs"] = targets
        spec["via"] = r.via
        spec["orig_name"] = spec["name"]
        same_target = [x for x in rels if x.src is r.src and x.dst is r.dst]
        generic = set(tokens(spec["name"])) <= (set(lexicon.ROLE_TERMS["id"]) | {"name", "email", "mail", "e"}) or \
            spec.get("concept") == r.dst.concept or fold(spec["name"]) in (fold(r.dst.name), fold(r.dst.plural))
        if len(same_target) == 1 and (generic or r.via in ("k", "e")) and r.attr.aid not in rename_attr:
            spec["name"] = r.dst.name if not r.extra else "Partner"
    for r in mrels:
        rid = f"m_{r.src.tid}_{r.attr.aid}_{r.dst.tid}"
        r.rid = rid
        rmodel.append(dict(id=rid, src=r.src.tid, attr=r.attr.aid, dst=r.dst.tid, targets=[r.dst.tid], kind="mention",
                           via="text", inclusion=round(r.inclusion, 3), coverage=round(r.coverage, 3),
                           structural=False, evidence=r.evidence, fuzzy=0, unresolved=0))
    # documents
    tmodel.append(dict(id=DOC_TYPE, name="Dokument", plural="Dokumente", concept="dokument", kind="document",
                       key=None, title="doc_title",
                       attrs=[dict(id=i, name=n, kind=k, role=r, fill=1.0, distinct=0, enum=None, constant=False,
                                   hidden=False, sources=[]) for i, n, k, r in DOC_ATTRS],
                       members=[], count=0, merge_log=[]))
    return dict(types=tmodel, relations=rmodel, built_at=now_iso())


# --- materialisation ---------------------------------------------------------------------------------

def _materialize(store: Store, model: dict, types: list[TypeDraft], groups: dict, rels: list[RelDraft],
                 mrels: list[RelDraft], docs, mindex: MentionIndex, c, actor: str) -> dict:
    ts = now_iso()
    stats = dict(records=0, new=0, changed=0, merged=0, removed=0)
    src_added = {r["id"]: r["added_at"] for r in store.sources(active_only=False)}
    src_name = {r["id"]: r["name"] for r in store.sources(active_only=False)}
    tables = {r["id"]: r["source_id"] for r in c.execute("SELECT id, source_id FROM raw_tables").fetchall()}
    rid_of: dict[tuple[int, int], int] = {}
    seen_records: set[int] = set()
    written: dict[int, dict] = {}

    # 1. identities -> record ids. An ident shared by several groups (two different people
    # called "Lena Neumann") identifies nobody and is not used.
    for t in types:
        existing = {r["ident"]: r["record_id"] for r in
                    c.execute("SELECT ident, record_id FROM idents WHERE type=?", (t.tid,)).fetchall()}
        shared = Counter(i for g in groups[id(t)] for i in g.idents)
        for g in groups[id(t)]:
            amb = {i for i in g.idents if shared[i] > 1}
            if amb:
                g.idents -= amb
                c.executemany("DELETE FROM idents WHERE type=? AND ident=?", [(t.tid, i) for i in amb])
                for i in amb:
                    existing.pop(i, None)
        for gi, g in enumerate(groups[id(t)]):
            rids = sorted({existing[i] for i in g.idents if i in existing})
            rids = [x for x in rids if x not in seen_records]  # never let two groups share one record
            if rids:
                rid = rids[0]
                for other in rids[1:]:
                    if other in seen_records:
                        continue
                    _merge_record(c, other, rid, ts, actor, "gleiche Identität in den Quellen")
                    stats["merged"] += 1
            else:
                cur = c.execute("INSERT INTO records(type,data,meta,origin,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                                (t.tid, "{}", "{}", "import", ts, ts))
                rid = cur.lastrowid
                g.new = True
            rid_of[(id(t), gi)] = rid
            seen_records.add(rid)
            c.executemany("INSERT INTO idents(type,ident,record_id) VALUES(?,?,?) ON CONFLICT(type,ident) DO UPDATE SET record_id=excluded.record_id",
                          [(t.tid, i, rid) for i in g.idents])

    # 2. values (refs resolved to record ids)
    ref_of = {}
    for r in rels:
        ref_of[(id(r.src), r.attr.aid)] = r
    for t in types:
        for gi, g in enumerate(groups[id(t)]):
            rid = rid_of[(id(t), gi)]
            data, raw = {}, {}
            for aid, v in g.values.items():
                r = ref_of.get((id(t), aid))
                if r is not None:
                    ti = r.targets.get(gi)
                    target = rid_of.get((id(r.dst), ti)) if ti is not None else None
                    if target is None:
                        for d, hits in r.extra:
                            if gi in hits:
                                target = rid_of.get((id(d), hits[gi]))
                                break
                    if target is not None:
                        data[aid] = target
                    else:
                        raw[aid] = _jsonable(v)
                    continue
                data[aid] = _jsonable(v)
            prov = {aid: [[tables.get(tl[0], 0), tl[0], tl[1]] for tl in lines] for aid, lines in g.prov.items()}
            alts = {aid: [[_jsonable(v), [[tables.get(x[0], 0), x[0], x[1]] for x in lines]] for v, lines in vs]
                    for aid, vs in g.alts.items()}
            srcs = sorted({tables.get(tl[0], 0) for tl in g.lines})
            _write_import(c, rid, data, raw, prov, alts, srcs, g, src_added, src_name, ts, actor, stats, written)
            stats["records"] += 1

    # 3. documents
    doc_rids = []
    existing = {r["ident"]: r["record_id"] for r in
                c.execute("SELECT ident, record_id FROM idents WHERE type=?", (DOC_TYPE,)).fetchall()}
    per_source = Counter()
    src_sha = {r["id"]: r["sha256"] for r in store.sources(active_only=False)}
    for d in docs:
        per_source[d["source_id"]] += 1
        ident = f"d:{src_sha.get(d['source_id'], '')[:16]}:{per_source[d['source_id']]}"
        data = {"doc_title": d["title"], "doc_kind": DOC_KIND_LABEL.get(d["kind"], d["kind"]), "doc_from": d["sender"],
                "doc_to": d["recipients"], "doc_date": (d["date"] or "")[:16] or None, "doc_text": d["body"],
                "doc_file": d["source_name"]}
        data = {k: v for k, v in data.items() if v}
        if ident in existing:
            rid = existing[ident]
            row = c.execute("SELECT data, deleted FROM records WHERE id=?", (rid,)).fetchone()
            if row and (loads(row["data"]) != data or row["deleted"]):
                c.execute("UPDATE records SET data=?, deleted=0, updated_at=? WHERE id=?", (dumps(data), ts, rid))
        else:
            cur = c.execute("INSERT INTO records(type,data,meta,origin,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                            (DOC_TYPE, dumps(data), dumps({"src": [d["source_id"]]}), "import", ts, ts))
            rid = cur.lastrowid
            c.execute("INSERT INTO idents(type,ident,record_id) VALUES(?,?,?)", (DOC_TYPE, ident, rid))
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,note,source_id) VALUES(?,?,?,?,?,?)",
                      (rid, ts, actor, "import", f"eingelesen aus {d['source_name']}", d["source_id"]))
            stats["new"] += 1
        seen_records.add(rid)
        doc_rids.append((rid, d))
        stats["records"] += 1

    # 4. records that no longer come from any source
    for r in c.execute("SELECT id, type, origin FROM records WHERE deleted=0 AND merged_into IS NULL").fetchall():
        if r["id"] in seen_records or r["origin"] != "import":
            continue
        has_user = c.execute("SELECT 1 FROM changes WHERE record_id=? AND kind IN ('edit','create','note') LIMIT 1",
                             (r["id"],)).fetchone()
        if has_user:
            c.execute("UPDATE records SET origin='user' WHERE id=?", (r["id"],))
            continue
        c.execute("UPDATE records SET deleted=1, updated_at=? WHERE id=?", (ts, r["id"]))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                  (r["id"], ts, actor, "remove", "nicht mehr in den Quellen enthalten"))
        stats["removed"] += 1

    # 5. refs + mentions + search index
    c.execute("DELETE FROM refs")
    type_spec = {t["id"]: t for t in model["types"]}
    ref_attrs = {(t["id"], a["id"]) for t in model["types"] for a in t["attrs"] if a["kind"] == "ref"}
    live = {}  # rid -> (type, data) for every live record; written ones come from memory
    for row in c.execute("SELECT id, type, data FROM records WHERE deleted=0 AND merged_into IS NULL").fetchall():
        rid = row["id"]
        live[rid] = (row["type"], written[rid] if rid in written else (loads(row["data"]) or {}))
    batch = []
    for rid, (tid, data) in live.items():
        for aid, v in data.items():
            if (tid, aid) in ref_attrs and isinstance(v, int):
                batch.append((rid, aid, v, "ref", None))
    for r in mrels:
        for gi, dgis in r.targets.items():
            src = rid_of.get((id(r.src), gi))
            for dgi in set(dgis):
                dst = rid_of.get((id(r.dst), dgi))
                if src and dst:
                    batch.append((src, r.attr.aid, dst, "mention", "Nummer im Text"))
    batch += _accepted_matches(store, model, c)
    for rid, d in doc_rids:
        found = mindex.scan(f"{d['title'] or ''}\n{d['body'] or ''}", names=True)
        found.update(mindex.scan_email(d["sender"] or ""))
        for (_t, _g), (t, gi, how) in found.items():
            dst = rid_of.get((id(t), gi))
            if dst:
                batch.append((rid, "doc", dst, "mention", how))
    c.executemany("INSERT OR IGNORE INTO refs(from_id,attr,to_id,kind,how) VALUES(?,?,?,?,?)", batch)
    _reindex(c, model, live)
    return stats


def match_attr(model: dict, bank_tid: str, inv_tid: str) -> str:
    """The attribute under which a bank transfer links to an invoice: the free-text relation
    if references were found in the purpose field, otherwise a dedicated link."""
    rel = next((r for r in model["relations"] if r["kind"] == "mention" and r["src"] == bank_tid and r["dst"] == inv_tid), None)
    return rel["attr"] if rel else "match"


def _accepted_matches(store: Store, model: dict, c) -> list[tuple]:
    out = []
    for subj, val in store.decisions("payment_match").items():
        if val != "yes":
            continue
        try:
            btid, bident, itid, iidents = subj.split("|", 3)
        except ValueError:
            continue
        brow = c.execute("SELECT record_id FROM idents WHERE type=? AND ident=?", (btid, bident)).fetchone()
        if not brow:
            continue
        attr = match_attr(model, btid, itid)
        for iident in iidents.split(","):
            irow = c.execute("SELECT record_id FROM idents WHERE type=? AND ident=?", (itid, iident)).fetchone()
            if irow:
                out.append((brow["record_id"], attr, irow["record_id"], "mention", "Zuordnung über den Betrag (bestätigt)"))
        if attr == "match" and not any(r["id"] == f"m_{btid}_match_{itid}" for r in model["relations"]):
            model["relations"].append(dict(id=f"m_{btid}_match_{itid}", src=btid, attr="match", dst=itid, targets=[itid],
                                           kind="mention", via="amount", inclusion=0, coverage=0, structural=False,
                                           evidence="Zahlungen über den Betrag zugeordnet (bestätigt)", fuzzy=0,
                                           unresolved=0))
    return out


def _write_import(c, rid, data, raw, prov, alts, srcs, g, src_added, src_name, ts, actor, stats, written=None):
    old_meta_json = None
    if getattr(g, "new", False):
        cur, meta = {}, {}
    else:
        row = c.execute("SELECT data, meta FROM records WHERE id=?", (rid,)).fetchone()
        cur = loads(row["data"]) or {}
        old_meta_json = row["meta"]
        meta = loads(old_meta_json) or {}
    writers = meta.get("w", {})
    newest_src = max((src_added.get(s, "") for s in srcs), default="")
    changed = []
    out = dict(cur)
    for aid, v in data.items():
        w = writers.get(aid)
        if w and w[0] == "user" and w[1] > newest_src:
            continue  # a person changed it after the newest file: the person wins
        if cur.get(aid) != v:
            if aid in cur:
                changed.append((aid, cur.get(aid), v))
            out[aid] = v
            writers[aid] = ["import", ts]
    for aid in list(cur):
        if aid not in data and writers.get(aid, ["import"])[0] == "import" and aid not in raw:
            changed.append((aid, cur[aid], None))
            out.pop(aid)
    meta.update(w=writers, prov=prov, alts=alts, raw=raw, src=srcs, fuzzy=g.fuzzy or None)
    is_new = getattr(g, "new", False)
    if written is not None:
        written[rid] = out
    meta_json = dumps(meta)
    if is_new or changed or meta_json != old_meta_json:
        c.execute("UPDATE records SET data=?, meta=?, updated_at=?, deleted=0 WHERE id=?",
                  (dumps(out), meta_json, ts if (is_new or changed) else meta.get("_ts", ts), rid))
    else:
        c.execute("UPDATE records SET deleted=0 WHERE id=? AND deleted=1", (rid,))
    if is_new:
        stats["new"] += 1
        note = "eingelesen aus " + ", ".join(src_name.get(s, f"Quelle {s}") for s in srcs[:4]) + \
            (f" und {len(srcs) - 4} weiteren" if len(srcs) > 4 else "")
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note,source_id) VALUES(?,?,?,?,?,?)",
                  (rid, ts, actor, "import", note, srcs[0] if srcs else None))
    elif changed:
        stats["changed"] += 1
        c.executemany("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,source_id,note) VALUES(?,?,?,?,?,?,?,?,?)",
                      [(rid, ts, actor, "import", aid, dumps(o), dumps(n), srcs[-1] if srcs else None,
                        f"aus {src_name.get(srcs[-1], 'neuer Quelle') if srcs else 'neuer Quelle'} übernommen")
                       for aid, o, n in changed])


def _merge_record(c, src: int, dst: int, ts: str, actor: str, why: str):
    c.execute("UPDATE records SET deleted=1, merged_into=?, updated_at=? WHERE id=?", (dst, ts, src))
    c.execute("UPDATE idents SET record_id=? WHERE record_id=?", (dst, src))
    c.execute("UPDATE notes SET record_id=? WHERE record_id=?", (dst, src))
    c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
              (dst, ts, actor, "merge", f"zusammengeführt mit Datensatz {src}: {why}"))
    # references in other records' data
    for row in c.execute("SELECT id, data FROM records WHERE deleted=0 AND data LIKE ?", (f"%{src}%",)).fetchall():
        data = loads(row["data"]) or {}
        hit = False
        for k, v in data.items():
            if v == src:
                data[k] = dst
                hit = True
        if hit:
            c.execute("UPDATE records SET data=? WHERE id=?", (dumps(data), row["id"]))


def record_text(spec: dict, data: dict, titles: dict[int, str] | None = None) -> str:
    parts = []
    for a in spec["attrs"]:
        v = data.get(a["id"])
        if v is None:
            continue
        if a["kind"] == "ref":
            if titles and isinstance(v, int) and v in titles:
                parts.append(titles[v])
            continue
        if a["kind"] in ("text", "id", "email", "phone", "zip", "iban", "url"):
            parts.append(str(v)[:2000])
    return " ".join(parts)


def _reindex(c, model: dict, live: dict | None = None):
    c.execute("DELETE FROM search")
    specs = {t["id"]: t for t in model["types"]}
    if live is None:
        live = {r["id"]: (r["type"], loads(r["data"]) or {}) for r in
                c.execute("SELECT id, type, data FROM records WHERE deleted=0 AND merged_into IS NULL").fetchall()}
    titles = {rid: record_title(specs[t], d, rid) for rid, (t, d) in live.items() if t in specs}
    c.executemany("INSERT INTO search(body, record_id, type) VALUES(?,?,?)",
                  [(record_text(specs[t], d, titles), rid, t) for rid, (t, d) in live.items() if t in specs])


def record_title(spec: dict, data: dict, rid: int | None = None) -> str:
    key, title = spec.get("key"), spec.get("title")
    parts = []
    if spec["kind"] in ("transaction",) and key and data.get(key) is not None:
        parts.append(str(data[key]))
    elif title and data.get(title) is not None and not isinstance(data.get(title), int):
        parts.append(str(data[title]))
    elif key and data.get(key) is not None:
        parts.append(str(data[key]))
    if not parts:
        for a in spec["attrs"]:
            v = data.get(a["id"])
            if v is not None and a["kind"] in ("text", "id") and not a.get("hidden") and len(str(v)) < 60:
                parts.append(str(v))
                break
    return parts[0] if parts else f"#{rid}" if rid else "–"


def _growth_summary(prev: dict | None, model: dict, stats: dict, log: list, secs: float) -> dict:
    prev_types = {t["id"]: t for t in (prev or {}).get("types", [])}
    new_types = [t["plural"] for t in model["types"] if t["id"] not in prev_types and t["kind"] != "document"] if prev else []
    new_attrs = []
    for t in model["types"]:
        p = prev_types.get(t["id"])
        if not p:
            continue
        pa = {a["id"] for a in p["attrs"]}
        for a in t["attrs"]:
            if a["id"] not in pa and not a.get("hidden"):
                new_attrs.append(f"{t['name']}: {a['name']}")
    prev_rels = {r["id"] for r in (prev or {}).get("relations", [])}
    new_rels = [r for r in model["relations"] if r["id"] not in prev_rels]
    return dict(seconds=round(secs, 2), stats=stats, new_types=new_types, new_attrs=new_attrs[:30],
                new_relations=len(new_rels) if prev else 0, types=len(model["types"]) - 1,
                relations=len(model["relations"]), first=prev is None)
