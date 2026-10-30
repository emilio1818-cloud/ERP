"""Firm K: a builder's invoice book: down-payment invoices ("Abschlag") carry the order's total beside the
invoice amount; plain invoices have the same figure in both."""
import sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import TODAY, de, eur, write_files

names = ["Müller, Hans", "Schulz, Petra", "Becker, Tom", "Wagner, Eva", "Hoffmann, Jan", "Koch, Lisa"]
inv = ["Rechnungsnr;Rechnungsdatum;Kunde;Art;Auftragssumme;Netto;MwSt;Brutto;Fällig am"]
bank = ["Buchungstag;Auftraggeber;Verwendungszweck;Betrag"]
start = TODAY - timedelta(days=150)
truth = {}
for i in range(30):
    d = start + timedelta(days=5 * i)
    no = f"RE-2026-{i + 1:04d}"
    cust = names[i % len(names)]
    order = round(20000 + 1500 * i, 2)
    abschlag = i % 3 != 0
    gross = round(order * 0.3, 2) if abschlag else round(1000 + 37 * i, 2)
    net = round(gross / 1.19, 2)
    tax = round(gross - net, 2)
    inv.append(f"{no};{de(d)};{cust};{'Abschlag' if abschlag else 'Rechnung'};{eur(order if abschlag else gross)};{eur(net)};{eur(tax)};{eur(gross)};{de(d + timedelta(days=14))}")
    if i < 26:
        bank.append(f"{de(d + timedelta(days=10))};{cust.split(', ')[1]} {cust.split(', ')[0]};{no};{eur(gross)}")
    else:
        truth[no] = gross
write_files(Path(sys.argv[1]), {"Rechnungen.csv": inv, "Konto.csv": bank})
print("truth open", truth, sum(truth.values()))
