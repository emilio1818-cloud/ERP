"""Firm B: a workshop where almost everybody pays at the counter. The book has the paid date = invoice
date for cash; a few pay by transfer. Variant arg2: 'erh' adds a "Betrag erh." column; 'noday' drops
"bez. am" and keeps only "Betrag erh."."""
import sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import TODAY, de, eur, write

variant = sys.argv[2] if len(sys.argv) > 2 else ""
people = [("Kaya", "Peter"), ("Wolf", "Jan"), ("Meyer", "Ayse"), ("Brune", "Rolf"), ("Lange", "Monika"),
          ("Pohl", "Dieter"), ("Vogt", "Karin"), ("Albers", "Frank")]
kunden = ["KdNr;Name;Vorname;PLZ;Ort"] + [f"{10100 + 37 * i};{n};{v};59557;Lippstadt" for i, (n, v) in enumerate(people)]
head = "Rg-Nr.;Datum;Kd-Nr.;Brutto;Zahlart;fällig"
if variant != "noday":
    head += ";bez. am"
if variant in ("erh", "noday"):
    head += ";Betrag erh."
inv = [head]
bank = ["Buchungstag;Auftraggeber;Verwendungszweck;Betrag"]
start = TODAY - timedelta(days=100)
for i in range(40):
    d = start + timedelta(days=2 * i)
    no = 31001 + i
    g = round(80.0 + 13.5 * i, 2)
    n, v = people[i % len(people)]
    kd = 10100 + 37 * (i % len(people))
    transfer = i in (5, 17, 29)
    unpaid = i in (33, 35, 36, 38, 39)
    if transfer:
        bank.append(f"{de(d + timedelta(days=9))};{v} {n};Rg {no};{eur(g)}")
    paid = "" if unpaid else de(d + timedelta(days=9)) if transfer else de(d)
    row = f"{no};{de(d)};{kd};{eur(g)};{'Überw.' if transfer or unpaid else 'bar'};{de(d + timedelta(days=14)) if transfer or unpaid else ''}"
    if variant != "noday":
        row += f";{paid}"
    if variant in ("erh", "noday"):
        row += f";{eur(g) if paid else ''}"
    inv.append(row)
    if i % 5 == 0:
        bank.append(f"{de(d + timedelta(days=1))};Lindner Werkstatt;Bareinzahlung;{eur(1000.0)}")
    bank.append(f"{de(d + timedelta(days=1))};Stadtwerke;Abschlag Strom;-{eur(120.0)}")
write(Path(sys.argv[1]), {"Kunden.csv": kunden, "Rechnungsbuch.csv": inv, "Konto.csv": bank})
