"""In-memory view of the organism for fast pages: model, records, titles, work.

Everything is rebuilt lazily when the data version or the model version changes.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date

from .behavior import apply_virtual
from .grow import record_title
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
            self.titles = {rid: record_title(specs[r["type"]], r["data"], rid) for rid, r in self.by_id.items()
                           if r["type"] in specs}
            self.mentions = defaultdict(lambda: defaultdict(list))
            self.backrefs = defaultdict(list)
            self.outrefs = defaultdict(list)
            for row in self.store.q("SELECT from_id, attr, to_id, kind, how FROM refs"):
                if row["kind"] == "mention" and row["attr"] != "doc":
                    self.mentions[row["attr"]][row["to_id"]].append(row["from_id"])
                self.backrefs[row["to_id"]].append((row["from_id"], row["attr"], row["kind"], row["how"]))
                self.outrefs[row["from_id"]].append((row["to_id"], row["attr"], row["kind"], row["how"]))
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
        self._work = compute_work(self.model, self.records, self.mentions, today, self.outrefs, self.titles,
                                  pending_payments=pending)
        self._work_key = key
        return self._work

    def refresh_network(self, force: bool = False):
        """Usage changes the organism: recompute Physarum conductivities every few minutes."""
        if not self.model or (not force and time.time() - self._net_at < 300):
            return
        from .physarum import grow_network

        with self.lock:
            grow_network(self.model, self.store)
            self._net_at = time.time()
            net = dict(model_version=self._mv, network=self.model.get("network"),
                       salience={t["id"]: t.get("salience") for t in self.model["types"]},
                       attrs={a["id"]: a.get("salience") for t in self.model["types"] for a in t["attrs"]})
            self.store.kv_set("network", net)

    def _overlay_network(self, net: dict):
        self.model["network"] = net.get("network") or self.model.get("network")
        for t in self.model["types"]:
            if t["id"] in (net.get("salience") or {}):
                t["salience"] = net["salience"][t["id"]]
            for a in t["attrs"]:
                if a["id"] in (net.get("attrs") or {}):
                    a["salience"] = net["attrs"][a["id"]]

    # --- navigation order with hysteresis (things do not jump around) -------------------------------
    def nav(self) -> tuple[list[dict], list[dict]]:
        self.ensure()
        if not self.model:
            return [], []
        types = [t for t in self.model["types"] if t["kind"] != "line"]
        prev = self.store.kv_get("nav_order") or []
        sal = {t["id"]: t.get("salience") or 0 for t in types}
        order = [tid for tid in prev if tid in sal] + [t["id"] for t in sorted(types, key=lambda t: -sal[t["id"]])
                                                        if t["id"] not in prev]
        changed = True
        guard = 0
        while changed and guard < 50:
            changed = False
            guard += 1
            for i in range(len(order) - 1):
                a, b = order[i], order[i + 1]
                if sal[b] > sal[a] * 1.15 + 0.01:
                    order[i], order[i + 1] = b, a
                    changed = True
        if order != prev:
            self.store.kv_set("nav_order", order)
        flux = self.store.flux("type:")
        active, dormant = [], []
        by = {t["id"]: t for t in types}
        for tid in order:
            t = by[tid]
            used = flux.get(f"type:{tid}", 0) > 0.5
            if (sal[tid] < 0.22 and not used and (t.get("count") or 0) < 30) and t["kind"] != "document":
                dormant.append(t)
            else:
                active.append(t)
        return active, dormant
