"""Firm N: a wholesaler grants skonto on every invoice, written the usual way: "2 % Skonto bei Zahlung innerhalb
von 10 Tagen, 30 Tage netto". Most customers take it; the book has them paid."""
import sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import TODAY, de, eur, write_files

terms = sys.argv[2] if len(sys.argv) > 2 else "2 % Skonto bei Zahlung innerhalb von 10 Tagen, 30 Tage netto"
names = ["Café Linde", "Hotel Möwe", "Bistro Anker", "Kanzlei Lotse", "Bäckerei Krume", "Büro Kompass"]
inv = ["Rechnungsnr;Rechnungsdatum;Kunde;Brutto;Zahlungsbedingungen;Fällig am;Bezahlt am"]
bank = ["Buchungstag;Zahlungspartner;Verwendungszweck;Betrag"]
start = TODAY - timedelta(days=150)
for i in range(30):
    d = start + timedelta(days=4 * i)
    no = f"RE-2026-{i + 1:04d}"
    g = round(400.0 + 17.5 * i, 2)
    cust = names[i % len(names)]
    paid = ""
    if i < 27:
        p = d + timedelta(days=7)
        bank.append(f"{de(p)};{cust};{no} abzgl. 2% Skonto;{eur(round(g * 0.98, 2))}")
        paid = de(p)
    inv.append(f"{no};{de(d)};{cust};{eur(g)};{terms};{de(d + timedelta(days=30))};{paid}")
    bank.append(f"{de(d + timedelta(days=1))};Immobilien Kuhn GbR;Miete;-{eur(950.0)}")
write_files(Path(sys.argv[1]), {"Rechnungen.csv": inv, "Konto.csv": bank})
