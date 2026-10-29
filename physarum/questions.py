"""Questions instead of configuration.

Where the evidence is weak the system asks, like a new colleague would: few questions,
each with its reasons, sorted by how much the answer changes. Every answer is stored as a
decision that all future growth respects, so nothing is asked twice.

Only what the owner knows and Physarum cannot is asked: whether two entries are the same
customer, whether a transfer pays an invoice. How the files are read (two lists or one, a
column as text or as a link) Physarum decides itself; such a decision is a hint on the list,
with one button to turn it around.
"""
from __future__ import annotations

from .grow import record_title
from .lexicon import dative_plural
from .payments import BY_AMOUNT, CONFIRMED
from .store import Store, dumps, loads, now_iso, pair_subject


def _rec_brief(t, g, limit=4) -> list[list[str]]:
    out = []
    for a in t.attrs:
        v = g.values.get(a.aid)
        if v is None or a.role in ("notes",):
            continue
        out.append([a.name, str(v)[:60]])
        if len(out) >= limit:
            break
    return out


def _member_examples(c, t: dict, member: dict, limit: int = 3) -> list[str]:
    """A few entries that came from this file, so the owner sees what is meant."""
    tables = set(member.get("tables") or [])
    out = []
    if not tables:
        return out
    for r in c.execute("SELECT id, data, meta FROM records WHERE type=? AND deleted=0 AND merged_into IS NULL ORDER BY id",
                       (t["id"],)):
        prov = (loads(r["meta"]) or {}).get("prov") or {}
        if any(len(p) > 1 and p[1] in tables for ps in prov.values() for p in ps):
            out.append(record_title(t, loads(r["data"]) or {}, r["id"]))
            if len(out) >= limit:
                break
    return out


def collect_questions(store: Store, model: dict, asks: list[dict], er: list[dict], c, matches: list | None = None,
                      titles: dict | None = None) -> int:
    ts = now_iso()
    found = {}
    titles = titles or {}
    from .values import display
    said = store.decisions("payment_match")
    for m in matches or []:
        bid = _stable_ident(c, m["bank_type"], m["bank"])
        iids = [_stable_ident(c, m["invoice_type"], i) for i in m["invoices"]]
        if not bid or not all(iids):
            continue
        subj_dec = f"{m['bank_type']}|{bid}|{m['invoice_type']}|{','.join(iids)}"
        if said.get(subj_dec) == "no":
            continue  # "this transfer is something else" – asked once
        inv_txt = " und ".join(titles.get(i, f"#{i}") for i in m["invoices"])
        found[f"payment_match|{subj_dec}"] = dict(
            kind="payment_match", subject=f"payment_match|{subj_dec}", impact=8 + m["amount"] / 200,
            payload=dict(text=f"{display(m['amount'], 'money')} von {m['payer'] or 'unbekannt'} am {display(m['when'], 'date')} "
                              f"– gehört das zu {inv_txt}?",
                         detail=f"Im Verwendungszweck steht keine Rechnungsnummer. {m['how']}.",
                         records=[m["bank"]] + m["invoices"], exact=m["exact"],
                         decision=dict(kind="payment_match", subject=subj_dec),
                         options=[["yes", "Ja, zuordnen"], ["no", "Nein"]]))
    for a in asks:  # how to read the files: decided, shown as a hint on the list
        if a.get("kind") == "relation":
            r = a["rel"]
            unresolved = list(dict.fromkeys(str(v) for v in r.unresolved.values()))[:5]
            subj = f"relation|{a['key']}"
            found[subj] = dict(kind="relation", subject=subj, impact=len(r.unresolved) + r.hits * (1 - r.inclusion),
                               status="hint",
                               payload=dict(text=f"„{r.attr.name}“ ist Text geblieben: nur {round(r.inclusion * 100)} % der "
                                                 f"Werte sind {r.dst.plural}.",
                                            detail="Nicht gefunden: " + ", ".join(unresolved),
                                            decision=dict(kind="relation", subject=a["key"]), types=[r.src.tid],
                                            options=[["yes", f"Mit {r.dst.plural} verknüpfen"], ["no", "Text lassen"]]))
        else:
            ma, mb, sim = a["a"], a["b"], a["sim"]
            sigs = sorted(a["sig"])
            if len(sigs) < 2:
                continue  # two files known by the same signature: whatever is decided holds for both alike
            subj = "same_type|" + pair_subject(*sigs)
            cols_a = [c.name for c in ma.cols][:8]
            cols_b = [c.name for c in mb.cols][:8]
            found[subj] = dict(kind="same_type", subject=subj, impact=(ma.n + mb.n) * 0.5, status="hint",
                               payload=dict(text=f"Zwei Listen: {_where(ma.label, ma.name_hint)} und "
                                                 f"{_where(mb.label, mb.name_hint)}.",
                                            detail=f"Ähnlich, weil: {sim['reason']}. Spalten: {', '.join(cols_a)} — bzw. "
                                                   f"{', '.join(cols_b)}.",
                                            decision=dict(kind="same_type", subject=pair_subject(*sigs)),
                                            types=a.get("types") or [],
                                            options=[["same", "Zu einer Liste zusammenlegen"], ["different", "Getrennt lassen"]]))
    for q in er:
        t = q["type"]
        ta = q["a"].values.get(t.title.aid) if t.title else None
        tb = q["b"].values.get(t.title.aid) if t.title else None
        subj = f"same_record|{q['key']}"
        why = ", ".join(q["pro"]) or "Name fast gleich"
        against = ", ".join(q["con"])
        if t.key is not None and q["a"].values.get(t.key.aid) and q["b"].values.get(t.key.aid):
            ka, kb = q["a"].values.get(t.key.aid), q["b"].values.get(t.key.aid)
            if str(ka) != str(ta):
                ta, tb = f"{ka} · {ta}" if ta else ka, f"{kb} · {tb}" if tb else kb  # numbers tell twins apart
        if q.get("text"):
            text = q["text"]
        elif str(ta) == str(tb):
            text = f"„{ta}“ gibt es zweimal – ist das derselbe {t.name}?"
        else:
            text = f"Ist „{ta}“ derselbe {t.name} wie „{tb}“?"
        found[subj] = dict(kind="same_record", subject=subj,
                           impact=(len(q["a"].protos) + len(q["b"].protos)) * (1.5 if q["pro"] else 0.6),
                           payload=dict(text=text,
                                        detail=f"Dafür: {why}." + (f" Dagegen: {against}." if against else ""),
                                        a=_rec_brief(t, q["a"]), b=_rec_brief(t, q["b"]), type=t.tid,
                                        idents=[sorted(q["a"].idents)[:3], sorted(q["b"].idents)[:3]],
                                        decision=dict(kind="same_record", subject=q["key"]),
                                        options=[["same", "Ja, zusammenführen"], ["different", "Nein, verschieden"]]))
    # merges that rest on structure only: a hint, so that they can be undone
    kept = store.decisions("same_type")
    for t in model["types"]:
        for m in t.get("merge_log", []):
            if "Spalten" in (m.get("reason") or "") and "Nummern" not in m["reason"] and "Namen" not in m["reason"]:
                subj = f"confirm|{t['id']}|{m['obs']}"
                member = next((x for x in t["members"] if x["label"] == m["obs"]), {})
                into = next((x for x in t["members"] if x["label"] == m["into"]), {})
                if (member.get("source") and member.get("source") == into.get("source")) or t.get("concept"):
                    continue  # one sheet per fitter or per year, two banks' statements: one list by design
                if member.get("sig") and into.get("sig") and pair_subject(member["sig"], into["sig"]) in kept:
                    continue  # the owner said so
                n = member.get("rows")
                ex_a, ex_b = _member_examples(c, t, member), _member_examples(c, t, into)
                examples = ""
                if ex_a and ex_b:
                    examples = (f" Zum Beispiel aus „{m['obs']}“: {', '.join(ex_a)} – aus „{m['into']}“: {', '.join(ex_b)}.")
                found[subj] = dict(kind="confirm_merge", subject=subj, impact=5, status="hint",
                                   payload=dict(text=f"{n or 'Die'} {t['plural']} aus {_where(m['obs'], dative=True)} stehen mit den "
                                                     f"{dative_plural(t['plural'])} aus {_where(m['into'], dative=True)} in einer Liste.",
                                                detail=f"Grund: {m['reason']}; kein Eintrag steht in beiden Dateien.{examples}",
                                                decision=dict(kind="same_type", subject=None, obs=m["obs"], into=m["into"],
                                                              type=t["id"]), types=[t["id"]],
                                                options=[["split", "Getrennt führen"], ["ok", "Zusammen lassen"]]))
    existing = {r["subject"]: r for r in c.execute("SELECT * FROM questions").fetchall()}
    for subj, q in found.items():
        status = q.get("status", "open")
        if subj in existing:
            if existing[subj]["status"] in ("obsolete", "open", "hint"):  # an old question about the files is a hint now
                c.execute("UPDATE questions SET status=?, payload=?, impact=? WHERE subject=?",
                          (status, dumps(q["payload"]), q["impact"], subj))
            continue
        c.execute("INSERT INTO questions(kind,subject,payload,impact,status,created_at) VALUES(?,?,?,?,?,?)",
                  (q["kind"], subj, dumps(q["payload"]), q["impact"], status, ts))
    for subj, r in existing.items():
        if r["status"] in ("open", "hint") and subj not in found:
            c.execute("UPDATE questions SET status='obsolete' WHERE subject=?", (subj,))
    return sum(1 for _ in c.execute("SELECT 1 FROM questions WHERE status='open'").fetchall())


def _stable_ident(c, tid: str, rid: int) -> str | None:
    rows = [r["ident"] for r in c.execute("SELECT ident FROM idents WHERE type=? AND record_id=?", (tid, rid)).fetchall()]
    for prefix in ("k:", "h:", "l:", "e:", "r:", "u:", "n:"):
        for i in sorted(rows):
            if i.startswith(prefix):
                return i
    return None


CONSEQUENCES = {
    ("same_record", "same"): "Aus zwei Einträgen wird einer – Aufträge, Rechnungen und Notizen beider hängen dann daran.",
    ("same_record", "different"): "Beide bleiben getrennt; diese Frage kommt nicht wieder.",
    ("same_type", "same"): "Beide werden eine Liste.",
    ("same_type", "different"): "Zwei getrennte Listen.",
    ("confirm_merge", "ok"): "Bleibt eine gemeinsame Liste.",
    ("confirm_merge", "split"): "Wird eine eigene Liste (der Name lässt sich ändern).",
    ("relation", "yes"): "Die Werte werden zu Verknüpfungen: man kann hin- und herspringen.",
    ("relation", "no"): "Die Spalte bleibt einfacher Text.",
    ("payment_match", "yes"): "Die Zahlung gilt für diese Rechnung(en) – sie werden bezahlt bzw. teilbezahlt.",
    ("payment_match", "no"): "Die Zahlung bleibt ohne Rechnung; die Rechnung bleibt offen.",
}


def reopen(store: Store, qid: int):
    """Ask again: the answer is forgotten, the question is open (a hint is a hint again)."""
    with store.tx() as c:
        c.execute("UPDATE questions SET status=CASE WHEN kind IN ('same_type', 'relation', 'confirm_merge') THEN 'hint' "
                  "ELSE 'open' END, answer=NULL, answered_at=NULL, snooze_until=NULL WHERE id=?", (qid,))


def _where(label: str, hint=None, dative: bool = False) -> str:
    """"Stundenzettel_August_2026 › Kortmann" -> "das Blatt „Kortmann“ in „Stundenzettel_August_2026“" – no
    internal labels in a question. With a name for its entries: "die Auftragspositionen aus
    „Aufträge_Großkunden“ (Blatt „2026“)"."""
    what = hint[1] if hint else None  # the plural: "die Kunde" would be wrong, the list's name is not
    if " › " in label:
        file, sheet = label.split(" › ", 1)
        sheet = sheet.split(" + ")[-1]
        if what:
            return f"{'den' if dative else 'die'} {what} aus „{file}“ (Blatt „{sheet}“)"
        return f"{'dem' if dative else 'das'} Blatt „{sheet}“ in „{file}“"
    if what:
        return f"{'den' if dative else 'die'} {what} aus „{label}“"
    return f"{'der' if dative else 'die'} Liste „{label}“"


def hints(store: Store, tid: str | None = None) -> list[dict]:
    """How Physarum read the files where it could have read them otherwise – per list."""
    out = [dict(id=r["id"], kind=r["kind"], subject=r["subject"], **loads(r["payload"]))
           for r in store.q("SELECT * FROM questions WHERE status='hint' ORDER BY impact DESC, id")]
    return [h for h in out if tid is None or tid in (h.get("types") or [])]


def open_questions(store: Store, limit: int | None = None) -> list[dict]:
    rows = store.q("SELECT * FROM questions WHERE status='open' AND (snooze_until IS NULL OR snooze_until < ?) "
                   "ORDER BY impact DESC, id", (now_iso(),))
    out = [dict(id=r["id"], kind=r["kind"], subject=r["subject"], impact=r["impact"], **loads(r["payload"])) for r in rows]
    return out[:limit] if limit else out


def answer(store: Store, qid: int, value: str, actor: str | None = None) -> dict:
    """Store the answer. Returns {'regrow': bool, 'merged': (a, b) | None}."""
    r = store.q1("SELECT * FROM questions WHERE id=?", (qid,))
    if not r:
        return dict(regrow=False)
    payload = loads(r["payload"])
    dec = payload.get("decision") or {}
    result = dict(regrow=False, merged=None)
    with store.tx() as c:
        if value == "later":
            from datetime import datetime, timedelta
            c.execute("UPDATE questions SET snooze_until=? WHERE id=?",
                      ((datetime.now() + timedelta(days=1)).isoformat(timespec="seconds"), qid))
            return result
        if value == "unknown":
            c.execute("UPDATE questions SET status='answered', answer=?, answered_at=? WHERE id=?",
                      (dumps(value), now_iso(), qid))
            return result
        kind = r["kind"]
        if kind == "same_type":
            store.decide("same_type", dec["subject"], value, actor, c=c)
            result["regrow"] = True
        elif kind == "relation":
            store.decide("relation", dec["subject"], value, actor, c=c)
            result["regrow"] = True
        elif kind == "payment_match":
            before = store.decisions("payment_match").get(dec["subject"])
            store.decide("payment_match", dec["subject"], value, actor, c=c)
            if value != "yes" and before == "yes":
                # changed one's mind: the transfer no longer pays these invoices
                recs = payload.get("records") or []
                if len(recs) >= 2:
                    c.executemany("DELETE FROM refs WHERE from_id=? AND to_id=? AND kind='mention' AND how IN (?, ?)",
                                  [(recs[0], i, CONFIRMED, BY_AMOUNT) for i in recs[1:]])
                    store.kv_set("data_version", (store.kv_get("data_version", 0) or 0) + 1, c)
            if value == "yes":
                from .grow import _accepted_matches
                m = store.model()
                rows = _accepted_matches(store, m, c)
                c.executemany("INSERT OR IGNORE INTO refs(from_id,attr,to_id,kind,how) VALUES(?,?,?,?,?)", rows)
                if any(r[1] == "match" for r in rows):
                    result["regrow"] = True  # a new kind of link: the processes must learn it
                store.kv_set("data_version", (store.kv_get("data_version", 0) or 0) + 1, c)
        elif kind == "same_record":
            store.decide("same_record", dec["subject"], value, actor, c=c)
            if value == "same":
                ids = payload.get("idents") or [[], []]
                tid = payload.get("type")
                ra = _rid_for(c, tid, ids[0])
                rb = _rid_for(c, tid, ids[1])
                if ra and rb and ra != rb:
                    from .grow import _merge_record
                    keep, drop = sorted((ra, rb))
                    _merge_record(c, drop, keep, now_iso(), actor or "Mensch", "per Antwort bestätigt")
                    result["merged"] = (keep, drop)
                    store.kv_set("data_version", (store.kv_get("data_version", 0) or 0) + 1, c)
        elif kind == "confirm_merge":
            sig = {m["label"]: m.get("sig") for t in (store.model() or {}).get("types", []) for m in t["members"]}
            pair = (sig.get(dec.get("obs")), sig.get(dec.get("into")))
            if all(pair) and (value == "split" or store.decisions("same_type").get(pair_subject(*pair))):
                store.decide("same_type", pair_subject(*pair), "different" if value == "split" else "same", actor, c=c)
                result["regrow"] = True
        c.execute("UPDATE questions SET status='answered', answer=?, answered_at=? WHERE id=?",
                  (dumps(value), now_iso(), qid))
    return result


def _rid_for(c, tid, idents) -> int | None:
    for i in idents:
        row = c.execute("SELECT record_id FROM idents WHERE type=? AND ident=?", (tid, i)).fetchone()
        if row:
            return row["record_id"]
    return None
