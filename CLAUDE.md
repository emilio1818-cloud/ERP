# Physarum – Arbeitsanleitung

Ein ERP, das sich aus den Daten einer Firma selbst baut. Worum es geht und warum: `README.md`, ausführlich
`docs/KONZEPT.md` (Abschnitt 7: ehrliche Grenzen, 8: was jede Prüfrunde geändert hat).

## Befehle

```bash
python3 -m unittest discover -s tests          # alle Tests, rund 2½ Minuten
python3 bench/run.py                           # Prüfstand: elf Firmen, je drei bis vier Varianten, rund 8 Minuten
python3 bench/run.py --s0 catering             # schneller Blick: eine Firma, nur unter eigenen Namen
python3 bench/diff.py --without hausverwaltung # was sich gegenüber bench/baseline.json geändert hat
python3 bench/run.py --save                    # neue Basis – erst, wenn diff.py keine Firma schlechter zeigt
python3 bench/keep.py FIRMA ORDNER && python3 -m physarum ORDNER --port 8800   # eine Firma ansehen
```

## Regeln

- **Der Prüfstand ist die Belohnung.** Jede Änderung an Erkennung oder Geld wird an `bench/` gemessen.
- **Stopp-Regel:** Eine neue Erkennungsregel kommt nur hinein, wenn sie auf mindestens zwei Firmen greift
  und keine Kennzahl einer anderen Firma schlechter macht. Sonst ist der Fund eine dokumentierte Grenze
  (KONZEPT Abschnitt 7). Fehler und Bedienprobleme werden allgemein behoben, Standardformate (camt, ZUGFeRD)
  gelesen – beides ist keine Erkennungsregel.
- **Erst löschen** (Raptor): Was nie läuft oder doppelt da ist, fliegt raus; jeder Fehlerfall wird ein Test.
- Bedienoberfläche und Dokumentation auf Deutsch, Code und Kommentare auf Englisch, Commit-Nachrichten
  deutsch und sachlich.

## Eine Prüfrunde

1. Zwei unabhängige Prüfer, jeder in einem eigenen Ordner mit einer Kopie des Codes: eine Firma, die niemand
   kannte (Generator mit Lieferungen, Fallen und Wahrheit im Format von `bench/one.py`), und eine Code- oder
   Bedienprüfung der letzten Runde.
2. Befunde einordnen: Fehler beheben (mit Test), Erkennungsregeln nach der Stopp-Regel, Rest als Grenze.
3. Eine tragfähige neue Firma kommt in den Prüfstand: `bench/gen/<firma>.py`, Loader in `bench/firms.py`,
   Zeile in `bench/README.md`.
4. Ganzer Prüfstand, `bench/diff.py`, neue Basis; KONZEPT (Runde, Grenzen) und README nachführen.

## Fallstricke

- Während ein Prüfstand läuft, den Code nicht ändern – den Lauf in einer Kopie des Arbeitsstands starten.
- Lange Läufe im Hintergrund starten und auf ihr eigenes Ende warten; nicht mit `pgrep -f` nach einem Befehl
  suchen, der im eigenen Aufruf steht (findet sich selbst).
- Nächste große Lücke: Forderungen ohne Rechnung (Miete, Hausgeld, Beiträge) auf einem Personenkonto. Die
  Hausverwaltung zeigt sie; nach der Stopp-Regel fehlt eine zweite Firma.
