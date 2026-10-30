"""Firm A: a workshop near Hildesheim. Invoices 31001.. count up; some customers live in 31008 Elze,
31020 Salzhemmendorf, 31028 Gronau, 31036 Eime - postcodes that are also invoice numbers."""
import sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import TODAY, de, eur, write

people = [("Kaya", "Peter", "31008", "Elze"), ("Wolf", "Jan", "31020", "Salzhemmendorf"),
          ("Meyer", "Ayse", "31028", "Gronau"), ("Brune", "Rolf", "31036", "Eime"),
          ("Lange", "Monika", "31134", "Hildesheim"), ("Pohl", "Dieter", "31135", "Hildesheim"),
          ("Vogt", "Karin", "31137", "Hildesheim"), ("Albers", "Frank", "31139", "Hildesheim")]
kunden = ["KdNr;Name;Vorname;Straße;PLZ;Ort"] + [f"{10100 + 37 * i};{n};{v};Hauptstr. {i + 1};{z};{o}"
                                                for i, (n, v, z, o) in enumerate(people)]
inv = ["Rg-Nr.;Datum;Kd-Nr.;Brutto;fällig;bez. am"]
bank = ["Buchungstag;Auftraggeber;Verwendungszweck;Betrag"]
start = TODAY - timedelta(days=100)
special = {}
for i in range(40):
    d = start + timedelta(days=2 * i)
    no = 31001 + i
    g = round(180.0 + 11.5 * i, 2)
    k = i % len(people)
    n, v, z, o = people[k]
    kd = 10100 + 37 * k
    paid = ""
    if no in (31008, 31010):          # paid by the firm the driver works for, number given (PLZ 31008 vs no PLZ)
        bank.append(f"{de(d + timedelta(days=8))};Spedition Hahn GmbH;Rg {no} Fahrzeug {n};{eur(g)}")
        special[no] = "Dritter zahlt mit Nummer"
    elif no in (31020, 31022):        # partial payment, number given
        bank.append(f"{de(d + timedelta(days=8))};{v} {n};Rg {no} Teilzahlung;{eur(200.0)}")
        special[no] = "Teilzahlung 200 mit Nummer"
    elif no in (31028, 31030):        # paid exactly by the customer, number given
        bank.append(f"{de(d + timedelta(days=8))};{v} {n};Rg {no};{eur(g)}")
        special[no] = "Kunde zahlt genau mit Nummer"
    elif no in (31036, 31038):        # paid by spouse, other first name, number given
        bank.append(f"{de(d + timedelta(days=8))};Erika {n};Rechnung {no};{eur(g)}")
        special[no] = "Ehefrau zahlt mit Nummer"
    elif i < 34:
        bank.append(f"{de(d + timedelta(days=8))};{v} {n};Rg {no};{eur(g)}")
    inv.append(f"{no};{de(d)};{kd};{eur(g)};{de(d + timedelta(days=14))};{paid}")
    bank.append(f"{de(d + timedelta(days=1))};Stadtwerke Hildesheim;Abschlag Strom;-{eur(120.0)}")
write(Path(sys.argv[1]), {"Kunden.csv": kunden, "Rechnungsbuch.csv": inv, "Konto.csv": bank})
print(special)
