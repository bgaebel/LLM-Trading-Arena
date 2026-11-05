# LLM Trading Arena — Projektbriefing und Roadmap für Codex

**Stand:** 05.11.2026  
**Ausgangsbasis:** `LLM_Trading_Arena_v0.3.1_Codex_RaspberryPi5.zip`  
**Zielplattform:** Raspberry Pi 5, Raspberry Pi OS 64-bit, Python 3.11+, privates Git-Repository  
**Modus:** ausschließlich Paper Trading. **Keine Echtgeld-Orders, kein Zugriff auf Bitvavo-Kontoguthaben.**

## 1. Projektvision

Die LLM Trading Arena ist ein dauerhaft laufender, nachvollziehbarer Forschungsaufbau, der algorithmische Handelssysteme und LLM-gesteuerte Agenten für **BTC/EUR und ETH/EUR** unter möglichst gleichen Markt- und Kostenbedingungen vergleicht. Die Kernfrage lautet: **Liefern GPT oder Claude nach Gebühren, Spread und Slippage einen messbaren Vorteil gegenüber klassischen Handelsstrategien und Buy & Hold?**

Nicht Ziel ist eine behauptete Profitabilität. Jede Kennzahl muss aus echten Marktbeobachtungen und *virtuellen*, korrekt gekennzeichneten Orders stammen. Offline-Demo und Live-Paper-Trading müssen jederzeit klar unterschieden bleiben.

## 2. Bestehender Ist-Zustand (v0.3.1)

- **Markt:** öffentliche Bitvavo-REST-API, `BTC-EUR` / `ETH-EUR`; Bid/Ask und OHLCV aus abgeschlossenen Kerzen.
- **Marktbeobachtung:** Kurs-Polling etwa alle 5 Sekunden; quantitativer Signalzyklus etwa alle 60 Sekunden; LLM-Worker prüft etwa alle 20 Sekunden, ob eine Analyse fällig ist. Die LLM-Mindestpause beträgt standardmäßig 1.800 Sekunden je Agent/Markt; Event-Auslöser und tägliche Limits sind konfigurierbar.
- **Agenten/Depots:** GPT, Claude, Trendfolge, Breakout, Mean Reversion, Ensemble, Buy & Hold. Jeder Teilnehmer hat eine separate virtuelle Performance-Historie.
- **Analysezeitbasen:** 1, 15, 60 und 240 Minuten. Indikatoren u. a. EMA, RSI, ATR, ADX; keine unvollständigen Kerzen.
- **Handelsmodell:** virtuelle Spot-Ausführung mit Bid/Ask, konfigurierbarer Taker-Gebühr (`TAKER_FEE=0.0025`) und Slippage (`SLIPPAGE=0.0003`). Keine echten Broker-Orders.
- **Persistenz:** SQLite mit getrennten Entwicklungs-/Live-Daten; lokales Web-Dashboard und CSV-Tradesexport.
- **LLM:** OpenAI- und Anthropic-APIs via `.env`; das Pi-Gerät hostet die großen Sprachmodelle nicht selbst.
- **Pi-Vorbereitung:** `AGENTS.md`, `.gitignore`, systemd-Service, Installationsskript und SQLite-Backup-Helfer liegen im bisherigen Paket vor.
- **Vorhandene Tests:** `python3 -m unittest discover -s tests -v`. Die bisherige Offline-Testabdeckung ist keine Garantie für reale API-Verbindungen oder Langzeitstabilität.

### Bestehende Hauptdateien

| Datei | Zuständigkeit |
|---|---|
| `main.py` | CLI, Dashboard und Markt-/Signal-/LLM-Worker |
| `bitvavo.py` | Öffentliche Quotes, OHLCV |
| `arena.py` | SQLite, Portfolios, LLM-Aufrufe, Kosten und Risiko |
| `strategies.py` | Trend-, Breakout-, Mean-Reversion- und Ensemble-Signale |
| `engine03.py` | Signalzyklen, Buy & Hold, Portfoliovergleich |
| `static/index.html` | Weboberfläche |
| `tests/` | Automatisierte Tests |
| `deploy/`, `scripts/` | Raspberry-Pi-Betrieb und Backup |

## 3. Prinzipien (nicht verhandelbar)

1. **Paper-only:** Niemals Echtgeld-Orderendpunkte implementieren/aufrufen oder Handelsberechtigungen anfordern, solange hierfür kein eigenständiger, ausdrücklich freigegebener Auftrag vorliegt.
2. **Datenkontinuität:** Vorhandene virtuelle Portfolios, Trades und UTC-Zeitstempel erhalten. Keine stillschweigende Zurücksetzung oder Veränderung historischer Trades.
3. **Fairer Vergleich:** Agenten nutzen dieselben Marktdaten und konsistente Gebühren-/Slippage-Annahmen. Strategische Unterschiede explizit dokumentieren.
4. **Keine Zukunftsdaten:** Indikatoren nur aus tatsächlich vorliegenden abgeschlossenen Kerzen; Event- und Publikationszeiten respektieren.
5. **Sicherheit:** Keine API-Keys, `.env`, SQLite-Daten oder Logdateien nach GitHub. Dashboard nicht ungeschützt ins Internet exponieren; standardmäßig nur Loopback, Zugriff über SSH-Tunnel.
6. **Nachvollziehbarkeit:** Jede Entscheidung speichert Agent, Symbol, Signalzeit, Datenzeitstempel, Strategie-/Modellversion, Entscheidungsgrund und angewandte Kostenannahmen.
7. **Fehlertoleranz:** Feed-/LLM-Ausfälle und veraltete Quotes dürfen keine neuen Orders erzeugen. BTC-Fehler darf ETH nicht blockieren und umgekehrt. LLM-Worker darf die Marktabfrage nicht blockieren.
8. **Versionierung:** Strategieänderungen verändern die Versuchsanordnung. Änderungen erst nach dokumentierter Versionierung und neuen Regressionstests aktivieren.
9. **Kostenkontrolle:** Anzahl der LLM-Aufrufe, Tokenverbrauch und geschätzte API-Kosten begrenzen und protokollieren.

## 4. Priorisierte Roadmap

### P0 – Ist-Zustand sichern und reproduzierbar machen

**Aufgaben:** Projektbestand inventarisieren; Tests ausführen; gefährliche Secrets/DBs im Git-Status prüfen; Konfiguration dokumentieren; Ausgangsstand taggen; von Windows-Live-DB konsistente Sicherung erstellen; Schema und vorhandene Historie prüfen. Sicherstellen, dass Demo- und Live-Daten nicht vermischt werden.

**Akzeptanz:** Alle bisherigen Tests grün; keine Secrets im Repository; unveränderte Basis-DB gesichert und Prüfsumme dokumentiert; klares Release-Tag.

### P1 – Raspberry Pi 5 produktionsfest für 24/7-Paper-Trading

**Aufgaben:** ARM64/Raspberry-Pi-OS-Installation validieren; systemd mit kontrolliertem Neustart und sauberem Shutdown; UTC/NTP; Pfade und Dateirechte; SQLite-WAL-Backup und Rotation; Health-Status für Feed, Quant-Worker, LLM-Worker, DB und letzte Entscheidung; Logrotation; Wiederanlauf nach Strom-/Netzausfall; dokumentierter Update-/Rollback-Prozess. Windows-DB nur nach Stop des Windows-Prozesses migrieren.

**Akzeptanz:** Test auf echtem Pi, Reboot- und Offline/Online-Szenarien bestanden; keine doppelten Initialkäufe/Orders; Historie nach Neustart unverändert; Dashboard nur via SSH-Tunnel erreichbar.

### P2 – Marktdatenqualität und realistisches Ausführungsmodell

**Aufgaben:** Bitvavo-Endpunkte mit Live-Daten verifizieren; Quote-Alter, Spread, Feed-Lücken und Uhrzeitdrift messen; Kerzenlücken korrekt behandeln und kenntlich machen; nach Möglichkeit WebSocket statt ausschließlich REST-Polling evaluieren, mit REST-Recovery; belastbare Slippage-Annahmen für unterschiedliche Marktregime; Gebührenparameter explizit je Simulation. Limit-Order-Simulation **nicht** als garantiert ausgeführt modellieren.

**Akzeptanz:** Reproduzierbare Tests für unvollständige Kerzen, Quote-Stale, API-429, Netzwerkunterbrechung, Datenreihenfolge, extreme Spreads und doppelte Events. Keine fiktive Ausführung bei fehlenden Preisen.

### P3 – Forschungsqualität der Strategieauswertung

**Aufgaben:** Equity, Nettorendite, Max Drawdown, Gebühren, Exposure, Trade-Anzahl, Turnover und Benchmark-Vergleich ergänzen; geschlossene und offene Positionen eindeutig unterscheiden; Vergleichszeitraum vereinheitlichen; getrennte Strategieregime/Versionen ausweisen; Backtest- und Walk-Forward-Framework erstellen; Sensitivitätsanalyse zu Gebühren/Slippage; keine Optimierung auf dem späteren Testzeitraum.

**Akzeptanz:** Kennzahlen lassen sich aus Trades und Quotes rekonstruieren; historische Daten und Simulationen klar markiert; jeder Kandidat wird gegenüber Buy & Hold und mindestens einer klassischen Baseline bewertet.

### P4 – LLM-Experimente methodisch sauber durchführen

**Aufgaben:** Strenge JSON-Schemas; ungültige und verspätete Modellantworten sicher ablehnen; Modellname, Promptversion, Kontextgröße, Input-/Output-Tokens, Latenz und Kosten je Entscheidung loggen; GPT/Claude unter vergleichbarer Datenlage evaluieren; ablationsbasierte Tests (Quant-only, LLM-only, Hybrid) entwickeln; Event-Trigger gegen feste Intervalle testen. Keine automatisch freigeschalteten Strategieänderungen durch LLMs.

**Akzeptanz:** Jede LLM-Order lässt sich auf einen gespeicherten Daten-Snapshot und eine Modell-/Promptversion zurückführen; Budgetsperre greift verlässlich; Tests ohne reale API-Schlüssel möglich.

### P5 – Dashboard und Bedienbarkeit

**Aufgaben:** Aktuelle Feedqualität und letzte erfolgreiche Signale deutlich anzeigen; Märkte/Depots getrennt darstellen; Strategieperformance einschließlich Kosten und API-Aufwand; Warnstatus vs. fatalen Fehler unterscheiden; CSV/JSON-Export; Filter für Strategie, Zeitraum und Markt; responsive Ansicht. Optional sichere Benachrichtigung bei Ausfall und täglicher Tagesreport.

**Akzeptanz:** Ohne Quellcodeeinsicht nachvollziehbar, ob der Bot läuft, warum er gerade nicht handelt, wann der letzte valide Kurs einging und ob seine Performance gegenüber Benchmarks besser oder schlechter ist.

### P6 – Erst nach stabilen Baselines: zusätzliche Hypothesen

**Kandidaten:** Momentum-Varianten, Volatilitätsregime, Marktphasenfilter, volatilitätsnormierte Positionsgrößen, Orderbuch-Mikrostruktur (nur mit brauchbarer Live-Feed-Qualität), Nachrichten-Analyse als separates Experiment. Jede neue Strategie gegen unveränderte Baselines unter gleichen Nettokosten testen. Höhere Signalfrequenz nicht mit höherer Qualität gleichsetzen.

**Akzeptanz:** Neue Strategieversionen nur nach dokumentiertem Testbericht und expliziter Freigabe des Nutzers in die laufende Arena übernehmen.

## 5. Reihenfolge und Arbeitsweise für Codex

- Zuerst Repository lesen und **Ist-Zustand mit Code belegen**, keine Annahmen über implementierte Features.
- Erst `P0`, dann `P1`. Nicht gleichzeitig Strategielogik, Speicherformat und Infrastruktur umbauen.
- Kleine nachvollziehbare Pull Requests mit Tests, Änderungsbeschreibung, Migrationshinweisen und Rollback.
- Bestehendes `AGENTS.md` beachten; dieses Dokument als `PROJECT_ROADMAP.md` ins Repository übernehmen.
- Vor jedem Deployment Backups; niemals zwei unabhängige Prozesse auf derselben Live-Simulationshistorie laufen lassen.

## 6. Erster ausführbarer Codex-Auftrag

> Analysiere den gesamten Stand der LLM Trading Arena v0.3.1 anhand des Repository-Codes. Arbeite zunächst nur an **P0 und P1** dieser Roadmap. Führe die bestehenden Unit-Tests aus und dokumentiere Architektur, reale Datenflüsse, bekannte Fehlerquellen sowie notwendige Konfigurationswerte. Sorge für reproduzierbares Raspberry-Pi-5-Deployment mit systemd, Health-Checks, atomaren SQLite-Backups inklusive Retention, kontrolliertem Start/Stop und einem sicheren Rollback. Erstelle Tests für Wiederanlauf, Feed-Ausfall, SQLite-Kontinuität und doppelte Startkäufe. Keine Änderung an Strategieregeln, Gebühren oder LLM-Prompts ohne gesonderte Freigabe. Keine echten Bitvavo-Orders. API-Secrets niemals ins Repository schreiben. Erstelle einen Pull Request mit Tests, Installationsanleitung, Datenmigrationsplan und offenen Risiken. Falls tatsächlicher Pi-Zugriff fehlt, teste Linux-seitig soweit möglich und markiere die Pi-spezifischen Schritte ausdrücklich als ungeprüft.

## 7. Offene Entscheidungen

- Raspberry Pi 5: RAM, SSD/microSD, Netzwerkanbindung und tatsächliche Linux-Benutzerkennung.
- GitHub: privater Repository-Name und gewünschter PR-/Deployment-Prozess.
- Ob Dashboard ausschließlich per SSH-Tunnel oder später über einen authentifizierten privaten VPN-Zugang genutzt werden soll.
- LLM-Budgetobergrenzen und gewünschte Testdauer, bevor Strategieparameter geändert werden.

**Erfolgskriterium des Projekts:** Ein 24/7 laufendes, überprüfbares und faires Paper-Trading-Experiment – nicht ein dekorativer Chart und nicht eine unbewiesene Gewinnbehauptung.
