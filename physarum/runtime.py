"""In-memory view of the organism for fast pages: model, records, titles, work.

Everything is rebuilt lazily when the data version or the model version changes.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date, timedelta

from .behavior import apply_virtual
from .grow import _de_date, record_title, record_titles
from .store import Store, loads


class Runtime:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.RLock()
        self._mv = None
        self._dv = None
        self.model: dict | None = None
        self.records: dict[str, list[dict]] = {}
        self.by_id: dict[int, dict] = {}
        self.titles: dict[int, str] = {}
        self.mentions: dict = {}
        self.backrefs: dict[int, list] = {}
        self.outrefs: dict[int, list] = {}
        self.pending_payments: dict[int, dict] = {}
        self.ledger: dict[int, dict] = {}
        self.stale: dict[str, list[dict]] = {}
        self._work = None
        self._work_key = None
        self._net_at = 0.0

    # --- versions ----------------------------------------------------------------------------
    def model_version(self) -> int:
        r = self.store.q1("SELECT MAX(version) AS v FROM models")
        return r["v"] or 0

    def data_version(self) -> int:
        return self.store.kv_get("data_version", 0) or 0

    def bump(self, c=None):
        self.store.kv_set("data_version", self.data_version() + 1, c)

    def ensure(self):
        mv, dv = self.model_version(), self.data_version()
        if mv == self._mv and dv == self._dv and self.model is not None:
            return
        with self.lock:
            if mv == self._mv and dv == self._dv and self.model is not None:
                return
            self.model = self.store.model()
            if self.model is None:
                self._mv, self._dv = mv, dv
                return
            net = self.store.kv_get("network")
            if net and net.get("model_version") == mv:
                self._overlay_network(net)
            self.records = self.store.all_records()
            apply_virtual(self.model, self.records)
            from .behavior import apply_recurring
            apply_recurring(self.model, self.records)
            self.by_id = {r["id"]: r for rs in self.records.values() for r in rs}
            specs = self.specs
            self.titles = record_titles(specs, ((rid, r["type"], r["data"]) for rid, r in self.by_id.items()))
            for rid, r in self.by_id.items():
                if (r.get("meta") or {}).get("draft"):
                    made = _de_date((r.get("created_at") or "")[:10])
                    self.titles[rid] = f"Entwurf vom {made}" if made else "Entwurf"
            self.mentions = defaultdict(lambda: defaultdict(list))
            self.backrefs = defaultdict(list)
            self.outrefs = defaultdict(list)
            by_amount = {}
            from .payments import BY_AMOUNT, CONFIRMED
            for row in self.store.q("SELECT from_id, attr, to_id, kind, how FROM refs"):
                if row["kind"] == "mention" and row["attr"] != "doc":
                    self.mentions[row["attr"]][row["to_id"]].append(row["from_id"])
                    if row["how"] in (BY_AMOUNT, CONFIRMED):
                        by_amount[(row["from_id"], row["to_id"])] = (
                            "Zahlung ohne Nummer – Betrag und Zahler stimmen" if row["how"] == BY_AMOUNT
                            else "Zahlung ohne Nummer – von Ihnen zugeordnet")
                self.backrefs[row["to_id"]].append((row["from_id"], row["attr"], row["kind"], row["how"]))
                self.outrefs[row["from_id"]].append((row["to_id"], row["attr"], row["kind"], row["how"]))
            from .payments import apply_to_records, ledger, mail_sources, stale_statuses
            self.untrusted = mail_sources(self.store)
            try:
                self.ledger = ledger(self.model, self.records, self.mentions, untrusted=self.untrusted, by_amount=by_amount)
            except Exception:  # noqa: BLE001 - the pages must open even if the ledger cannot be built
                self.ledger = {}
            apply_to_records(self.model, self.records, self.ledger)
            from .process import stock_now
            for rid, v in stock_now(self.model, self.records).items():
                if rid in self.by_id:
                    self.by_id[rid]["data"]["stock_now"] = v
            self.stale = stale_statuses(self.model, self.records, self.ledger)
            self._mv, self._dv = mv, dv
            self._work = None

    # --- accessors -------------------------------------------------------------------------------
    @property
    def specs(self) -> dict[str, dict]:
        return {t["id"]: t for t in (self.model or {}).get("types", [])}

    def spec(self, tid: str) -> dict | None:
        return self.specs.get(tid)

    def attr(self, tid: str, aid: str) -> dict | None:
        s = self.spec(tid)
        return next((a for a in s["attrs"] if a["id"] == aid), None) if s else None

    def title(self, rid) -> str:
        return self.titles.get(rid, f"#{rid}")

    def active_records(self) -> dict[str, list[dict]]:
        """Records without those the newest version of their list no longer has: kept, but not worked on."""
        return {tid: [r for r in rs if not (r.get("meta") or {}).get("vanished")] for tid, rs in self.records.items()}

    def payment_proposals(self) -> dict[int, dict]:
        """{invoice rid: the open question} for transfers without a number that may pay it."""
        from .store import loads
        out = {}
        for q in self.store.q("SELECT id, payload FROM questions WHERE kind='payment_match' AND status='open'"):
            pl = loads(q["payload"]) or {}
            recs = pl.get("records") or []
            for inv in recs[1:]:
                out[inv] = dict(qid=q["id"], bank=recs[0], text=pl.get("text"))
        return out

    def work(self, today: date | None = None) -> list[dict]:
        from .process import compute_work

        self.ensure()
        today = today or date.today()
        key = (self._mv, self._dv, today.isoformat())
        if self._work is not None and self._work_key == key:
            return self._work
        if not self.model:
            return []
        pending = self.payment_proposals()
        self.pending_payments = pending
        work = compute_work(self.model, self.active_records(), self.mentions, today, self.outrefs, self.titles,
                            pending_payments=pending, ledger=self.ledger,
                            mails_done=set(self.store.decisions("mail_done")))
        work += self.integrity()
        work += self.mail_payments()
        changed = self.bank_changes(today)
        if changed:
            risk = next((g for g in work if g["id"] == "risk:iban"), None)
            if risk is None:
                risk = dict(id="risk:iban", type=changed[0]["type"], kind="risk", severity=3, count=0, amount=None,
                            items=[], action=None, title="Vorsicht: Bankverbindung oder Absender passen nicht zum Lieferanten",
                            explain="Vor einer Zahlung telefonisch beim bekannten Ansprechpartner prüfen. "
                                    "So sieht Rechnungsbetrug typischerweise aus.")
                work.append(risk)
            risk["items"] = changed + risk["items"]
            risk["count"] = len(risk["items"])
        work.sort(key=lambda g: (-g["severity"], -(g["amount"] or 0), -g["count"]))
        self._work = work
        self._work_key = key
        return self._work

    def bank_changes(self, today: date) -> list[dict]:
        """A newer supplier list names another bank account than before: the classic invoice fraud
        comes as a changed master record too, not only as a mail."""
        out = []
        masters = {t["id"]: t for t in self.model["types"] if t["kind"] == "master"}
        ibans = {a["id"]: t for t in masters.values() for a in t["attrs"] if a["kind"] == "iban"}
        if not ibans:
            return out
        since = (today - timedelta(days=60)).isoformat()
        marks = ",".join("?" * len(ibans))
        for c in self.store.q(f"SELECT record_id, ts, attr, old, new, source_id FROM changes WHERE kind='import' "
                              f"AND attr IN ({marks}) AND ts >= ? ORDER BY id", (*ibans, since)):
            old, new = loads(c["old"]), loads(c["new"])
            if not old or not new or "".join(str(old).split()).upper() == "".join(str(new).split()).upper():
                continue
            rid = c["record_id"]
            if rid not in self.by_id:
                continue
            src = self.store.q1("SELECT name FROM sources WHERE id=?", (c["source_id"],)) if c["source_id"] else None
            from .reconcile import _fmt_iban
            out.append(dict(rid=rid, partner=rid, title=self.title(rid), party=None, days=0, money=None, type=ibans[c["attr"]]["id"],
                            reason=f"neue Bankverbindung im Stammsatz: {_fmt_iban(str(new))} statt {_fmt_iban(str(old))}"
                                   + (f" (laut „{src['name']}“)" if src else "")
                                   + " – vor der nächsten Zahlung telefonisch bestätigen"))
        return out

    def mail_payments(self) -> list[dict]:
        """A list that came by mail says invoices are paid: shown, not counted, until the owner accepts it."""
        from .payments import untrusted_rows
        rows = untrusted_rows(self.model, self.records, getattr(self, "untrusted", set()))
        if not rows:
            return []
        inv_types = {e["type"] for e in self.ledger.values()}
        items, sources = [], {}
        for rid in rows:
            r = self.by_id.get(rid)
            if not r:
                continue
            named = [to for to, attr, kind, how in self.outrefs.get(rid, []) if to in self.by_id
                     and self.by_id[to]["type"] in inv_types and (self.ledger.get(to) or {}).get("state") in ("offen", "teilbezahlt")]
            if not named:
                continue
            sid = next(iter(set((r.get("meta") or {}).get("src") or []) & self.untrusted), None)
            src = self.store.q1("SELECT name FROM sources WHERE id=?", (sid,)) if sid else None
            sources[sid] = src["name"] if src else "?"
            for to in named[:3]:
                items.append(dict(rid=to, title=self.title(to), days=0, money=(self.ledger.get(to) or {}).get("open"),
                                  reason=f"laut „{sources[sid]}“ aus einer Mail bezahlt – im eigenen Kontoauszug nicht zu sehen",
                                  source=sid, party=None))
        if not items:
            return []
        return [dict(id="pay:mail", type=self.by_id[items[0]["rid"]]["type"], kind="mailpay", severity=2,
                     title="Zahlungsnachweise aus Mails – noch nicht gezählt", count=len(items),
                     amount=round(sum(x["money"] or 0 for x in items), 2), items=items[:50], action=None,
                     sources=[dict(id=k, name=v) for k, v in sources.items() if k],
                     explain="Eine mitgeschickte Liste nennt diese Rechnungen als bezahlt. Gezählt wird Geld nur aus "
                             "Ihren eigenen Kontoauszügen – oder aus dieser Liste, wenn Sie sie als Zahlungsquelle anerkennen.")]

    def integrity(self) -> list[dict]:
        """Issued documents and what the files say about them: deviations that were not taken over,
        a number given twice, a document that no longer appears in any file."""
        from .behavior import _foreign_numbers
        from .ops import LOCKED_CONCEPTS
        from .text import norm_key

        items = []
        gone = {r["record_id"] for r in self.store.q(
            "SELECT c.record_id FROM changes c WHERE c.kind='gone' AND c.id = (SELECT MAX(id) FROM changes "
            "WHERE record_id=c.record_id AND kind IN ('gone','import'))")}
        for spec in self.model["types"]:
            if spec.get("concept") not in LOCKED_CONCEPTS:
                continue
            key = spec.get("key")
            # a supplier's numbers are unique per supplier only
            party = next((a["id"] for a in spec["attrs"] if a["kind"] == "ref"
                          and (self.spec(a.get("ref")) or {}).get("kind") == "master"), None) \
                if _foreign_numbers(spec, self.model) else None
            by_number = defaultdict(list)
            missing = {}
            for m in spec.get("members", []):
                v = m.get("versions") or {}
                for k in v.get("vanished") or []:
                    missing[norm_key(k)] = v.get("vanished_from")
            for r in self.records.get(spec["id"], []):
                meta = r.get("meta") or {}
                if meta.get("draft"):
                    continue
                for aid, (v, src) in (meta.get("collision") or {}).items():
                    a = next((x for x in spec["attrs"] if x["id"] == aid), None)
                    if a:
                        items.append(dict(rid=r["id"], title=self.title(r["id"]), days=0, money=None, party=None,
                                          reason=f"„{src}“ nennt diese Nummer für eine andere Rechnung ({a['name']}: "
                                                 f"{v}) – nicht übernommen, die Nummer ist hier vergeben", sev=3))
                        break
                for aid, (v, src) in (meta.get("conflicts") or {}).items():
                    a = next((x for x in spec["attrs"] if x["id"] == aid), None)
                    if a:
                        items.append(dict(rid=r["id"], title=self.title(r["id"]), days=0, money=None, party=None,
                                          reason=f"„{src}“ nennt für {a['name']} einen anderen Wert – nicht übernommen, "
                                                 f"die Rechnung ist festgeschrieben", sev=3))
                for aid, (was, now, src, when) in (meta.get("corrected") or {}).items():
                    a = next((x for x in spec["attrs"] if x["id"] == aid), None)
                    if a:
                        from .values import display
                        items.append(dict(rid=r["id"], title=self.title(r["id"]), days=0, money=None, party=None,
                                          reason=f"{a['name']} nach der Ausstellung geändert: {display(was, a['kind'])} → "
                                                 f"{display(now, a['kind'])} laut „{src}“ – im anderen Programm korrigiert?",
                                          sev=2, seen=f"/r/{r['id']}/korrektur-gesehen"))
                        break
                e = self.ledger.get(r["id"])
                if e and e.get("doc") and not meta.get("corrected"):
                    from .values import display
                    items.append(dict(rid=r["id"], title=self.title(r["id"]), days=0, money=e["open"], party=None,
                                      reason=f"Das PDF nennt {display(e['doc']['total'], 'money')}, das Rechnungsbuch "
                                             f"{display(e['doc']['book'], 'money')} – gezählt wird das PDF, das hat der "
                                             f"Kunde bekommen. Bitte das Buch berichtigen.", sev=2))
                if key and r["data"].get(key) is not None:
                    by_number[(r["data"].get(party) if party else None, norm_key(r["data"][key]))].append(r)
                if r["id"] in gone:
                    items.append(dict(rid=r["id"], title=self.title(r["id"]), days=0, money=None, party=None,
                                      reason="steht in keiner eingelesenen Datei mehr – im anderen Programm gelöscht?", sev=2))
                elif key and missing and r.get("origin") == "import" and norm_key(r["data"].get(key)) in missing:
                    items.append(dict(rid=r["id"], title=self.title(r["id"]), days=0, money=None, party=None,
                                      reason=f"fehlt in der neuesten Fassung von „{missing[norm_key(r['data'].get(key))]}“ – "
                                             f"im anderen Programm gelöscht? Ausgestellte Rechnungen bleiben hier erhalten", sev=2))
            for num, rs in by_number.items():
                if len(rs) > 1 and not any((r.get("meta") or {}).get("storno_of") for r in rs):
                    for r in rs:
                        here = r.get("origin") == "user"
                        items.append(dict(rid=r["id"], title=self.title(r["id"]), days=0, money=None, party=None,
                                          reason=f"Nummer {r['data'][key]} gibt es {len(rs)}-mal"
                                                 + (" – diese wurde hier ausgestellt" if here else " – aus einer Datei"),
                                          sev=3))
        # any kind of thing: a number given here and, for something else, in a file
        for spec in self.model["types"]:
            key = spec.get("key")
            if not key or spec.get("concept") in LOCKED_CONCEPTS:
                continue
            by_no = defaultdict(list)
            for r in self.records.get(spec["id"], []):
                if r["data"].get(key) is not None and not (r.get("meta") or {}).get("draft"):
                    by_no[norm_key(r["data"][key])].append(r)
            for rs in by_no.values():
                if len(rs) > 1 and any(r.get("origin") == "user" for r in rs) and any(r.get("origin") == "import" for r in rs):
                    for r in rs:
                        here = r.get("origin") == "user"
                        items.append(dict(rid=r["id"], title=self.title(r["id"]), days=0, money=None, party=None,
                                          reason=f"{spec['name']}-Nummer {r['data'][key]} gibt es zweimal – "
                                                 + ("hier angelegt" if here else "aus einer Datei")
                                                 + ": zwei verschiedene, bitte eine umnummerieren", sev=2))
        if not items:
            return []
        seen, uniq = set(), []
        for x in items:
            if (x["rid"], x["reason"]) not in seen:
                seen.add((x["rid"], x["reason"]))
                uniq.append(x)
        locked = all((self.spec(self.by_id[x["rid"]]["type"]) or {}).get("concept") in LOCKED_CONCEPTS for x in uniq)
        return [dict(id="integrity", type=self.by_id[uniq[0]["rid"]]["type"], kind="integrity",
                     severity=max(x["sev"] for x in uniq),
                     title="Prüfen: Ihre Dateien widersprechen ausgestellten Belegen" if locked else
                     "Prüfen: Ihre Dateien widersprechen dem, was hier steht",
                     count=len({x["rid"] for x in uniq}), amount=None, items=uniq[:50], action=None,
                     explain="Festgeschriebene Rechnungen ändert Physarum beim Einlesen nicht. Was abweicht, steht hier – "
                             "klären Sie es im anderen Programm oder mit einer Stornorechnung.")]

    def refresh_network(self, force: bool = False):
        """Usage changes the organism: recompute Physarum conductivities every few minutes."""
        if not self.model or (not force and time.time() - self._net_at < 300):
            return
        from .physarum import grow_network

        import copy
        with self.lock:
            m = copy.deepcopy(self.model)  # the live picture only; menu and columns wait for the next growth
            grow_network(m, self.store)
            self.model["network"] = m.get("network")
            self._net_at = time.time()
            net = dict(model_version=self._mv, network=m.get("network"))
            self.store.kv_set("network", net)

    def _overlay_network(self, net: dict):
        # the picture of the organism follows usage live; menu order and list columns keep the
        # conductivity of the last growth, so the screen stays calm between two feedings
        self.model["network"] = net.get("network") or self.model.get("network")

    # --- navigation order with hysteresis (things do not jump around) -------------------------------
    def nav(self) -> tuple[list[dict], list[dict]]:
        """Menu: ordered by conductivity, with hysteresis, recomputed only when the organism grew.
        A kind of thing that is new is shown for two weeks even while it is still small."""
        self.ensure()
        if not self.model:
            return [], []
        types = [t for t in self.model["types"] if t["kind"] != "line"]
        sal = {t["id"]: t.get("salience") or 0 for t in types}
        saved = self.store.kv_get("nav_order") or {}
        if isinstance(saved, list):
            saved = dict(order=saved, model=None)
        prev = [tid for tid in saved.get("order", []) if tid in sal]
        if saved.get("model") == self._mv and set(prev) == set(sal):
            order = prev
        else:
            # the menu keeps its places (people find things where they were); a new kind of thing joins
            # where its weight puts it, and only a list that became far more important moves up
            order = list(prev)
            for t in sorted((t for t in types if t["id"] not in prev), key=lambda t: -sal[t["id"]]):
                pos = next((i for i, x in enumerate(order) if sal[x] < sal[t["id"]]), len(order))
                order.insert(pos, t["id"])
            changed, guard = True, 0
            while changed and guard < 50:
                changed = False
                guard += 1
                for i in range(len(order) - 1):
                    a, b = order[i], order[i + 1]
                    if sal[b] > sal[a] * 2 + 0.05:
                        order[i], order[i + 1] = b, a
                        changed = True
            self.store.kv_set("nav_order", dict(order=order, model=self._mv))
        seen = self.store.kv_get("type_seen") or {}
        today = date.today().isoformat()
        first = not seen
        if any(tid not in seen for tid in sal):
            for tid in sal:
                seen.setdefault(tid, "" if first else today)
            self.store.kv_set("type_seen", seen)
        flux = self.store.flux("type:")
        active, dormant = [], []
        by = {t["id"]: t for t in types}
        for tid in order:
            t = dict(by[tid])
            t["count"] = len(self.records.get(tid, []))  # what is there now, also what was made here since growing
            t["is_new"] = bool(seen.get(tid)) and (date.today() - date.fromisoformat(seen[tid])).days <= 14
            used = flux.get(f"type:{tid}", 0) > 0.5
            if (sal[tid] < 0.22 and not used and (t.get("count") or 0) < 30 and not t["is_new"]) and t["kind"] != "document":
                dormant.append(t)
            else:
                active.append(t)
        return active, dormant
