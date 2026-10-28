"""Writing: create, edit, steps, notes, storno — with the rules a system of record needs.

* Every change is a new entry in the change log (append-only). Nothing is overwritten
  without a trace.
* Issued documents (invoices) are locked: amounts, dates, parties and numbers cannot be
  changed afterwards; they can only be cancelled (storno) with a reason. Payments, status
  and notes stay possible.
* Records other records depend on cannot be deleted.
* Formulas, defaults and numbering learned from the data fill in what is predictable.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from . import lexicon
from .store import dumps, loads, now_iso
from .text import fold, norm_key, norm_name, tokens
from .values import _EMAIL, add_months, as_date, iban_ok, interval_months, parse_date, parse_duration, parse_number, period_text

LOCKED_CONCEPTS = {"rechnung"}


class OpError(Exception):
    pass


# --- parsing user input -------------------------------------------------------------------------

def parse_input(rt, attr: dict, raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if raw == "":
            return None
    k = attr["kind"]
    if k in ("number", "money"):
        x = parse_number(str(raw), "de")
        if x is None:
            x = parse_number(str(raw), "en")
        if x is None:
            raise OpError(f"„{raw}“ ist keine Zahl")
        return round(x, 2) if k == "money" else x
    if k == "percent":
        s = str(raw).replace("%", "").strip()
        x = parse_number(s, "de")
        if x is None:
            raise OpError(f"„{raw}“ ist kein Prozentwert")
        return x / 100 if x > 1 else x
    if k == "duration":
        x = parse_number(str(raw).split()[0], "de")
        if x is None:
            raise OpError(f"„{raw}“ ist keine Anzahl Tage")
        return int(x)
    if k == "date":
        d = parse_date(str(raw))
        if d is None:
            raise OpError(f"„{raw}“ ist kein Datum")
        return (d.date() if isinstance(d, datetime) else d).isoformat()
    if k == "datetime":
        s = str(raw).replace("T", " ")
        d = parse_date(s) or parse_date(str(raw)[:10])
        if d is None:
            raise OpError(f"„{raw}“ ist kein Zeitpunkt")
        return d.isoformat(timespec="minutes") if isinstance(d, datetime) else d.isoformat()
    if k == "bool":
        return str(raw).lower() in ("1", "on", "true", "ja", "yes", "x")
    if k == "email":
        if not _EMAIL.match(str(raw)):
            raise OpError(f"„{raw}“ ist keine E-Mail-Adresse")
        return str(raw)
    if k == "iban":
        s = re.sub(r"\s+", "", str(raw)).upper()
        if not iban_ok(s):
            raise OpError(f"„{raw}“ ist keine gültige IBAN (Prüfziffer)")
        return s
    if k == "zip":
        d = re.sub(r"\D", "", str(raw))
        return d.zfill(5) if 4 <= len(d) <= 5 else str(raw)
    if k == "ref":
        if isinstance(raw, int) or (isinstance(raw, str) and raw.isdigit() and int(raw) in rt.by_id):
            rid = int(raw)
            if rt.by_id[rid]["type"] not in (attr.get("refs") or [attr.get("ref")]):
                raise OpError("Verweis auf falschen Datensatz")
            return rid
        # typed name: resolve against the target types
        name = norm_name(raw)
        for tid in attr.get("refs") or [attr.get("ref")]:
            for r in rt.records.get(tid, []):
                if norm_name(rt.title(r["id"])) == name or norm_key(rt.title(r["id"])) == norm_key(raw):
                    return r["id"]
        raise OpError(f"„{raw}“ nicht gefunden – bitte aus der Liste wählen")
    return str(raw)


# --- formulas -------------------------------------------------------------------------------------

def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def eval_formula(rt, f: dict, data: dict):
    op = f["op"]
    try:
        if op in ("mul", "add", "sub"):
            a, b = (_num(data.get(x)) for x in f["args"])
            if a is None or b is None:
                return None
            return round(a * b if op == "mul" else a + b if op == "add" else a - b, 2)
        if op == "scale":
            a = _num(data.get(f["args"][0]))
            return None if a is None else round(a * f["k"], 2)
        if op in ("date_add", "date_default"):
            d = as_date(data.get(f["args"][0]))
            return None if d is None else (d.fromordinal(d.toordinal() + int(f["days"]))).isoformat()
        if op == "period_next":
            last = as_date(data.get(f["args"][0]))
            k = interval_months(data.get(f["args"][1])) if len(f["args"]) > 1 else f.get("months")
            return None if not last or not k else period_text(add_months(last, k), f.get("like"))
        if op == "date_add_ref":
            d = as_date(data.get(f["args"][0]))
            target = rt.by_id.get(data.get(f["ref"]))
            if d is None or not target:
                return None
            n = parse_duration(target["data"].get(f["ref_attr"]))
            if n is None:
                return None
            return d.fromordinal(d.toordinal() + int(n)).isoformat()
    except (TypeError, ValueError, KeyError, OverflowError):
        return None
    return None


def apply_formulas(rt, spec: dict, data: dict, given: set) -> list[str]:
    """Fill formula targets the user did not type. Returns the attribute ids that were computed."""
    done = []
    for _ in range(3):  # chains: MwSt from Netto, then Brutto from Netto + MwSt
        for f in spec.get("formulas") or []:
            if f["op"] == "sum_children" or f["attr"] in given:
                continue
            if f.get("on_change") and data.get(f["attr"]) is not None and not set(f["args"]) & given:
                continue  # "next maintenance" moves only when the maintenance is entered
            v = eval_formula(rt, f, data)
            if v is not None and data.get(f["attr"]) != v:
                data[f["attr"]] = v
                if f["attr"] not in done:
                    done.append(f["attr"])
    return done


def next_number(rt, spec: dict, today: date | None = None) -> str | None:
    nb = spec.get("numbering")
    if not nb:
        return None
    today = today or date.today()
    from .behavior import find_numbering

    fresh = find_numbering(spec, rt.records.get(spec["id"], []), today)
    return (fresh or nb)["next"]


def prefill(rt, spec: dict, today: date | None = None) -> dict:
    """What a new record of this type probably looks like."""
    today = today or date.today()
    data = {}
    for aid, d in (spec.get("defaults") or {}).items():
        data[aid] = d["value"]
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    if proc:
        a = rt.attr(spec["id"], proc["start"]["attr"])
        data[proc["start"]["attr"]] = today.isoformat() if a["kind"] == "date" else datetime.now().isoformat(timespec="minutes")
        st = proc.get("status")
        if st and st.get("initial"):
            data[st["attr"]] = st["initial"]
    num = next_number(rt, spec, today)
    if num and spec.get("key"):
        data[spec["key"]] = num
    apply_formulas(rt, spec, data, set())
    return data


# --- locks ----------------------------------------------------------------------------------------

def lock_state(rt, spec: dict, rec: dict) -> dict | None:
    """Issued documents are locked (GoBD): only payments, notes and storno remain possible. A
    draft made here is not issued yet and stays free."""
    from .billing import is_draft

    if spec.get("concept") not in LOCKED_CONCEPTS:
        return None
    key = spec.get("key")
    if is_draft(rec) or not key or rec["data"].get(key) is None:
        return None
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    editable = set()
    if proc:
        for st in proc["steps"]:
            for s in [st] + st.get("also", []):
                if s["source"] == "own":
                    editable.add(s["attr"])
    for a in spec["attrs"]:
        if a.get("role") in ("notes",):
            editable.add(a["id"])
    meta = rec.get("meta") or {}
    cancelled = bool(meta.get("storno_by") or meta.get("storno_of"))
    return dict(editable=set() if cancelled else editable, cancelled=cancelled,
                reason="Ausgestellte Rechnung: Nummer, Datum, Kunde und Beträge sind festgeschrieben – "
                       "Korrektur nur per Storno. Zahlungseingang und Notizen lassen sich weiter eintragen.")


def _parent_lock(rt, spec: dict, rec: dict) -> dict | None:
    """Lines of an issued invoice are as fixed as the invoice."""
    if spec.get("kind") != "line":
        return None
    for a in spec["attrs"]:
        if a["kind"] == "ref":
            parent = rt.by_id.get(rec["data"].get(a["id"]))
            if parent:
                pspec = rt.spec(parent["type"])
                full = rt.store.record(parent["id"])
                if pspec and full and lock_state(rt, pspec, full):
                    return dict(editable=set(), reason="Position einer ausgestellten Rechnung: festgeschrieben.")
    return None


# --- writes -----------------------------------------------------------------------------------------

def _write_refs_and_search(rt, c, rid: int, spec: dict, data: dict):
    from .grow import record_text, record_title

    c.execute("DELETE FROM refs WHERE from_id=? AND kind='ref'", (rid,))
    for a in spec["attrs"]:
        if a["kind"] == "ref" and isinstance(data.get(a["id"]), int):
            c.execute("INSERT OR IGNORE INTO refs(from_id,attr,to_id,kind) VALUES(?,?,?,?)", (rid, a["id"], data[a["id"]], "ref"))
    c.execute("DELETE FROM search WHERE record_id=?", (rid,))
    c.execute("INSERT INTO search(body, record_id, type) VALUES(?,?,?)", (record_text(spec, data, rt.titles), rid, spec["id"]))


def _clean(spec: dict, data: dict) -> dict:
    keep = {a["id"] for a in spec["attrs"] if not a.get("virtual")}
    return {k: v for k, v in data.items() if k in keep and v is not None}


def create(rt, tid: str, raw: dict, actor: str, lines: list[dict] | None = None, line_type: str | None = None) -> int:
    rt.ensure()
    spec = rt.spec(tid)
    if not spec:
        raise OpError("Unbekannte Art")
    data, given, errors = {}, set(), []
    for a in spec["attrs"]:
        if a["id"] in raw and not a.get("virtual"):
            try:
                v = parse_input(rt, a, raw[a["id"]])
            except OpError as e:
                errors.append(f"{a['name']}: {e}")
                continue
            if v is not None:
                data[a["id"]] = v
                given.add(a["id"])
    if errors:
        raise OpError("; ".join(errors))
    from .billing import derive, is_invoice
    copies, _why = derive(rt, spec, data)
    for aid, v in copies.items():
        if aid not in given and v is not None:
            data[aid] = v
            given.add(aid)  # taken over from the order (VAT by the articles' rates) beats a learned formula
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == tid), None)
    if proc and data.get(proc["start"]["attr"]) is None:
        # what is made here starts now (the form proposes the same)
        sa = next((a for a in spec["attrs"] if a["id"] == proc["start"]["attr"]), None)
        if sa and sa["kind"] in ("date", "datetime"):
            data[proc["start"]["attr"]] = date.today().isoformat() if sa["kind"] == "date" else \
                datetime.now().isoformat(timespec="minutes")
    draft = is_invoice(spec)
    key = spec.get("key")
    if draft:
        data.pop(key, None)  # the number comes when the invoice is issued
    elif key and data.get(key) is None:
        n = next_number(rt, spec)
        if n:
            data[key] = n
    if key and data.get(key) is not None:
        dup = [r for r in rt.records.get(tid, []) if norm_key(r["data"].get(key)) == norm_key(data[key])]
        if dup:
            raise OpError(f"{next(a['name'] for a in spec['attrs'] if a['id'] == key)} „{data[key]}“ gibt es schon")
    computed = apply_formulas(rt, spec, data, given)
    data = _clean(spec, data)
    ts = now_iso()
    with rt.store.tx() as c:
        meta = dict(w={aid: ["user", ts] for aid in data}, computed=computed)
        if draft:
            meta["draft"] = True
        cur = c.execute("INSERT INTO records(type,data,meta,origin,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (tid, dumps(data), dumps(meta), "user", ts, ts))
        rid = cur.lastrowid
        idents = [f"u:{rid}"]
        if key and data.get(key) is not None:
            idents.append("k:" + norm_key(data[key]))
        for a in spec["attrs"]:
            if a["kind"] == "email" and data.get(a["id"]) and spec["kind"] == "master":
                idents.append("e:" + str(data[a["id"]]).casefold())
        if spec.get("title") and data.get(spec["title"]) and spec["kind"] == "master":
            idents.append("n:" + norm_name(data[spec["title"]]))
        c.executemany("INSERT OR IGNORE INTO idents(type,ident,record_id) VALUES(?,?,?)", [(tid, i, rid) for i in idents])
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                  (rid, ts, actor, "create", "angelegt" + (f"; berechnet: {len(computed)} Feld(er)" if computed else "")))
        _write_refs_and_search(rt, c, rid, spec, data)
        if lines and line_type:
            lspec = rt.spec(line_type)
            parent_ref = next((a["id"] for a in lspec["attrs"] if a["kind"] == "ref" and a.get("ref") == tid), None)
            for ln in lines:
                ldata, lgiven = {}, set()
                for a in lspec["attrs"]:
                    if a["id"] in ln and a["id"] != parent_ref and not a.get("virtual"):
                        v = parse_input(rt, a, ln[a["id"]])
                        if v is not None:
                            ldata[a["id"]] = v
                            lgiven.add(a["id"])
                if not ldata:
                    continue
                ldata[parent_ref] = rid
                for aid, v in derive(rt, lspec, ldata)[0].items():
                    if aid not in lgiven and v is not None:
                        ldata[aid] = v  # the unit price comes from the article, as it always did
                apply_formulas(rt, lspec, ldata, lgiven)
                ldata = _clean(lspec, ldata)
                cur = c.execute("INSERT INTO records(type,data,meta,origin,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                                (line_type, dumps(ldata), dumps(dict(w={k: ["user", ts] for k in ldata})), "user", ts, ts))
                lid = cur.lastrowid
                c.execute("INSERT INTO idents(type,ident,record_id) VALUES(?,?,?)", (line_type, f"u:{lid}", lid))
                c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                          (lid, ts, actor, "create", f"Position zu {rt.title(rid) if rid in rt.titles else '#' + str(rid)}"))
                _write_refs_and_search(rt, c, lid, lspec, ldata)
        rt.bump(c)
        for aid in given:
            rt.store.flux_add(f"attr:{aid}", 1.0, c=c)
        rt.store.flux_add(f"type:{tid}", 2.0, c=c)
    return rid


def update(rt, rid: int, raw: dict, actor: str, note: str | None = None, kind: str = "edit",
           allow: set | None = None) -> list[str]:
    """Apply edits. Returns names of changed attributes. `allow`: attributes an action (paid,
    reminded) may set on a locked document."""
    rt.ensure()
    rec = rt.store.record(rid)
    if not rec or rec["deleted"]:
        raise OpError("Datensatz nicht gefunden")
    spec = rt.spec(rec["type"])
    lock = lock_state(rt, spec, rec) or _parent_lock(rt, spec, rec)
    if lock and allow:
        lock = dict(lock, editable=set(lock["editable"]) | set(allow))
    data = dict(rec["data"])
    given, errors, changed = set(), [], []
    for a in spec["attrs"]:
        if a["id"] not in raw or a.get("virtual"):
            continue
        try:
            v = parse_input(rt, a, raw[a["id"]])
        except OpError as e:
            errors.append(f"{a['name']}: {e}")
            continue
        if data.get(a["id"]) == v:
            continue
        if lock and a["id"] not in lock["editable"]:
            errors.append(f"{a['name']}: festgeschrieben (Storno statt Änderung)")
            continue
        given.add(a["id"])
        if v is None:
            data.pop(a["id"], None)
        else:
            data[a["id"]] = v
    if errors:
        raise OpError("; ".join(errors))
    if not given:
        return []
    computed = apply_formulas(rt, spec, data, given) if not lock else []
    autos = _automations(rt, spec, rec["data"], data, given)
    data = _clean(spec, data)
    ts = now_iso()
    meta = rec["meta"] or {}
    w = meta.get("w", {})
    with rt.store.tx() as c:
        for aid in sorted(set(given) | set(computed) | set(x for x, _ in autos)):
            old, new = rec["data"].get(aid), data.get(aid)
            if old == new:
                continue
            k = kind if aid in given else "auto"
            why = note if aid in given else next((t for x, t in autos if x == aid), "berechnet")
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                      (rid, ts, actor if aid in given else "Physarum", k, aid, dumps(old), dumps(new), why))
            prev = w.get(aid)
            # remember what the files said before the person changed it: a later file that
            # says the same again must not undo the change
            base = old if (prev is None or prev[0] == "import") else (prev[2] if len(prev) > 2 else None)
            w[aid] = ["user" if aid in given else "auto", ts, base]
            changed.append(aid)
            rt.store.flux_add(f"attr:{aid}", 1.0, c=c)
        meta["w"] = w
        c.execute("UPDATE records SET data=?, meta=?, updated_at=? WHERE id=?", (dumps(data), dumps(meta), ts, rid))
        _write_refs_and_search(rt, c, rid, spec, data)
        rt.bump(c)
    return changed


def _automations(rt, spec, before: dict, data: dict, given: set) -> list[tuple[str, str]]:
    """Learned rules the user switched on ("Trampelpfade"): when a step date is set, set the status."""
    out = []
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    if not proc or not proc.get("status"):
        return out
    on = rt.store.decisions("auto")
    for au in proc["status"].get("autos", []):
        key = f"{spec['id']}|{au['step']}|{au['attr']}"
        if on.get(key) != "on" or au["attr"] in given:
            continue
        st = next((s for s in proc["steps"] if s["id"] == au["step"]), None)
        if not st:
            continue
        attrs = [s["attr"] for s in [st] + st.get("also", []) if s["source"] == "own"]
        if any(a in given and data.get(a) and not before.get(a) for a in attrs):
            data[au["attr"]] = au["value"]
            out.append((au["attr"], f"Regel: {au['text']} (gelernt aus {au['n']} Fällen)"))
    return out


def set_step(rt, rid: int, attr: str, when: str | None, actor: str) -> list[str]:
    rt.ensure()
    rec = rt.by_id.get(rid)
    raw = {attr: when or date.today().isoformat()}
    allow = {attr}
    if rec:
        proc = next((p for p in rt.model.get("processes", []) if p["type"] == rec["type"]), None)
        st = (proc or {}).get("status")
        if proc and st:
            stage = next((i for i, s in enumerate(proc["steps"], start=1)
                          if any(x["source"] == "own" and x["attr"] == attr for x in [s] + s.get("also", []))), None)
            vals = [v for v, k in (st.get("map") or {}).items() if k == stage]
            cur = str(rec["data"].get(st["attr"]))
            if stage and len(vals) == 1 and cur not in (st.get("negative") or []) and (st["map"].get(cur, 0) or 0) < stage:
                raw[st["attr"]] = vals[0]  # "paid" also means status "bezahlt"
                allow.add(st["attr"])
    return update(rt, rid, raw, actor, note="Schritt erledigt", allow=allow)


def revert(rt, rid: int, attrs: list[str], actor: str) -> list[str]:
    """Undo the last change of these attributes (the "Rückgängig" after a quick action)."""
    rt.ensure()
    raw = {}
    for aid in attrs:
        row = rt.store.q1("SELECT old FROM changes WHERE record_id=? AND attr=? ORDER BY id DESC LIMIT 1", (rid, aid))
        if row is not None:
            old = loads(row["old"]) if row["old"] else None
            rec = rt.store.record(rid)
            if not rec or not rt.spec(rec["type"]):
                raise OpError("Datensatz nicht gefunden")
            a = next((x for x in rt.spec(rec["type"])["attrs"] if x["id"] == aid), None)
            raw[aid] = "" if old is None else (_to_input(a, old) if a else old)
    if not raw:
        return []
    return update(rt, rid, raw, actor, note="rückgängig gemacht", allow=set(raw))


def _to_input(attr: dict, v):
    if attr["kind"] in ("money", "number") and isinstance(v, (int, float)):
        return str(v).replace(".", ",")
    if attr["kind"] == "percent" and isinstance(v, (int, float)):
        return f"{v * 100:g}".replace(".", ",")
    return v


def add_note(rt, rid: int, text: str, actor: str):
    text = (text or "").strip()
    if not text:
        return
    ts = now_iso()
    with rt.store.tx() as c:
        c.execute("INSERT INTO notes(record_id,ts,actor,text) VALUES(?,?,?,?)", (rid, ts, actor, text))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)", (rid, ts, actor, "note", text[:200]))
        rt.bump(c)


def storno(rt, rid: int, reason: str, actor: str) -> int | None:
    """Cancel. An issued invoice is cancelled by a cancellation invoice of its own (returns its
    id); a draft is simply discarded; anything else gets its negative status."""
    from .billing import BillingError, cancel, is_draft, is_invoice

    rt.ensure()
    rec = rt.store.record(rid)
    if not rec or rec["deleted"]:
        raise OpError("Datensatz nicht gefunden")
    spec = rt.spec(rec["type"])
    if not reason or not reason.strip():
        raise OpError("Bitte einen Grund für das Storno angeben")
    if is_invoice(spec) and is_draft(rec):
        delete(rt, rid, actor, reason=f"Entwurf verworfen: {reason}")
        return None
    if is_invoice(spec) and lock_state(rt, spec, rec):
        try:
            return cancel(rt, rid, reason, actor)
        except BillingError as e:
            raise OpError(str(e)) from e
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == spec["id"]), None)
    st = (proc or {}).get("status")
    value = next(iter(st["negative"]), None) if st and st.get("negative") else None
    ts = now_iso()
    with rt.store.tx() as c:
        data = dict(rec["data"])
        if value and st:
            old = data.get(st["attr"])
            data[st["attr"]] = value
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                      (rid, ts, actor, "storno", st["attr"], dumps(old), dumps(value), reason))
        meta = rec["meta"] or {}
        meta["storno"] = dict(ts=ts, actor=actor, reason=reason)
        c.execute("UPDATE records SET meta=? WHERE id=?", (dumps(meta), rid))
        if not (value and st):
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                      (rid, ts, actor, "storno", reason))
        c.execute("UPDATE records SET data=?, updated_at=? WHERE id=?", (dumps(data), ts, rid))
        c.execute("INSERT INTO notes(record_id,ts,actor,text) VALUES(?,?,?,?)", (rid, ts, actor, f"Storniert: {reason}"))
        rt.bump(c)
    return None


def delete(rt, rid: int, actor: str, reason: str | None = None):
    """Delete what was made here; hide (with a reason) what came from a file – it does not come
    back with the next growth, and it can be shown again."""
    rt.ensure()
    rec = rt.store.record(rid)
    if not rec or rec["deleted"]:
        raise OpError("Datensatz nicht gefunden")
    spec = rt.spec(rec["type"])
    if lock_state(rt, spec, rec):
        raise OpError("Ausgestellte Rechnungen können nicht gelöscht werden – bitte stornieren.")
    users = [b for b in rt.backrefs.get(rid, []) if b[2] == "ref" and b[0] in rt.by_id]
    if users:
        raise OpError(f"Wird von {len(users)} anderen Datensätzen verwendet und kann deshalb nicht gelöscht werden.")
    imported = rec.get("origin") == "import" or bool(rt.store.q1(
        "SELECT 1 AS x FROM changes WHERE record_id=? AND kind='import' LIMIT 1", (rid,)))
    if imported and not (reason or "").strip():
        raise OpError("Dieser Datensatz stammt aus einer Datei. Er wird nicht gelöscht, sondern ausgeblendet – "
                      "bitte einen Grund angeben.")
    ts = now_iso()
    with rt.store.tx() as c:
        c.execute("UPDATE records SET deleted=1, updated_at=? WHERE id=?", (ts, rid))
        if imported:
            idents = [r["ident"] for r in c.execute("SELECT ident FROM idents WHERE record_id=?", (rid,)).fetchall()]
            for i in idents:
                rt.store.decide("hidden_record", f"{rec['type']}|{i}", reason.strip(), actor, c=c)
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                      (rid, ts, actor, "hide", f"ausgeblendet: {reason.strip()}"))
        else:
            c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                      (rid, ts, actor, "delete", reason or "gelöscht"))
        c.execute("DELETE FROM search WHERE record_id=?", (rid,))
        c.execute("DELETE FROM refs WHERE from_id=?", (rid,))
        rt.bump(c)


def unhide(rt, rid: int, actor: str):
    rec = rt.store.record(rid)
    if not rec:
        raise OpError("Datensatz nicht gefunden")
    ts = now_iso()
    with rt.store.tx() as c:
        idents = [r["ident"] for r in c.execute("SELECT ident FROM idents WHERE record_id=?", (rid,)).fetchall()]
        c.executemany("DELETE FROM decisions WHERE kind='hidden_record' AND subject=?",
                      [(f"{rec['type']}|{i}",) for i in idents])
        c.execute("UPDATE records SET deleted=0, updated_at=? WHERE id=?", (ts, rid))
        c.execute("INSERT INTO changes(record_id,ts,actor,kind,note) VALUES(?,?,?,?,?)",
                  (rid, ts, actor, "unhide", "wieder eingeblendet"))
        rt.bump(c)


def apply_stale(rt, tid: str, actor: str, rids: set | None = None) -> int:
    """Take over what the money says ("paid according to the bank statement") – in one go,
    every change in the record's history. With rids: only for these records."""
    rt.ensure()
    proc = next((p for p in rt.model.get("processes", []) if p["type"] == tid), None)
    st = (proc or {}).get("status")
    items = (getattr(rt, "stale", {}) or {}).get(tid) or (st or {}).get("stale") or []
    if rids is not None:
        items = [s for s in items if s["rid"] in rids]
    if not st or not items:
        return 0
    ts = now_iso()
    n = 0
    with rt.store.tx() as c:
        for s in items:
            row = c.execute("SELECT data, meta FROM records WHERE id=? AND deleted=0", (s["rid"],)).fetchone()
            if not row:
                continue
            data, meta = loads(row["data"]) or {}, loads(row["meta"]) or {}
            if str(data.get(st["attr"])) != s["was"]:
                continue
            step = next((x for x in proc["steps"] if x["id"] == s["step"]), None)
            own = next((x["attr"] for x in [step] + step.get("also", []) if x["source"] == "own"), None) if step else None
            changes = [(st["attr"], data.get(st["attr"]), s["value"])]
            data[st["attr"]] = s["value"]
            when = s.get("when") or _child_date(rt, step, s["rid"])
            if own and when and not data.get(own):
                changes.append((own, None, when))
                data[own] = when
            w = meta.setdefault("w", {})
            for aid, _o, _n in changes:
                w[aid] = ["auto", ts]
            c.execute("UPDATE records SET data=?, meta=?, updated_at=? WHERE id=?", (dumps(data), dumps(meta), ts, s["rid"]))
            c.executemany("INSERT INTO changes(record_id,ts,actor,kind,attr,old,new,note) VALUES(?,?,?,?,?,?,?,?)",
                          [(s["rid"], ts, actor, "auto", aid, dumps(o), dumps(nv),
                            "laut Kontoauszug bezahlt (Abgleich nach Betrag)") for aid, o, nv in changes])
            n += 1
        rt.bump(c)
    return n


def _child_date(rt, step, rid) -> str | None:
    if not step:
        return None
    best = None
    for s in [step] + step.get("also", []):
        if s["source"] != "child":
            continue
        if s["rel_kind"] == "own_ref":
            own = rt.by_id.get(rid, {}).get("data", {}).get(s["rel_attr"])
            srcs = [own] if isinstance(own, int) else []
        elif s["rel_kind"] == "mention":
            srcs = rt.mentions.get(s["rel_attr"], {}).get(rid, [])
        else:
            srcs = [c["id"] for c in rt.records.get(s["type"], []) if c["data"].get(s["rel_attr"]) == rid]
        for x in srcs:
            d = as_date(rt.by_id.get(x, {}).get("data", {}).get(s["attr"]))
            if d and (best is None or d < best):
                best = d
    return best.isoformat() if best else None
