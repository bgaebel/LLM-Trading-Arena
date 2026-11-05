# Forschungsbetrieb: Budget, Audit und vollständige Backups

Stand: 05.11.2026. Betriebsvertrag **2**; SQLite-Schema und Trading-Regeln bleiben v0.3.1. Neue Forschungsauswertungen und der Terminal-Aufbau sind in PR #2 vorbereitet. Echte Pi-/Historien-/Anbieterabnahme bleibt erforderlich.

## EUR-Reservierung vor Modellaufrufen

| Variable | Wirkung |
|---|---|
| `LLM_DAILY_BUDGET_EUR` | Gemeinsame lokale Tagesgrenze für beide Anbieter, UTC. Nicht gesetzt: keine monetäre Sperre. `0`: keine neue LLM-Anfrage. |
| `LLM_CALL_RESERVE_EUR` | Positiver konservativer Betrag, der vor jeder Anfrage dauerhaft belegt wird. |
| `OPENAI_INPUT_EUR_PER_MILLION` / `OPENAI_OUTPUT_EUR_PER_MILLION` | Eigene aktuelle EUR-Preisschätzung für das genau konfigurierte OpenAI-Modell. |
| `ANTHROPIC_INPUT_EUR_PER_MILLION` / `ANTHROPIC_OUTPUT_EUR_PER_MILLION` | Entsprechende EUR-Preisschätzung für das konfigurierte Anthropic-Modell. |

Die neue `.env.example` setzt die Tagesgrenze auf **0**; Preise sind auskommentiert. Erst eigene Preise, Reservierungsbetrag und gewünschte Tagesgrenze konfigurieren. Bestehende `.env`-Dateien werden nicht verändert. Gebühren/Slippage für virtuelle Trades bleiben unabhängig davon unverändert.

Reservierung und Abrechnung liegen dauerhaft im privaten `llm-audit/<DB-Name>.ledger.json`. Noch offene Reservierungen zählen auch nach Neustart gegen die Tagesgrenze. Bei bekannter ungecachter Nutzung wird mit den für diesen Versuch gespeicherten Preisen geschätzt. Fehlerhafte Modellantworten werden ebenfalls abgerechnet, wenn die Antwort verwertbare Nutzungszahlen enthielt. Timeouts und fehlende Nutzungsdaten behalten ihre Reservierung. Nicht gesendete Anfragen, etwa nach einem Snapshot-Schreibfehler, werden mit belegbar null Anbieterkosten freigegeben.

Für Cache-Sondertarife wird kein Preis erfunden: positive Cache-Nutzung hält die Reservierung und bleibt ohne zusätzliche Preislogik monetär unbekannt. Alte Versuche ohne Ledger werden bei aktivierter Tagesgrenze nicht als kostenlos behandelt; weitere Anfragen bleiben für den betroffenen UTC-Tag gesperrt. Lokale `BUDGET_BLOCKED`- und `NOT_SENT`-Einträge sind keine Anbieteranfragen und werden im Kostenbericht entsprechend ausgeschlossen. Der bestehende Versuchszähler begrenzt weiterhin alle lokalen Versuche konservativ.

Dies ist eine **lokale Planungssperre auf Basis eigener Schätzungen**, kein hartes Rechnungs-/Ausgabenlimit beim Anbieter. Eine einzelne Anfrage kann eine zu kleine Reservierung überschreiten. Sobald eine solche Überschreitung bekannt wird, werden weitere Anfragen dieses Tages gesperrt. Preiswerte und Reservierung daher bewusst wählen; für ein verbindliches Anbieterlimit die Anbieter-Kontoeinstellungen verwenden. Keine Zugangsdaten in diese Dokumentation oder Git eintragen.

## Antwortprüfung und Nachvollziehbarkeit

Neue Snapshots enthalten Code-Prüfsummen, vollständige Kerzen und Quotes, Kontext, Kostenannahmen sowie Prompt-Prüfsumme. Die Rohantwort muss genau die vereinbarten Signalfelder enthalten. Widersprüchliche BUY-/SELL-Ziele werden abgelehnt, bevor der bisherige Adapter Felder normalisiert. Prompts und eigentliche Strategiefunktionen bleiben unverändert. Richtlinienkennungen: `strict-signal-v1` und `eur-reservation-v1`.

Providerfehlertexte und Credentials werden nicht gespeichert. Selbst bei Schemafehlern nach einer Antwort bleiben beobachtete Tokenzahlen im Ledger erhalten. Vor jedem weiteren Modellaufruf werden Quotes und Snapshot-Alter erneut geprüft. Ein unterbrochener Feed löst keine zusätzlichen Anfragen mit alten Daten aus.

## Vollständige Pakete statt alleiniger SQLite-Kopie

Der tägliche Timer, Installationsbackup und Pre-Update-Backup verwenden jetzt `scripts/backup_bundle.py`. Ein Paket enthält die SQLite-Sicherung, deren Inventar, die zugehörigen LLM-Snapshots und das Budgetjournal. Jede Datei ist über SHA-256 erfasst; Entscheidungen mit fehlenden/veränderten Snapshot-Referenzen verhindern die Veröffentlichung. Die automatische Rotation behält die 14 zuletzt verwalteten Pakete des jeweiligen Quellpfads. Alte SQLite-Sicherungen und manuelle ZIPs werden nicht automatisch entfernt.

```text
python scripts/backup_bundle.py PATH_TO_DB --destination NEW_PRIVATE_BACKUP.zip
python scripts/backup_bundle.py NEW_PRIVATE_BACKUP.zip --verify
python scripts/backup_bundle.py NEW_PRIVATE_BACKUP.zip --restore-directory NEW_PRIVATE_DATA_DIRECTORY
```

Restore veröffentlicht ausschließlich ein **neues** Datenverzeichnis. Bestehende Dateien/Verzeichnisse werden nicht überschrieben oder zusammengeführt. Geprüft und extrahiert wird dieselbe private Kopie des Pakets. Der ursprüngliche Datenbankname bleibt erhalten. Vor Migration beide Bot-Prozesse stoppen; die Datenverzeichnisse und Sicherungen außerhalb Git halten.

Nach einem Restore werden LLM-Anfragen für den restlichen aktuellen UTC-Tag vorsichtshalber gesperrt: Ein älteres Backup kann externe Ausgaben nach seinem Aufnahmezeitpunkt nicht kennen. Depot-/Tradehistorie und bisherige Kosteneinträge werden dabei nicht verändert. Die Sperre endet am nächsten UTC-Tag; klassische Strategien bleiben verwendbar. Keine Ledger-Dateien löschen, um diese Sperre oder Reservierungen zu umgehen.

Eine neue reine SQLite-Sicherung vermerkt vorhandene Audit-Seitendaten. `restore_db.py` verweigert deren alleinige Wiederherstellung. Für alte v0.3.1-Daten ohne Audit-Dateien bleiben die bisherigen SQLite-Werkzeuge verwendbar.

Der Paket-Timeout des Backupdiensts beträgt jetzt 1.800 Sekunden. Große Audit-Historien erhöhen Speicherbedarf und Laufzeit; lokale Vollpakete ersetzen kein zweites Speichermedium. Während der konsistenten Aufnahme werden Audit-Änderungen während des Staging gesperrt. Unterbrechungen behalten offene Budgetreservierungen konservativ bei. Hart abgebrochene Staging-Verzeichnisse bleiben als temporäre Dateien außerhalb der Rotation erhalten und dürfen erst ohne laufenden Backupjob geprüft werden.

## Betriebsversion und Updates

Der neue Updater unterstützt ausschließlich Betriebsvertrag **2**. Ein automatischer Rücksprung auf Vertrag 1 würde die Sicherung zusätzlicher Audit-/Budgetdaten nicht mehr gewährleisten und wird abgelehnt. Frischinstallation verwendet direkt den geprüften Vertrag-2-Commit.

Bei einer tatsächlich bestehenden Vertrag-1-Installation: Dienst/Timer stoppen, bisherigen Bestand konsistent separat sichern, geprüften Vertrag-2-Code auschecken, `.env` lokal prüfen und den neuen Installer ausführen. Hier wurde bislang keine Pi-Installation ausgeführt; dieser Übergang wurde daher nicht praktisch abgenommen. Nach dem Übergang erfolgen weitere Wechsel über den Vertrag-2-Updater. Keine Schemaänderung und keine Rücksetzung von Portfolios.

## Reports und Terminal

Depot-/Markt-/Zeitraumfilter verwenden dieselbe Validierung in JSON und CSV. Uhrzeiten aus dem Browser werden nach UTC normalisiert. Der Marktfilter betrifft Kurse und Aktivitäten; Depotkennzahlen umfassen beide Märkte. JSON-Historie ist auf 500 Trades/Signale begrenzt und enthält Trunkierungsflags; CSV enthält sämtliche zum Filter passenden Trades.

Der Performancebericht trennt Handelsrendite, bekannte API-Kostenschätzung und einen API-Nettowert, der bei unbekannten Kosten leer bleibt. Realisierte Ergebnisse verwenden FIFO mit proportionalen Kauf-/Verkaufsgebühren. Offene Lots mit Kostenbasis werden getrennt ausgewiesen. Fehlende Eröffnungskäufe führen zu unbekanntem realisiertem Ergebnis statt erfundener Gewinne. Vollständiger Kapitalverlust ist ein gültiger Drawdown von 100 %.

Die dunkle Terminal-Oberfläche verwendet klar getrennte Arbeitsflächen: Marktpreise, Betriebs-/Kostenleiste, Strategieauswertung, Verlauf/Bestände und Aktivitäten. Keine dekorativen Verläufe oder Depot-Kachelwand. Browserprüfung mit synthetischen Daten: Filtern nach Depot/Markt/Zeitraum, Rücksetzen, Exportparameter sowie schmale Ansicht und zweispaltiger Desktop-Aufbau. Diese Demo ist kein Performancebeleg.

## Quellen und verbleibende Abnahme

Bitvavo nennt öffentliche Rate-Limits, eine 15-minütige Sperre bei nicht authentifizierter Überschreitung und den Reset-Zeitstempel im Header. Der Client teilt den 429-Cooldown zwischen Quote- und Kerzenworker; ohne verwertbaren Header wartet er konservativ 900 Sekunden. Die Worker prüfen weiter ihren Zustand und verwenden keine veralteten Quotes für neue Ausführungen. [Bitvavo Rate limits](https://docs.bitvavo.com/docs/rate-limits/), [Handle errors](https://docs.bitvavo.com/docs/errors/).

REST und WebSocket bieten die benötigten Bid-/Ask-Daten. Für den aktuellen kleinen Forschungsaufbau bleibt REST aktiv; ein WebSocket-Wechsel benötigt zusätzlich eine geprüfte Reconnect-/Recovery-Implementierung und Vergleichsmessungen. Es wurde kein eigener ungeprüfter WebSocket-Protokollstack in die Standardbibliothek-Lösung eingebaut. [REST ticker book](https://docs.bitvavo.com/docs/rest-api/get-ticker-book/), [WebSocket ticker book](https://docs.bitvavo.com/docs/websocket-api/get-ticker-book/).

Offen bleiben reale Feed-/Slippageberichte, Anbieter-/Preisabnahme, wissenschaftliche Ablations-/Triggervergleiche, getestete P6-Kandidaten und die tatsächliche Pi-/Historienabnahme. P2–P6 werden nicht pauschal als abgeschlossen markiert.
