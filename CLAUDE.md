# Physarum – Arbeitsanleitung

Ein ERP, das sich aus den Daten einer Firma selbst baut. Worum es geht und warum: `README.md`, ausführlich
`docs/KONZEPT.md` (Abschnitt 7: ehrliche Grenzen, 8: was jede Prüfrunde geändert hat).

## Befehle

```bash
python3 -m unittest discover -s tests          # alle Tests, rund 2½ Minuten
python3 bench/run.py                           # Prüfstand: zwölf Firmen, je drei bis vier Varianten, rund 9 Minuten
python3 bench/run.py --s0 catering             # schneller Blick: eine Firma, nur unter eigenen Namen
python3 bench/diff.py --without hausverwaltung # was sich gegenüber bench/baseline.json geändert hat
python3 bench/run.py --save                    # neue Basis – erst, wenn diff.py keine Firma schlechter zeigt
python3 bench/keep.py FIRMA ORDNER && python3 -m physarum ORDNER --port 8800   # eine Firma ansehen
```

## Regeln

- **Der Prüfstand ist die Belohnung.** Jede Änderung an Erkennung oder Geld wird an `bench/` gemessen; neben
  „Geld richtig“ (gepoolt und je Firma) zählt „Geld erklärt“: der Anteil des Kontogelds, den ein Vorgang erklärt.
- **Stopp-Regel, ohne Etikett:** Jede neue Bedingung auf Zellinhalte – Wortliste, Schwelle, Sonderfall – braucht
  mindestens zwei Firmen des Prüfstands, bei denen sie messbar wirkt, und darf keine Kennzahl einer anderen Firma
  verschlechtern. Ausgenommen sind nur Leser dokumentierter Standardformate (camt, MT940, ZUGFeRD, pain) und
  Absturzfehler. Ein Fehler, der nur bei einer Firma auftritt, wird behoben, wenn der richtige Code einfacher ist
  als der falsche; sonst gilt die Regel auch für ihn.
- **Streichpflicht:** Jede Runde schaltet ein Lauf die Regeln der letzten zwei Runden einzeln aus. Ohne Wirkung →
  streichen. Wirkung bei nur einer Firma → in `docs/KONZEPT.md` (Abschnitt 8.4) markieren; ohne zweiten Zeugen
  binnen zwei Runden → streichen.
- Bedienoberfläche und Dokumentation auf Deutsch, Code und Kommentare auf Englisch, Commit-Nachrichten
  deutsch und sachlich; jeder Fehlerfall wird ein Test.

## Eine Prüfrunde

1. Zwei unabhängige Prüfer, jeder in einem eigenen Ordner mit einer Kopie des Codes: eine Firma, die niemand
   kannte (Generator mit Lieferungen, Fallen und Wahrheit im Format von `bench/one.py`), und eine Code- oder
   Bedienprüfung der letzten Runde.
2. Befunde einordnen: Fehler beheben (mit Test), Erkennungsregeln nach der Stopp-Regel, Rest als Grenze.
   Dazu der Ausschaltlauf der Streichpflicht und die Fristen in KONZEPT 8.4 (dort stehen die Regeln auf Bewährung).
3. Eine tragfähige neue Firma kommt in den Prüfstand: `bench/gen/<firma>.py`, Loader in `bench/firms.py`,
   Zeile in `bench/README.md`.
4. Ganzer Prüfstand, `bench/diff.py`, neue Basis; KONZEPT (Runde, Grenzen) und README nachführen.

## Fallstricke

- Während ein Prüfstand läuft, den Code nicht ändern – den Lauf in einer Kopie des Arbeitsstands starten.
- Lange Läufe im Hintergrund starten und auf ihr eigenes Ende warten; nicht mit `pgrep -f` nach einem Befehl
  suchen, der im eigenen Aufruf steht (findet sich selbst).
- Forderungen ohne Rechnung (Miete, Hausgeld, Beiträge) entstehen in `physarum/claims.py` aus dem Zahlungsbild.
  Nächster Schritt: die Einzelposten einer pain.008-Datei als Zahlung je Mitglied – der Verein zieht die meisten
  Beiträge per Sammellastschrift ein und zeigt deshalb nur 4 von 57 offenen Posten. Offen außerdem: Beträge, die nie
  gezahlt wurden (Erhöhung, Neueintritt ohne Zahlung), Jahreszahler (zu wenige Zahlungen für einen Rhythmus).
- „Geld erklärt“ liegt bei einem Drittel: Was unerklärt bleibt, zeigt, wo Physarum noch blind ist.
