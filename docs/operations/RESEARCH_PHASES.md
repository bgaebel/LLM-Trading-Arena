# Forschungsausbau P2–P6

Arbeitsstand: 05.11.2026. Implementierungsschritt, noch keine vollständige Phasenabnahme.

## Implementiert

- P2: Widersprüchliche Kerzenduplikate, falsch ausgerichtete Zeitstempel und unmögliche OHLC-Spannen ablehnen; identische Duplikate deduplizieren.
- P3: Read-only Performancebericht über gemeinsame Equity-Zeitpunkte: Nettorendite, Drawdown, Gebühren, Trades, Turnover, beobachtungsgewichtete Exposure, offene BTC/ETH und Abstand zu Buy & Hold. Gebühren sind in Equity enthalten. FIFO trennt realisierte Ergebnisse und offene Lots; API-Schätzungen und unbekannte Kosten sind separat ausgewiesen.
- P3: Isolierter Replay mit unveränderten Strategien und Ausführungsfunktionen in temporärer SQLite-DB. Keine Netz-/LLM-Aufrufe. Input-Prüfsumme und Prüfung abgeschlossener Kerzen. Walk-Forward mit getrennten Testfenstern und frischem Kapital pro Fold; keine Optimierung auf Testdaten.
- P4: Private vollständige Snapshots vor Modellaufrufen unter `llm-audit/` neben der DB. Entscheidung mit Snapshot-/Prompt-Prüfsumme, konfiguriertem Modell, Latenz und vorhandenen Provider-Tokenzahlen. Kosten bleiben ohne belastbares Preismodell unbekannt. Fehler beim Sichern verhindern die Anfrage.
- P5: Gruppiertes dunkles Terminal mit getrennten Arbeitsflächen, Betriebs-/Kostenstatus, Depot-/Markt-/Zeitraumfiltern und JSON-/CSV-Export. Schmale und zweispaltige Ansicht mit synthetischen Daten im Browser geprüft.

## Verwendung

Aus `apps/arena/`, Ausgabe auf einen neuen privaten Pfad:

```text
python research.py report PATH_TO_DB PATH_TO_REPORT.json
python research.py replay PATH_TO_SNAPSHOTS.json PATH_TO_REPORT.json
python research.py sensitivity PATH_TO_SNAPSHOTS.json PATH_TO_REPORT.json
python research.py walk-forward PATH_TO_SNAPSHOTS.json PATH_TO_REPORT.json --train 100 --test 20
```

Replay-JSON: geordnete Liste mit `at` (UTC-Epochsekunden) und `markets`. Beide Märkte `BTCEUR`/`ETHEUR` sind Pflicht. Je Markt: `bid`, `ask`, `bars`. `bars` enthält Schlüssel `1`, `15`, `60`, `240`; jede Kerze ist `[ts,open,high,low,close,volume]`. Ausschließlich damals bekannte Quotes verwenden, ausreichend Kerzen für alle Indikatoren bereitstellen. Rekonstruierte Quotes als Annahme deklarieren; keine empirische Ausführbarkeit behaupten.

Der tägliche Timer und Pre-Update-Backups sichern SQLite, Audit-Snapshots und Budgetjournal als verifiziertes Paket. Neue lokale EUR-Reservierung schützt die Anfrageplanung; fehlgeschlagene Antworten werden bei vorhandener Nutzung mit erfasst. Preise bleiben explizite Nutzerkonfiguration. Details und Betriebsvertrag 2: [RESEARCH_CONTROLS.md](RESEARCH_CONTROLS.md). Alte Entscheidungen erhalten keine nachträglich erfundenen Snapshots.

## Offene Phasenkriterien

- P2: Reale Feed-/Slippageberichte. Mock-basierte 429-/Disconnect-/Recovery-Tests und dokumentierte REST/WebSocket-Abwägung sind vorhanden; eine reale WebSocket-Vergleichsmessung steht aus.
- P3: Rückrechnung echter Historie und Regime-/Baselineberichte. FIFO-Accounting und isoliertes Sensitivitätsgitter sind implementiert; empirische Auswertung steht aus.
- P4: Abnahme tatsächlicher Anbieter-/Modellpreise, Cache-Sondertarife und wissenschaftliche Ablations-/Triggervergleiche. Lokale Budgetreservierung, Fehlerabrechnung und strenge Rohantwortprüfung sind implementiert.
- P5: Abnahme mit echter Historie und auf dem Zielgerät. Filter, API-Kostenansicht und Browserprüfung mit synthetischen Daten sind erfolgt.
- P6: Kandidaten zunächst als separate Hypothesen mit festgeschriebenen Zeiträumen, Baselines und Widerlegungskriterien untersuchen. Aktivierung erst nach stabilen Baselines, Testbericht und Freigabe.

Die reale Pi-/Historienabnahme bleibt offen. Tokenprotokollierung orientiert sich an der [offiziellen OpenAI-Dokumentation](https://developers.openai.com/api/docs/guides/token-counting); fehlende Providerangaben werden nicht geschätzt.

P6-Versuchsplaene: `experiments/protocols/EXP-001.md` bis `EXP-003.md` (Momentum, Regimefilter, LLM-Ablation); Parameter und Datengrenzen vor Durchfuehrung festlegen.
