# Forschungsausbau P2–P6

Arbeitsstand: 05.11.2026. Implementierungsschritt, noch keine vollständige Phasenabnahme.

## Implementiert

- P2: Widersprüchliche Kerzenduplikate, falsch ausgerichtete Zeitstempel und unmögliche OHLC-Spannen ablehnen; identische Duplikate deduplizieren.
- P3: Read-only Performancebericht über gemeinsame Equity-Zeitpunkte: Nettorendite, Drawdown, Gebühren, Trades, Turnover, beobachtungsgewichtete Exposure, offene BTC/ETH und Abstand zu Buy & Hold. Gebühren sind in Equity enthalten; API-Kosten noch nicht.
- P3: Isolierter Replay mit unveränderten Strategien und Ausführungsfunktionen in temporärer SQLite-DB. Keine Netz-/LLM-Aufrufe. Input-Prüfsumme und Prüfung abgeschlossener Kerzen. Walk-Forward mit getrennten Testfenstern und frischem Kapital pro Fold; keine Optimierung auf Testdaten.
- P4: Private vollständige Snapshots vor Modellaufrufen unter `llm-audit/` neben der DB. Entscheidung mit Snapshot-/Prompt-Prüfsumme, konfiguriertem Modell, Latenz und vorhandenen Provider-Tokenzahlen. Kosten bleiben ohne belastbares Preismodell unbekannt. Fehler beim Sichern verhindern die Anfrage.
- P5: Dashboard mit Betriebs-/Feed-/Providerstatus und vergleichbaren Performancekennzahlen; JSON-Export. `/api/performance` und `/api/export.json` unterstützen `start`, `end`, `agent`.

## Verwendung

Aus `apps/arena/`, Ausgabe auf einen neuen privaten Pfad:

```text
python research.py report PATH_TO_DB PATH_TO_REPORT.json
python research.py replay PATH_TO_SNAPSHOTS.json PATH_TO_REPORT.json
python research.py sensitivity PATH_TO_SNAPSHOTS.json PATH_TO_REPORT.json
python research.py walk-forward PATH_TO_SNAPSHOTS.json PATH_TO_REPORT.json --train 100 --test 20
```

Replay-JSON: geordnete Liste mit `at` (UTC-Epochsekunden) und `markets`. Beide Märkte `BTCEUR`/`ETHEUR` sind Pflicht. Je Markt: `bid`, `ask`, `bars`. `bars` enthält Schlüssel `1`, `15`, `60`, `240`; jede Kerze ist `[ts,open,high,low,close,volume]`. Ausschließlich damals bekannte Quotes verwenden, ausreichend Kerzen für alle Indikatoren bereitstellen. Rekonstruierte Quotes als Annahme deklarieren; keine empirische Ausführbarkeit behaupten.

Private LLM-Snapshots gehören zur Sicherungsplanung. Der vorhandene SQLite-Backuptimer sichert die zusätzlichen Dateien noch nicht automatisch. Alte Entscheidungen erhalten keine nachträglich erfundenen Snapshots.

## Offene Phasenkriterien

- P2: Live-Feed-Bericht, 429-/Disconnect-/Recovery-Integrationstests, WebSocket/REST-Vergleich, empirische Slippagekalibrierung.
- P3: Rückrechnung echter Historie, Regime-/Baselineberichte und geschlossene Positionen getrennt ausweisen. Das isolierte Sensitivitätsgitter ist implementiert; empirische Auswertung steht aus.
- P4: Monetäre Budgetreservierung, verifiziertes Preismodell, Abrechnung fehlgeschlagener Requests, strenge Antwortschema-/Ablations-/Triggervergleiche.
- P5: Interaktive Filter, API-Kostenansicht und visuelle Abnahme.
- P6: Kandidaten zunächst als separate Hypothesen mit festgeschriebenen Zeiträumen, Baselines und Widerlegungskriterien untersuchen. Aktivierung erst nach stabilen Baselines, Testbericht und Freigabe.

Die reale Pi-/Historienabnahme bleibt offen. Tokenprotokollierung orientiert sich an der [offiziellen OpenAI-Dokumentation](https://developers.openai.com/api/docs/guides/token-counting); fehlende Providerangaben werden nicht geschätzt.

P6-Versuchsplaene: `experiments/protocols/EXP-001.md` bis `EXP-003.md` (Momentum, Regimefilter, LLM-Ablation); Parameter und Datengrenzen vor Durchfuehrung festlegen.
