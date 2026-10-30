"""Firm E: customer numbers and invoice numbers both start at 10001 (the program numbers everything that
way). Customers write their customer number into the purpose next to the invoice number."""
import sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import TODAY, de, eur, write_files

firms = ["Café Linde", "Hotel Möwe", "Bistro Anker", "Kanzlei Lotse", "Bäckerei Krume", "Büro Kompass",
         "Praxis Wendt", "Optik Schulz", "Autohaus Kemper", "Elektro Kaiser", "Taxi Yilmaz", "Pflegedienst Sonne",
         "Getränke Brune", "Spedition Hahn", "Gärtnerei Rose", "Malerei Vogt", "Tischlerei Pohl", "Friseur Lange",
         "Kiosk Albers", "Metzgerei Wolf", "Blumen Meyer", "Reisebüro Kaya", "Bauhof Lippe", "Hausverwaltung Ems",
         "Fahrschule Tempo", "Apotheke Mitte", "Schuhhaus Klein", "Pizzeria Roma", "Zahnarzt Dr. Weiss", "Kita Sonnenblume"]
kunden = ["Kd-Nr.;Firma;PLZ;Ort"] + [f"{10001 + i};{n};59557;Lippstadt" for i, n in enumerate(firms)]
inv = ["Rg-Nr.;Datum;Kd-Nr.;Brutto;fällig;bez. am"]
bank = ["Buchungstag;Auftraggeber;Verwendungszweck;Betrag"]
start = TODAY - timedelta(days=170)
for i in range(80):
    d = start + timedelta(days=2 * i)
    no = 10001 + i
    k = (i * 7) % len(firms)
    kd = 10001 + k
    g = round(200.0 + 9.5 * i, 2)
    if no == 10060:
        k, kd, g = 11, 10012, 600.00   # Pflegedienst Sonne, customer 10012
    paid = ""
    if no == 10012:
        pass  # open, overdue: an invoice of Bistro Anker... whoever: nobody paid it
    elif no == 10060:
        bank.append(f"{de(d + timedelta(days=9))};{firms[k]};Kd-Nr. {kd} Rg {no} Teilzahlung;{eur(300.0)}")
    elif i < 72:
        paid = de(d + timedelta(days=9))
        bank.append(f"{de(d + timedelta(days=9))};{firms[k]};Kd-Nr. {kd} Rg {no};{eur(g)}")
    inv.append(f"{no};{de(d)};{kd};{eur(g)};{de(d + timedelta(days=14))};{paid}")
    bank.append(f"{de(d + timedelta(days=1))};Stadtwerke;Abschlag Strom;-{eur(120.0)}")
write_files(Path(sys.argv[1]), {"Kunden.csv": kunden, "Rechnungsbuch.csv": inv, "Konto.csv": bank})
