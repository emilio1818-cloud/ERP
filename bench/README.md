# Prüfstand

Der Maßstab jeder Änderung. Eine Firma, die ein Prüfer einmal gebaut hat, bleibt hier: mit ihren Dateien,
ihren Lieferungen und dem, was an jedem Liefertag wahr ist. Physarum wächst jede Firma neu, an ihrem Tag
(fester Stichtag), und wird gegen die Wahrheit gemessen. Die schnellen Firmen laufen zusätzlich unter
anderen Namen für dieselben Dinge: S1 neutrale Dateinamen, S2 andere Spaltenüberschriften, S3 beides.

```bash
python bench/run.py              # alle Firmen, die schnellen auch als S1–S3 (gut 1 Minute)
python bench/run.py demo maler   # nur diese
python bench/run.py --save       # das Ergebnis wird die neue Basis (bench/baseline.json)
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

Gemessen wird je Lieferung: offene Posten (richtig/zu viel/fehlend, Euro), überfällige Rechnungen,
fertige Aufträge ohne Rechnung, Festpreis-Projekte deutlich über Budget, Geld ohne Rechnung, Einträge auf
Heute, Fragen (davon zum Datenmodell). Unter S1–S3 zudem: dieselben offenen Posten wie im Original, und
heißen die Listen gleich?
Dazu, was der Code kostet: Zeilen, Wort-Regeln, reguläre Ausdrücke.

Die Regel: Ein Fund wird nur behoben, wenn die Lösung auf mindestens zwei Firmen greift und keine
Kennzahl einer anderen Firma schlechter macht. Sonst ist er eine dokumentierte Grenze.
