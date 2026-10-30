"""Firm G: the firm sends Pohl a reminder naming his two open invoices (1.120,00 + 380,00). Nine days
later an unknown customer, Cem Arslan, pays a deposit of 1.470,00 for winter tyres, no invoice yet.
Pohl has not paid. Arg2 'noremind' leaves the reminder out (control)."""
import sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import TODAY, de, eur, eml, write_files

variant = sys.argv[2] if len(sys.argv) > 2 else ""
people = [("Kaya", "Peter"), ("Wolf", "Jan"), ("Meyer", "Ayse"), ("Brune", "Rolf"), ("Lange", "Monika"),
          ("Pohl", "Dieter"), ("Vogt", "Karin"), ("Albers", "Frank")]
kunden = ["KdNr;Name;Vorname;PLZ;Ort"] + [f"{10100 + 37 * i};{n};{v};59557;Lippstadt" for i, (n, v) in enumerate(people)]
inv = ["Rg-Nr.;Datum;Kd-Nr.;Brutto;fällig;bez. am"]
bank = ["Buchungstag;Auftraggeber;Verwendungszweck;Betrag"]
start = TODAY - timedelta(days=100)
pohl = []
for i in range(40):
    d = start + timedelta(days=2 * i)
    no = 31001 + i
    k = i % len(people)
    n, v = people[k]
    kd = 10100 + 37 * k
    g = round(80.0 + 13.5 * i, 2)
    if no == 31006:
        g = 1120.00
    if no == 31014:
        g = 380.00
    if n == "Pohl" and no in (31006, 31014):
        pohl.append((no, d, g))
        paid = ""
    elif i < 36:
        paid = de(d + timedelta(days=8))
        bank.append(f"{de(d + timedelta(days=8))};{v} {n};Rg {no};{eur(g)}")
    else:
        paid = ""
    inv.append(f"{no};{de(d)};{kd};{eur(g)};{de(d + timedelta(days=14))};{paid}")
    bank.append(f"{de(d + timedelta(days=1))};Stadtwerke;Abschlag Strom;-{eur(120.0)}")
remind = start + timedelta(days=60)
bank.append(f"{de(remind + timedelta(days=9))};Cem Arslan;Anzahlung Winterreifen;{eur(1470.00)}")
files = {"Kunden.csv": kunden, "Rechnungsbuch.csv": inv, "Konto.csv": bank}
if variant != "noremind":
    body = ("Sehr geehrter Herr Pohl,\n\nbei Durchsicht unserer Buchhaltung haben wir festgestellt, dass folgende "
            "Rechnungen noch offen sind:\n\n" +
            "\n".join(f"Rechnung {no} vom {de(d)} über {eur(g)} EUR" for no, d, g in pohl) +
            f"\n\nzusammen {eur(sum(g for _, _, g in pohl))} EUR. Bitte überweisen Sie bis {de(remind + timedelta(days=14))}.\n\n"
            "Mit freundlichen Grüßen\nPetra Lindner\nAutoservice Lindner GmbH\nTel. 02941 18220\n")
    files["Mails/Zahlungserinnerung Pohl.eml"] = eml("Petra Lindner <buero@autoservice-lindner.de>",
                                                     "Dieter Pohl <d.pohl@t-online.de>",
                                                     "Zahlungserinnerung", remind, body)
write_files(Path(sys.argv[1]), files)
print(pohl, de(remind))
