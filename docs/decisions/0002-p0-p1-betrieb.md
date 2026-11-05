# 0002 – P0/P1-Betriebsvertrag

Datum: 05.11.2026. Status: implementiert; Pi-Abnahme offen.

Betriebsvertragsversion **1** (`apps/arena/deploy/OPERATIONS_VERSION`), Änderungskennung **OPS-P1-001**. Forschungs-/Strategiebasis bleibt v0.3.1. Gebühren, Slippage, Positionsgrößen, Indikatoren, Signalregeln, Modellnamen und Prompts werden nicht verändert.

Neue operative Ausführungssperren: fehlende/inkompatible Datenbank, zweiter Schreiber, unsynchronisierte Pi-Uhr vor Service-Start sowie Shutdown während einer Modellanfrage. Ein beim Shutdown eintreffendes Modellergebnis erhält `CANCELLED` und erzeugt keine neue Entscheidung/Order. Ein abgestürzter Versuch kann `PENDING` bleiben; er zählt weiter zum Tagesbudget und wird nicht stillschweigend neu geschrieben.

SQLite-Schreibtransaktionen reservieren den Schreiber vor dem Lesen der Depotdaten. Dies verhindert konkurrierende Risiko-/Signaländerungen mit veralteten Depotständen. Fehler rollen Entscheidung, Trade und Depot gemeinsam zurück; bestehende Idempotenz-Schlüssel bleiben unverändert. Regressionen stehen in `tests/test_operations.py`.

Health prüft lokal und passiv; keine Probe-Trades, keine zusätzlichen LLM-Kosten. Feed-/Providerprobleme sind degradierter Betrieb, kein automatischer Neustartsturm. Tote/hängende Worker sind Prozessfehler. Startup-/Backup-Prüfungen führen vollständige DB-Integritätskontrollen durch; HTTP-Health bleibt leichtgewichtig.

Automatischer Rollback betrifft nur Code und Units innerhalb Betriebsvertragsversion 1 / unverändertem DB-Schema. Ein Datenrollback würde jüngste Trades verlieren und ist daher kein Teil dieses Ablaufs. `v0.3.1-import` dient als Referenz, nicht als automatisch unterstütztes Rollback-Ziel.

Backups werden als vollständige Dateien atomar sichtbar; separate Manifeste dienen zur Verifikation und Retention. Bei Abbruch zwischen beiden Publikationen bleibt ein vollständiges, nicht automatisch rotiertes Backup erhalten. Unvollständige `.arena-backup-*.tmp` nach hartem Kill werden nicht als Backups erkannt. Manuell nur nach Prüfung und ohne laufendes Backup entfernen.
