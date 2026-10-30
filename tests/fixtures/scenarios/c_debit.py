"""Firm C: a service firm that collects half of its invoices by SEPA direct debit. The office ticks a
direct debit off as paid on the invoice date (it is certain to come); the debit is booked a week later and
names the invoice. The other half pays by transfer; the book has the bank's date."""
import sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import TODAY, de, eur, write

names = ["Café Linde", "Hotel Möwe", "Bistro Anker", "Kanzlei Lotse", "Bäckerei Krume", "Büro Kompass",
         "Praxis Dr. Wendt", "Optik Schulz"]
inv = ["Rechnungsnr;Rechnungsdatum;Kunde;Brutto;Zahlart;Fällig am;Bezahlt am"]
bank = ["Buchungstag;Zahlungspartner;Verwendungszweck;Betrag"]
start = TODAY - timedelta(days=150)
for i in range(40):
    d = start + timedelta(days=3 * i)
    no = f"RE-{d.year}-{i + 1:04d}"
    g = round(150.0 + 9.5 * i, 2)
    cust = names[i % len(names)]
    debit = i % 2 == 0
    if i >= 37:
        paid = ""
    elif debit:
        paid = de(d)  # ticked off when the invoice goes out: the debit is certain
        bank.append(f"{de(d + timedelta(days=7))};{cust};SEPA-Lastschrift {no} Mandat M-{100 + i % 8};{eur(g)}")
    else:
        paid = de(d + timedelta(days=10))
        bank.append(f"{de(d + timedelta(days=10))};{cust};{no};{eur(g)}")
    inv.append(f"{no};{de(d)};{cust};{eur(g)};{'Lastschrift' if debit else 'Überweisung'};{de(d + timedelta(days=14))};{paid}")
    bank.append(f"{de(d + timedelta(days=1))};Immobilien Kuhn GbR;Miete;-{eur(950.0)}")
write(Path(sys.argv[1]), {"Rechnungen.csv": inv, "Konto.csv": bank})
