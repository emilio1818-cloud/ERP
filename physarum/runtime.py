"""In-memory view of the organism for fast pages: model, records, titles, work.

Everything is rebuilt lazily when the data version or the model version changes.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date

from .behavior import apply_virtual
from .grow import _de_date, record_title, record_titles
from .store import Store


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
            for row in self.store.q("SELECT from_id, attr, to_id, kind, how FROM refs"):
                if row["kind"] == "mention" and row["attr"] != "doc":
                    self.mentions[row["attr"]][row["to_id"]].append(row["from_id"])
                self.backrefs[row["to_id"]].append((row["from_id"], row["attr"], row["kind"], row["how"]))
                self.outrefs[row["from_id"]].append((row["to_id"], row["attr"], row["kind"], row["how"]))
            from .payments import apply_to_records, ledger, stale_statuses
            try:
                self.ledger = ledger(self.model, self.records, self.mentions)
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

    def work(self, today: date | None = None) -> list[dict]:
        from .process import compute_work

        self.ensure()
        today = today or date.today()
        key = (self._mv, self._dv, today.isoformat())
        if self._work is not None and self._work_key == key:
            return self._work
        if not self.model:
            return []
        pending = {}
        from .store import loads
        for q in self.store.q("SELECT id, payload FROM questions WHERE kind='payment_match' AND status='open'"):
            pl = loads(q["payload"]) or {}
            recs = pl.get("records") or []
            for inv in recs[1:]:
                pending[inv] = dict(qid=q["id"], bank=recs[0], text=pl.get("text"))
        self.pending_payments = pending
        work = compute_work(self.model, self.active_records(), self.mentions, today, self.outrefs, self.titles,
                            pending_payments=pending, ledger=self.ledger)
        work += self.integrity()
        work.sort(key=lambda g: (-g["severity"], -(g["amount"] or 0), -g["count"]))
        self._work = work
        self._work_key = key
        return self._work

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
                for aid, (v, src) in (meta.get("conflicts") or {}).items():
                    a = next((x for x in spec["attrs"] if x["id"] == aid), None)
                    if a:
                        items.append(dict(rid=r["id"], title=self.title(r["id"]), days=0, money=None, party=None,
                                          reason=f"„{src}“ nennt für {a['name']} einen anderen Wert – nicht übernommen, "
                                                 f"die Rechnung ist festgeschrieben", sev=3))
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
        if not items:
            return []
        seen, uniq = set(), []
        for x in items:
            if (x["rid"], x["reason"]) not in seen:
                seen.add((x["rid"], x["reason"]))
                uniq.append(x)
        return [dict(id="integrity", type=self.by_id[uniq[0]["rid"]]["type"], kind="integrity",
                     severity=max(x["sev"] for x in uniq), title="Prüfen: Ihre Dateien widersprechen ausgestellten Belegen",
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
            order = prev + [t["id"] for t in sorted(types, key=lambda t: -sal[t["id"]]) if t["id"] not in prev]
            changed, guard = True, 0
            while changed and guard < 50:
                changed = False
                guard += 1
                for i in range(len(order) - 1):
                    a, b = order[i], order[i + 1]
                    if sal[b] > sal[a] * 1.15 + 0.01:
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
            t["is_new"] = bool(seen.get(tid)) and (date.today() - date.fromisoformat(seen[tid])).days <= 14
            used = flux.get(f"type:{tid}", 0) > 0.5
            if (sal[tid] < 0.22 and not used and (t.get("count") or 0) < 30 and not t["is_new"]) and t["kind"] != "document":
                dormant.append(t)
            else:
                active.append(t)
        return active, dormant
