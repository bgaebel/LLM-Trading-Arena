> **P0/P1-Betriebsstand:** Installation, Migration, Health, Backups und Updates sind in [docs/operations](../../docs/operations/README.md) beschrieben. Live-Betrieb benötigt eine übernommene DB oder eine ausdrücklich neue Historie via `python main.py init-live`. Demo zuerst mit `python main.py demo` erzeugen. Die nachfolgende v0.3.1-Fachbeschreibung bleibt als Referenz erhalten.

# LLM Trading Arena v0.3.1 · Bitvavo-EUR-Sandbox

**Was sie ist:** Eine lokale Forschungs-Sandbox mit echten **öffentlichen** Bitvavo-Marktdaten und rein virtuellen Orders. **Was sie nicht ist:** ein echtes Trading-Konto, eine Gewinnmaschine, ein realistischer Limit-Order-Matching-Simulator oder ein freigegebenes Echtgeldsystem.

## Installation unter Windows

1. ZIP entpacken, z. B. unter `Dokumente/llm-trading-arena`, **nicht** unter `Program Files (x86)`.
2. Python 3.11 oder neuer installieren (keine zusätzlichen Python-Pakete nötig).
3. **`START_DEMO_WINDOWS.bat`** starten. Der Browser steht unter **http://127.0.0.1:8787**. Diese Demo ist ausdrücklich vollständig synthetisch: keine Bitvavo-Livekurse, keine LLM-Trades.
4. Für echte Livekurse: `.env.example` in **`.env`** umbenennen. Optional deine **OpenAI/Anthropic-API-Schlüssel** eintragen; sie sind nur für diese LLMs notwendig. **Keinen Bitvavo-API-Schlüssel eingeben.** `START_LIVE_WINDOWS.bat` starten. Den Demo-Prozess vorher schließen, da beide den gleichen lokalen Port nutzen.
5. Danach Dashboard unter **http://127.0.0.1:8787** öffnen. Falls GPT/Claude nicht aktiv sind, `.env` prüfen, Startfenster neustarten, Fehlerprotokoll lesen. Das Label `KEY GESETZT` bedeutet nur, dass ein Schlüssel geladen wurde – kein erfolgreicher API-Test.

Zum manuellen Test: `python -m unittest discover -s tests -v`.

Die SQLite-Datenbanken landen unter `%LOCALAPPDATA%\LLMTradingArena\data\` (oder im Verzeichnis `LLM_TRADING_ARENA_DATA_DIR`). **v0.3.1 verwendet dieselben Dateien wie v0.3** `live_v03_bitvavo.sqlite3` und `demo_v03_bitvavo.sqlite3`. Die bisherigen v0.3-Depots und Signale bleiben erhalten; alte v0.2-Ergebnisse werden weder migriert noch vermischt.

## Handelsplatz und Daten

- **BTC-EUR und ETH-EUR**; Startkapital **10.000 EUR für jedes der sieben virtuellen Depots**, kein Hebel, keine Shorts. Jede Strategie hat ein unabhängiges Portfolio.
- Öffentliche Bitvavo-REST-API `GET /v2/ticker/book` (~5 Sekunden) für Geld-/Briefkurse; `GET /v2/{market}/candles` für 1m/15m/1h/4h-Preis-/Volumendaten. Keine privaten Endpunkte und **kein Code für echte Orders**.
- Die Bitvavo-Kerzen-API liefert jüngste Kerzen zuerst. Wir sortieren und **verwerfen jede noch nicht abgeschlossene Kerze anhand ihres UTC-Zeitstempels**.
- Alle Signalberechnungen arbeiten nur mit abgeschlossenen Kerzen. Ältere Timeframes werden zur Schonung der API gecacht.
- Bitvavo liefert laut offizieller Dokumentation für Intervalle ohne Trades keine Kerzen. Wir ergänzen daher bei 1m-Daten **maximal zwei direkt aufeinanderfolgende fehlende Minuten** je Lücke mit unverändertem letztem Schlusskurs und **Volumen 0**. Diese Ergänzung wird in den gespeicherten LLM-Kontexten kenntlich gemacht. Größere Lücken und veraltete Daten bleiben gesperrt.
- **ETH-Fehler stoppen BTC nicht**: Die OHLCV-Analyse wird pro Markt unabhängig ausgeführt; die Ausführung benötigt weiterhin zwei frische Quotes für die gesamte Depotauswertung.
- **Buy & Hold kauft BTC und ETH sofort nach dem ersten frischen, vollständigen Bid/Ask-Abruf**, unabhängig von allen Kerzen und LLMs. Voraussetzung ist, dass beide EUR-Quotes frisch und plausibel sind.
- Ein Kursausfall, eine veraltete Momentaufnahme oder zu wenig Historie führt zu **keinen neuen Trades** (fail closed). Das ist eine Forschungsanwendung und kein hochverfügbares Sicherheitsprodukt.

## Experimentelle Strategien – vorab festgelegt, nicht nachträglich optimiert

| Teilnehmer | Signalbasis | Idee | Schwäche |
|---|---|---|---|
| **Trendfolge** | 1h-EMA24/72, 4h-EMA12/30, 1h-ADX | Trendphasen mitnehmen | Später Einstieg, Fehlsignale in Seitwärtsphasen |
| **Breakout** | 15m-Schlusskurs; 48h-Hoch auf 1h-Daten; 15m-Volumen; 1h-ATR/ADX | Ausbruch mit Volumenfilter | Fehlausbrüche, Schocks |
| **Mean-Reversion** | 15m-RSI14 und Bollinger-ähnliche 20er Standardabweichung; 1h-ADX | Nach Überverkauf und erster Erholung zurück zur Mitte | Gefährlich in starken Abwärtstrends |
| **Ensemble** | Mischung der drei obigen Signalgeber, Regime aus 1h-ADX | Andere Gewichtung für Trend/Range/Übergang | Regime kann falsch erkannt werden |
| **GPT** | Aufbereitete Daten / obige Signale; alle 30 Minuten, bei größeren Ereignissen frühestens nach 10 Minuten | LLM als unabhängiger Bewertungsagent | Teurer, nicht deterministisch, keine bewiesene Alpha-Quelle |
| **Claude** | Wie GPT, eigenes Depot | LLM-Vergleich | Gleiche methodische Risiken |
| **Buy & Hold** | Einmaliger 45-%-Kauf je Asset | Passive Vergleichsbasis | Ungesicherter Marktrückgang |

`HOLD` ist eine reguläre Entscheidung, keine fehlende Datenversorgung. Diese sieben Strategien erzeugen **keine sieben unabhängigen Alpha-Hypothesen**: Ensemble nutzt dieselben Indikatoren; die LLMs sehen die Referenzsignale. Der Vergleich ist explorativ und sollte später durch separate eingefrorene Out-of-sample-Tests ergänzt werden.

## Gebühren und Ausführung

- Standard-Bitvavo-EUR-Spotannahme: **0,25 % Taker pro Seite**, `TAKER_FEE=0.0025`. Die persönliche Gebühr hängt von Orderart, Volumen und evtl. Rabatten ab. **Maker 0,15 %** wird hier bewusst **nicht** als Sofortausführung simuliert, weil Limit-Orders an der Börse nicht garantiert gefüllt werden.
- Zusätzlich `SLIPPAGE=0.0003` (**0,03 % pro Seite**) als frei wählbare Belastung sowie der echte Bid/Ask-Spread der aktuellen Quotes.
- Käufer bezahlen Ask+Slippage, Verkäufer erhalten Bid−Slippage; Gebühren werden separat vom Depot abgezogen.
- Das ist keine Orderbuch-Tiefen-/Fill-Queue-Simulation. Bei schnellen Märkten und bei größeren Orders können real erzielbare Ergebnisse schlechter sein.
- Maximal 45 % pro Symbol und insgesamt 90 % Exposition; Mindest-Rebalance 50 EUR und 2 % des Depots. Strategie-Depots: virtueller Stopp bei 10 % Peak-to-Trough-Drawdown, dann Zwangsliquidation; Buy-and-Hold bleibt als ungesicherte Benchmark bestehen.

## Worker und Kosten

- Kurs- und Risikothread ca. **alle 5 Sekunden** (`MARKET_POLL_SECONDS=5`). Dies ist REST-Polling, **kein WebSocket** und garantiert kein sofortiges Reagieren auf jeden Tick.
- Quantitative Strategien überprüfen aktualisierte geschlossene Bars ca. jede Minute. Trendfolge handelt maximal einmal je neuer 1h-Bar, Breakout/Mean-Reversion/Ensemble je neuer 15m-Bar. Buy-and-Hold kauft einmalig.
- LLM-Thread läuft unabhängig. Standard `LLM_MIN_INTERVAL_SECONDS=1800` (30min/Asset/Agent), `LLM_EVENT_MOVE_THRESHOLD=0.018` (1,8 % Bewegung seit letztem Versuch), `LLM_EVENT_COOLDOWN_SECONDS=600` (10min), `MAX_DAILY_LLM_CALLS=60` pro Agent und UTC-Tag. Dieses Limit ist kein USD-Kostenlimit; zusätzlich Kontobudget beim API-Anbieter setzen.
- **Beachte:** Das Gebührenmodell ist ein Konfigurationswert; eine Änderung im laufenden Versuch verändert die Vergleichsbasis. Für andere Gebühren/Slippage neue Test-Datenbank verwenden.

## Forschung und Tests

1. Vergleich stets **nach Gebühren, Spread und Slippage**; Drawdown sowie Buy-and-Hold als Baseline zeigen.
2. Jede Modellentscheidung wird mit Indikatoren, Zeitpunkt, Quelle und virtuellen Trades gespeichert.
3. Nie die aktuell formende Kerze verwenden (Look-ahead-Bias).
4. Im eigenen Forward-Test mehrere Wochen/Monate pro Marktregime beobachten; ein kurzer Gewinn ist kein statistisch belastbarer Vorteil.
5. Synthetische Demo dient nur dazu, Software und UI zu prüfen. **Sie ist kein Backtest und kein Leistungsnachweis**.

Diese v0.3.1 wurde mit Offline-Unit-Tests und synthetischer Demo überprüft. **Bitvavo-Live-Endpunkte sowie die OpenAI-/Anthropic-API konnten in dieser Umgebung nicht Ende-zu-Ende getestet werden.** Fehler beim ersten Live-Start bitte anhand der Konsolenausgaben melden. Die Bitvavo-WebSocket-Implementierung ist die naheliegende nächste Verbesserung.

### Offizielle Quellen

- https://bitvavo.com/de/fees
- https://docs.bitvavo.com/docs/rest-api/get-ticker-book/
- https://docs.bitvavo.com/docs/rest-api/get-candlestick-data/
- https://docs.bitvavo.com/docs/websocket-api/ticker-subscription/
- https://docs.bitvavo.com/docs/rate-limits/

## Patch v0.3.1 – Startkäufe und Bitvavo-Kerzen

**Ausgangsproblem:** In v0.3 wurde Buy & Hold innerhalb der Multi-Timeframe-Strategie berechnet. Wenn eine ETH-Kerze fehlte, blockierte dies sämtliche quantitativen Strategien einschließlich des BTC/ETH-Benchmarkkaufs.

**Behebung:** Der Kurs-Poller initialisiert Buy & Hold jetzt anhand frischer Bitvavo-Bid/Ask-Kurse, ohne auf Candles warten zu müssen; Wiederholungen nach Neustarts sind ausgeschlossen. Andere Strategien dürfen auf die ersten verlässlichen OHLCV-Signale warten. Fehlerhafte Kerzendaten eines Markts beeinträchtigen den anderen nicht. Der Quote-/Risiko-Poller läuft unabhängig weiter. Diese Version enthält **keine echten Brokerorder-Endpunkte**.

**Upgrade:** Alte v0.3 beenden, ZIP vollständig in einen neuen Ordner entpacken, vorhandene `.env` kopieren und `START_LIVE_WINDOWS.bat` starten. Die Datenbankpfade sind bewusst unverändert. Bitte den alten und den neuen Prozess nicht gleichzeitig starten (Port und SQLite-Zugriffe). Bei einem leeren Benchmarkdepot sollten innerhalb des ersten erfolgreichen Kursabrufs zwei virtuelle Buy-Orders in der Trade-Tabelle erscheinen. Ohne gültigen Live-Kurs gibt es bewusst keinen Kauf. Bei zuvor bereits erfolgten Benchmarkkäufen wird nichts verdoppelt.

**Validierung:** Unit-Tests und lokaler Dashboard-Test, aber in dieser Ausführungsumgebung keine echte Bitvavo- oder LLM-API-Verbindung. Die Live-Reparatur muss vor Ort anhand der Trade-Liste bestätigt werden.
