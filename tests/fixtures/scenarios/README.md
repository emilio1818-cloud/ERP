# Szenarien der Code-Prüfung (Runde 8)

Kleine Firmen, die ein Prüfer gebaut hat, um je eine Regel zu brechen. Jedes Skript schreibt seine Dateien
in den Ordner, den es als erstes Argument bekommt (`python a_plz.py OUT [Variante]`); `tests/test_scenarios.py`
lässt sie wachsen und prüft, dass das Ergebnis so bleibt, wie es nach der Behebung war.

| Skript | Was es prüft |
|---|---|
| a_plz | Postleitzahlen, die zugleich Rechnungsnummern sind (31008 Elze) |
| b_cash | fast alle zahlen bar an der Kasse; das Buch hat „Betrag erh.“ (Variante `erh`) |
| c_debit | Lastschrift im Buch am Rechnungstag abgehakt, die Bank bucht eine Woche später |
| e_overlap | Kunden- und Rechnungsnummern ab 10001, beide im Verwendungszweck |
| g_advice | eine Mahnung nennt zwei offene Rechnungen; ein Fremder zahlt eine Anzahlung |
| j_refund | doppelt bezahlt, eine Mail bittet um Erstattung auf ein neues Konto |
| k_gross | Abschlagsrechnungen mit der Auftragssumme neben dem Rechnungsbetrag |
| n_skonto | Skonto in der üblichen Schreibweise („2 % Skonto bei Zahlung innerhalb von 10 Tagen“) |
