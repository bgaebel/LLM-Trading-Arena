# Architektur

Die Anwendung liegt als zusammenhängende Einheit unter `apps/arena/`:

| Datei/Ordner | Zuständigkeit |
|---|---|
| `main.py` | CLI, Dashboard und Worker |
| `bitvavo.py` | Öffentliche Marktdaten |
| `arena.py` | SQLite, virtuelle Portfolios, Risiko und LLM-Anbindung |
| `strategies.py` | Quantitative Strategien |
| `engine03.py` | Signalzyklen und Portfoliovergleich |
| `static/` | Weboberfläche |
| `tests/` | Bestehende Offline-Regressionstests |
| `scripts/`, `deploy/` | Backup und Pi-Service |

Dies ist eine Strukturübersicht, kein abgeschlossener Architektur- oder Sicherheitsaudit. Eine detaillierte Untersuchung der Datenflüsse gehört zu P0.

Detaillierte Bestandsanalyse, Datenflüsse und P0/P1-Befunde: [P0_BASELINE.md](P0_BASELINE.md).
