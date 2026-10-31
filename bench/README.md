# Prüfstand

Der Maßstab jeder Änderung. Eine Firma, die ein Prüfer einmal gebaut hat, bleibt hier: mit ihren Dateien,
ihren Lieferungen und dem, was an jedem Liefertag wahr ist. Physarum wächst jede Firma neu, an ihrem Tag
(fester Stichtag), und wird gegen die Wahrheit gemessen. Jede Firma läuft zusätzlich unter anderen Namen für
dieselben Dinge: S1 neutrale Dateinamen, S2 andere Spaltenüberschriften; die schnellen auch S3 (beides).

```bash
python bench/run.py              # alle Firmen, auch als S1 und S2 (rund 9 Minuten)
python bench/run.py demo maler   # nur diese
python bench/run.py --s0         # nur unter eigenen Namen: der schnelle Blick beim Arbeiten
python bench/run.py --save       # das Ergebnis wird die neue Basis (bench/baseline.json)
python bench/diff.py             # was der letzte Lauf geändert hat, Zelle für Zelle (--without FIRMA …)
python bench/one.py catering S0  # eine Firma, eine Variante: eine JSON-Zeile
python bench/keep.py catering /tmp/cat && python -m physarum /tmp/cat --port 8800   # ansehen
```

| Firma | Woher | Was sie prüft |
|---|---|---|
| demo | Beispiel-Firma (Kaffeerösterei) | der erste Eindruck |
| brenner | SHK-Firma, Review 2 (`tests/fixtures/brenner`) | Bank mit Vorspann, ein Blatt je Monteur, fertig aber nicht berechnet |
| agentur | Webagentur, Review 3, zwei Lieferungen (`data/agentur.zip`) | CRM, zwei Zeiterfassungen, Tickets, offene Posten centgenau |
| handwerk | Haustechnik, Review 4, zwei Lieferungen (`data/handwerk.zip`) | Abschläge, Einbehalt, zwei Banken, Wartung, Lieferanten-PDFs |
| musikschule | Strategie-Review (`gen/musikschule.py`) | SEPA-Sammellastschrift, umsatzsteuerfreie Beiträge, Kürzel |
| maler | Bedienungstest (`gen/maler.py`) | zwei „Müller, Hans“, eine Familie, die kein Kunde ist |
| shop | Online-Händler, Review 6, zwei Lieferungen (`gen/shop/`) | Auszahlungen, Erstattungen, Größen, B2B-Rechnungen |
| werkstatt | Kfz-Werkstatt, Review 7, zwei Lieferungen (`gen/werkstatt.py`) | Rechnungsnummern als reine Zahl, bar/EC bei Abholung, Versicherung kürzt, Gutschrift und Storno, eigene Rechnungs-PDFs |
| gebaeude | Gebäudereinigung, Review 8, zwei Lieferungen (`gen/gebaeude.py`) | Sparkassen-CSV (CAMT), Monatsrechnungen je Vertrag, SEPA-Sammellastschrift mit Rücklastschriften, Hausverwaltung zahlt mehrere Objekte, eigene XRechnung, Briefbogen-PDFs |
| catering | Catering und Veranstaltungen, Review 9, zwei Lieferungen (`gen/catering.py`) | Bank nur als camt.053 (ein XML je Tag, Monats-ZIPs), Kontowechsel, Anzahlungen ohne Rechnung, Schlussrechnung nach Gästezahl, Stornokosten, Kita-Essen nach Essenszahlen, fester Dauerauftrag, Rahmenverträge quartalsweise, Entwurf im Rechnungsexport, ZUGFeRD/XRechnung/PDF-Eingangsrechnungen |
| hausverwaltung | WEG- und Mietverwaltung, Review 10, zwei Lieferungen (`gen/hausverwaltung.py`) | Miete, Hausgeld, Umlagen und Abrechnungsergebnisse ohne Rechnungsnummer (offene Posten als Sollstellung „Konto Sollart Zeitraum“), Jobcenter zahlt Teile, Kautionsraten, Vergütung vom Objektkonto aufs Geschäftskonto, neun Konten in drei Formaten (Sparkassen-CSV, VR-Umsatzanzeige, camt.053/052), Handwerkerrechnungen „c/o“ der Verwaltung |
| verein | Sportverein (e. V., 562 Mitglieder, fünf Abteilungen), Review 11, zwei Lieferungen (`gen/verein.py`) | Mitgliedsbeiträge ohne Rechnung (offene Posten als Sollstellung „Mitgliedsnr. Sollart Zeitraum“), monatlich bis jährlich, Lastschrift (pain.008, Sammelgutschrift, Rücklastschriften mit Gebühr), Überweisung und bar, Beitragserhöhung zum 01.07. mit Differenz der Jahreszahler, Familienbeitrag, Austritte und Daueraufträge danach, Kurs- und Feriencampgebühren, Pacht ohne Rechnung, eigene Rechnungen (Sponsoring, Hallennutzung), Bank als MT940 (.sta), VR-CSV und Sparkasse CSV-MT940, Chef-Masche per Mail |

Gemessen wird je Lieferung: offene Posten (richtig/zu viel/fehlend, Euro), überfällige Rechnungen,
fertige Aufträge ohne Rechnung, Festpreis-Projekte deutlich über Budget, Geld ohne Rechnung, Einträge auf
Heute, Fragen (davon zum Datenmodell) und „Geld erklärt“: welcher Anteil des Kontogelds (Summe der Beträge) durch
einen Vorgang erklärt ist – eine Zahlung auf eine Rechnung, eine Sollstellung, eine eigene Bewegung. Dieses Maß braucht
keine Wahrheit. Zusammengefasst wird „Geld richtig“ zweimal: über alle offenen Posten aller Firmen und als Mittel je
Firma, damit eine Firma mit vielen Posten nicht allein entscheidet. Unter S1–S3 zudem, in jeder Lieferung: dieselben
offenen Posten wie im Original, und heißen die Listen gleich?
Dazu, was der Code kostet: Zeilen, Wort-Regeln (eine Bedingung, die ein Wort oder eine Wortliste prüft),
reguläre Ausdrücke. „Listen gleich benannt“ misst nur, ob die Namen unter S1–S3 gleich bleiben, nicht ob sie
gut sind.

Die Regel: Jede neue Bedingung auf Zellinhalte (Wortliste, Schwelle, Sonderfall) braucht mindestens zwei Firmen,
bei denen sie messbar wirkt, und darf keine Kennzahl einer anderen Firma verschlechtern; ausgenommen sind nur Leser
dokumentierter Standardformate und Absturzfehler. Sonst ist der Fund eine dokumentierte Grenze. Regeln, die nur bei
einer Firma wirken, stehen auf Bewährung (`docs/KONZEPT.md`, Abschnitt 8.4).
