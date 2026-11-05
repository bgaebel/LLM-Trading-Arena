# P0 – Bestandsanalyse v0.3.1

Stand: 05.11.2026. Referenz: Tag `v0.3.1-import`, Commit `c292821`; unverändertes Originalarchiv mit SHA-256-Manifest unter `archive/releases/`. Der Import-Tag enthält bereits die zuvor beauftragte Ordnerstruktur und angepasste Pi-Codepfade.

## Tatsächlicher Datenfluss

1. `main.quote_worker` fragt über `bitvavo.quotes` den öffentlichen `/v2/ticker/book` ab (eine gemeinsame Anfrage für BTC-EUR/ETH-EUR). `Quote.validate` prüft Preise und Spread. `record_live_quotes` speichert Marktstände und Ticks, aktualisiert virtuelle Equity und prüft das bestehende Drawdown-Limit. `initialize_buyhold` legt einmalig den virtuellen Benchmark an.
2. `signal_worker` liest frische Quotes aus SQLite und lädt über `live_snapshots` abgeschlossene Kerzen für 1/15/60/240 Minuten. Kerzen werden gecacht. Kleine 1-Minuten-Lücken werden bereits im Ausgangscode mit höchstens zwei Nullvolumen-Kerzen rekonstruiert. Ungültige Kerzen eines Markts pausieren diesen Markt.
3. `quant_cycle` ruft unveränderte Funktionen aus `strategies.py` auf. Trend folgt 60-Minuten-, Breakout/Mean-Reversion/Ensemble folgen 15-Minuten-Kerzen. Entscheidungen werden über `(agent,symbol,bar_ts)` dedupliziert; das Benchmark-Sentinel ist `bar_ts=-1`.
4. Der getrennte LLM-Worker übernimmt Snapshots unter einem Thread-Lock. `llm_due` prüft Intervall/Ereignis; `llm_calls` reserviert ein Tageskontingent vor dem API-Aufruf. Antworten werden validiert und vor virtueller Ausführung erneut auf Quote-/Snapshot-Alter geprüft. Kosten und Prompts bleiben unverändert.
5. `record_decision` speichert Entscheidung und gegebenenfalls virtuellen Trade. `trade_to_target` verändert ausschließlich SQLite. Es existiert kein privater Bitvavo-Client und kein echter Orderpfad.
6. Dashboard/CSV lesen SQLite. Seit P1 sind HTTP-Datenbankverbindungen ausdrücklich read-only; sie initialisieren weder Schema noch Portfolios.

## SQLite-Bestand

| Tabelle | Inhalt / Erhaltung |
|---|---|
| portfolios | Sieben getrennte virtuelle Depots, Cash, BTC, ETH, Peak, Halt-Flag |
| decisions | UTC-Zeitpunkt, Agent, Markt, Signal, Modell, Begründung, Inputs, Status; Unique-Schlüssel |
| trades | Virtuelle Ausführungen einschließlich Gebühren, Slippage und Entscheidungsreferenz |
| market | Letzter Marktstand pro Symbol und Herkunft |
| market_ticks | Kurzfristiger Kursverlauf; bestehende Löschung älter als zwei Tage bleibt unverändert |
| equity | Performancehistorie; `(ts,agent)` eindeutig |
| llm_calls | Persistente Versuchszähler und Status je Agent/Markt |
| logs | Betriebsnachrichten; P1 entfernt nach erfolgreichem Backup Einträge älter als 30 Tage |

Schema und `user_version=0` bleiben unverändert. Keine Migration, keine Neuberechnung historischer Trades. Betriebsprüfungen kontrollieren Integrität, Fremdschlüssel, erforderliche Spalten, Portfolio-Set und Idempotenz-Indizes. Vorhandene inkompatible Daten werden abgewiesen, nicht repariert. Private Backup-Manifeste enthalten Zeilenzahlen, Schema-Hash und letzte Zeitstempel; keine solchen Manifeste im Repository.

## Befunde vor P1 und Umsetzung

| Befund | Änderung / verbleibende Grenze |
|---|---|
| SIGTERM beendet den Prozess ohne koordiniertes Warten | Stop-Event, Join bis 45 s; danach Exit 1; systemd Stop-Limit 60 s |
| Gestorbene Threads lassen Dashboard weiterlaufen | Supervisor erkennt Tod/Stillstand und beendet mit Fehler für systemd-Neustart |
| Zwei Prozesse können dieselbe Datei schreiben | Betriebssystem-Lock für CLI-Schreibbefehle; alte Versionen und andere Rechner kennen diesen Lock nicht |
| Start kann bei falschem Pfad neue leere Historie anlegen | Live-Start verlangt vorhandene validierte DB; Neuanlage nur explizit mit `init-live` |
| Worker und HTTP öffnen Schema/Portfolios erneut | Worker verbinden mit `mode=rw`, HTTP mit `mode=ro`; kein automatisches Nachinitialisieren |
| Risiko- und Signalworker lesen Depots vor Schreibreservierung | `BEGIN IMMEDIATE` serialisiert transaktionale Depotänderungen; Regression für vollständigen Rollback |
| Veraltete Snapshots bleiben im Arbeitsspeicher | Cache bei Feed-/Strategiefehler leeren; beim Stop eintreffende LLM-Antwort verwerfen |
| Backupdatei wird direkt am endgültigen Pfad aufgebaut | SQLite-Backup-API, Integritätsprüfung, fsync und atomarer Hardlink ohne Überschreiben |
| Fehler können Providerantworten enthalten | Nur Fehlerklasse, keine Antworttexte/Headers in neuen Fehlerlogs |
| Kein Backup-Zeitplan / keine Retention | Täglicher Timer, 14 erfolgreiche automatische Sicherungen je Quelldateipfad |
| Kein Update-/Rollback-Ablauf | Kandidat offline testen, stoppen, sichern, Code wechseln, PID-geprüfte Liveness; bei Fehler Code zurück |

## Offene Grenzen

- Echte Historie liegt laut Nutzer auf einem anderen PC. Hier weder geprüft noch gesichert; keine Behauptung eines abgeschlossenen P0-Daten-Cutovers.
- Gemeinsamer Quote-/Risikozyklus verlangt weiterhin **beide** frischen Märkte. Ein fehlender Quote kann beide Märkte pausieren; Kerzenfehler sind dagegen marktweise isoliert. Änderung dieser Portfolio-/Risikosemantik ist außerhalb P0/P1.
- `SLIPPAGE` ohne Konfiguration: `0.0005`; `.env.example`: `0.0003`. Dieser Unterschied ist Bestandsverhalten und bleibt erhalten.
- Modelle und API-Verfügbarkeit wurden nicht online validiert. Health ist passiv und löst keine kostenpflichtigen Probes aus. Vollständige Modell-/Prompt-/Tokenversionierung gehört zu P4.
- Ein laufender SQLite-Prozess kann bei vollständigem Datenträger keine Historie speichern. Health/Logs zeigen Fehler; Speicherplatz und Datenträger müssen auf dem Pi überwacht werden.
- Equity- und Handelshistorie wachsen weiter; keine ungefragte Löschung historischer Performance-Daten.
- GitHub-Metadaten zeigten am 05.11.2026 ein **öffentliches** Repository. Das widerspricht dem privaten Ziel aus der Roadmap; Sichtbarkeit wurde nicht eigenständig verändert.
