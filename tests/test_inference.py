import unittest

from physarum.infer.identity import build_protos, resolve
from physarum.infer.normalize import normalize
from physarum.infer.observe import obs_from_table
from physarum.infer.relations import MentionIndex, discover, discover_mentions
from physarum.infer.unify import unify
from physarum.physarum import tero
from physarum.values import profile_table


def obs(tid, label, columns, rows):
    profs = profile_table(columns, rows, {"locale": "de"})
    return obs_from_table(tid, label, columns, profs, list(range(2, len(rows) + 2)), source_id=tid)


def flat_orders():
    cols = ["Auftrag", "Datum", "Kd-Nr", "Kunde", "Art.-Nr", "Artikel", "Menge", "Einzelpreis", "Gesamt"]
    rows = []
    custs = [("K-1", "Café Hafenblick"), ("K-2", "Hotel Elbblick"), ("K-3", "Bistro Anker"), ("K-4", "Kanzlei Lotse"),
             ("K-5", "Bäckerei Krume"), ("K-6", "Büro Kompass")]
    arts = [("A-1", "Espresso 1 kg", 24.9), ("A-2", "Filter 1 kg", 28.9), ("A-3", "Decaf 1 kg", 27.9)]
    n = 0
    for o in range(120):
        kd, kn = custs[o % 6]
        if o % 7 == 0:
            kn = kn.replace("Café", "Cafe")  # typo variant
        for j in range(1 + o % 3):
            an, aname, price = arts[(o + j) % 3]
            q = 1 + (o + j) % 5
            rows.append([f"A-2026-{o + 1:04d}", f"{1 + o % 28:02d}.0{1 + o % 9}.2026", kd, kn, an, aname, q, price,
                         round(q * price, 2)])
            n += 1
    return cols, rows


class TestNormalize(unittest.TestCase):
    def test_flat_export_becomes_header_lines_customer_article(self):
        cols, rows = flat_orders()
        parts = normalize(obs(1, "Aufträge", cols, rows))
        hints = sorted(p.name_hint[0] for p in parts if p.name_hint)
        self.assertEqual(hints, ["Artikel", "Auftrag", "Auftragsposition", "Kunde"])
        header = next(p for p in parts if p.kind_hint == "header")
        self.assertEqual(header.n, 120)
        self.assertEqual(header.key, "Auftrag")
        lines = next(p for p in parts if p.kind_hint == "line")
        self.assertIn("Einzelpreis", [c.name for c in lines.cols])  # the price stays a fact of the sale
        self.assertEqual(len(lines.links), 2)

    def test_no_extraction_without_repetition(self):
        cols = ["Kd-Nr", "Firma", "Ort"]
        rows = [[f"K-{i}", f"Firma {i}", "Hamburg" if i % 2 else "Kiel"] for i in range(30)]
        parts = normalize(obs(1, "Kunden", cols, rows))
        self.assertEqual(len(parts), 1)

    def test_base_rate_column_is_not_a_dependency(self):
        cols = ["Rechnungsnr", "Kd-Nr", "Kunde", "Status"]
        rows = []
        for i in range(400):
            kd = f"K-{i % 20}"
            rows.append([f"RE-{i}", kd, f"Kunde {i % 20}", "offen" if (i // 20) % 10 == 3 else "bezahlt"])
        parts = normalize(obs(1, "Rechnungen", cols, rows))
        party = next(p for p in parts if p.kind_hint == "party")
        self.assertNotIn("Status", [c.name for c in party.cols])


class TestUnifyIdentityRelations(unittest.TestCase):
    def setUp(self):
        self.master = obs(1, "Kundenliste", ["Kd-Nr.", "Firma", "PLZ", "Ort", "Telefon"],
                          [["K-1", "Café Hafenblick", "20457", "Hamburg", "040 111111"],
                           ["K-2", "Hotel Elbblick GmbH", "22765", "Hamburg", "040 222222"],
                           ["K-3", "Bistro Anker", "22880", "Wedel", "040 333333"],
                           ["K-9", "Cafe Hafenblick GmbH", "20457", "Hamburg", "040111111"]])
        self.crm = obs(2, "CRM_Export", ["Company", "City", "Email"],
                       [["Hotel Elbblick", "Hamburg", "info@elbblick.de"], ["Bistro Anker", "Wedel", "a@anker.de"],
                        ["Neukunde Kiel", "Kiel", "x@neu.de"]])
        cols, rows = flat_orders()
        self.parts = normalize(obs(3, "Aufträge", cols, rows))

    def build(self, decisions=None):
        types = unify([self.master, self.crm] + self.parts)
        for i, t in enumerate(types):
            t.tid = f"t{i}"
            for j, a in enumerate(t.attrs):
                a.aid = f"a{i}_{j}"
        groups, qs = {}, []
        for t in types:
            groups[id(t)] = resolve(t, build_protos(t), decisions or {}, qs, [])
        return types, groups, qs

    def test_customers_from_three_sources_are_one_type(self):
        types, groups, qs = self.build()
        kunden = [t for t in types if t.concept == "kunde"]
        self.assertEqual(len(kunden), 1)
        k = kunden[0]
        self.assertEqual(len(k.members), 3)
        # K-1..K-6, K-9 (a duplicate with its own number) and the CRM newcomer
        self.assertEqual(len(groups[id(k)]), 8)
        # the duplicate with a different number is asked about, never merged silently
        self.assertTrue(any(q["kind"] == "same_record" for q in qs))

    def test_relations_structural_and_by_value(self):
        types, groups, _ = self.build()
        obs_type = {o.oid: t for t in types for o in t.members}
        rels = discover(types, groups, obs_type)
        pairs = {(r.src.name, r.dst.name) for r in rels}
        self.assertIn(("Auftrag", "Kunde"), pairs)
        self.assertIn(("Auftragsposition", "Auftrag"), pairs)
        self.assertIn(("Auftragsposition", "Artikel"), pairs)

    def test_mentions_in_free_text_with_context(self):
        inv = obs(4, "Rechnungen", ["Rechnungsnr", "Datum", "Betrag"],
                  [[f"RE-2026-{i:04d}", "01.02.2026", "10,00"] for i in range(1, 20)])
        orders = obs(5, "Auftragsbuch", ["Auftragsnr", "Datum"], [[f"A-2026-{i:04d}", "01.02.2026"] for i in range(1, 20)])
        bank = obs(6, "Kontoauszug", ["Buchungstag", "Verwendungszweck", "Betrag"],
                   [["02.02.2026", "RE-2026-0003 danke", "10,00"], ["03.02.2026", "Rechnung 2026-0005", "10,00"],
                    ["04.02.2026", "Miete", "-500,00"], ["05.02.2026", "RE2026-0007", "10,00"]])
        types = unify([inv, orders, bank])
        for i, t in enumerate(types):
            t.tid = f"t{i}"
            for j, a in enumerate(t.attrs):
                a.aid = f"a{i}_{j}"
        groups = {id(t): resolve(t, build_protos(t)) for t in types}
        mi = MentionIndex(types, groups)
        rels = discover_mentions(types, groups, mi, set())
        self.assertEqual(len(rels), 1)
        r = rels[0]
        self.assertEqual(r.dst.name, "Rechnung")
        self.assertEqual(len(r.targets), 3)  # "Rechnung 2026-0005" resolved by context, not to the order


class TestPhysarum(unittest.TestCase):
    def test_redundant_tubes_survive_but_main_path_is_thicker(self):
        # triangle a-b-c plus a long detour d; nutrients at a and c
        edges = [(0, 1, 1.0), (1, 2, 1.0), (0, 2, 1.0), (0, 3, 3.0), (3, 2, 3.0)]
        D, Q = tero(4, edges, [0.5, 0.0, 0.5, 0.0])
        self.assertGreater(D[2], D[0])          # direct tube a-c carries most flow
        self.assertGreater(D[0], 1e-3)          # the redundant path is thinner, not gone
        self.assertLess(D[3], D[2])             # the long detour is weakest


if __name__ == "__main__":
    unittest.main()
