# LLM Trading Arena

Forschungsprojekt zum Vergleich klassischer Strategien, GPT, Claude und Buy & Hold für BTC/EUR und ETH/EUR. Ausschließlich Paper Trading.

## Orientierung

| Ort | Inhalt |
|---|---|
| [PROJECT_ROADMAP.md](PROJECT_ROADMAP.md) | Verbindliche Projektbeschreibung, Prinzipien und Roadmap P0–P6 |
| [apps/arena/](apps/arena/) | Lauffähige Python-Anwendung, Dashboard, Tests und Deployment |
| [research/](research/README.md) | Quellen, Hypothesen, Notebooks und Datenkatalog |
| [experiments/](experiments/README.md) | Versionierte Versuchspläne, Auswertungen und lokale Runs |
| [docs/](docs/README.md) | Architektur, Entscheidungen und Betrieb |
| [planning/](planning/README.md) | Arbeitsstand und konkretisierte Aufgaben |
| [archive/releases/](archive/releases/README.md) | Unveränderte Original-ZIP und SHA-256-Inventar |

## Lokal arbeiten

Python 3.11+; die Anwendung verwendet die Standardbibliothek. Aus dem Projektstamm:

```powershell
cd apps/arena
python -m unittest discover -s tests -v
```

Offline-Demo: `python main.py demo`, danach `python main.py serve --demo`.
Die Demo verwendet synthetische Daten. Die Windows-Starter liegen ebenfalls unter `apps/arena/`.

Konfiguration: `apps/arena/.env.example` lokal nach `apps/arena/.env` kopieren.
Live-Start benötigt eine übernommene Historie; nur für neue Experimente zuerst `python main.py init-live`. Live-Paper-Betrieb ist in der [Betriebsanleitung](docs/operations/README.md) beschrieben; LLM-Aufrufe können API-Kosten verursachen.
Für den Pi siehe [Betrieb und Pfade](docs/operations/README.md).

Tests und Startbefehle immer aus `apps/arena/` ausführen. Die bestehenden flachen Python-Imports bleiben damit kompatibel. Eine spätere Paketaufteilung erfolgt als eigene Änderung mit Regressionstests.

Secrets, Laufzeitdatenbanken, Backups und große Forschungsdaten gehören nicht in Git. Es wird keine Live-Datenbank mitgeliefert. Status und offene Validierungen: [planning/STATUS.md](planning/STATUS.md).

P0/P1-Betrieb: [Migration](docs/operations/MIGRATION.md), [Update/Rollback](docs/operations/UPDATES.md), [Validierung und offene Pi-Abnahme](docs/operations/VALIDATION.md).
