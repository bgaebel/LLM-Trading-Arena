# Konfiguration

`.env` liegt ausschließlich unter `apps/arena/.env`. Der Loader verwendet `os.environ.setdefault`: Prozess-/systemd-Umgebungswerte haben Vorrang. Keine Exchange-Schlüssel erforderlich. `.env.example` enthält leere LLM-Schlüssel und Beispielwerte; Modellnamen bleiben aus v0.3.1 übernommen und sind hier nicht gegen echte APIs geprüft.

| Variable | Code-Standard | Bedeutung |
|---|---|---|
| OPENAI_API_KEY | nicht gesetzt | GPT deaktiviert ohne Schlüssel |
| ANTHROPIC_API_KEY | nicht gesetzt | Claude deaktiviert ohne Schlüssel |
| OPENAI_MODEL | gpt-6.1-sol | Bestehender Modellname; lokal auf Verfügbarkeit prüfen |
| ANTHROPIC_MODEL | claude-sonnet-5-5 | Bestehender Modellname; lokal auf Verfügbarkeit prüfen |
| TAKER_FEE | 0.0025 | Bestehende Kostenannahme je virtueller Ausführung |
| SLIPPAGE | **0.0005** | Beispielkonfiguration setzt **0.0003**; keine automatische Vereinheitlichung |
| PORT | 8787 | HTTP ausschließlich 127.0.0.1; Service-Preflight verlangt 1024–65535 |
| MARKET_POLL_SECONDS | 5 | Mindestintervall 3 s; Quote-Watchdog max(45 s, 3 × Konfigurationswert) |
| LLM_MIN_INTERVAL_SECONDS | 1800 | Mindestwert 600 s im bestehenden Code |
| LLM_EVENT_MOVE_THRESHOLD | 0.018 | Mindestwert 0.005 |
| LLM_EVENT_COOLDOWN_SECONDS | 600 | Mindestwert 300 s |
| MAX_DAILY_LLM_CALLS | 60 | Je Agent/UTC-Tag, Versuche einschließlich Fehler; 0 deaktiviert neue Calls |
| LLM_TRADING_ARENA_DATA_DIR | siehe unten | Overrides für lokale CLI; Pi-Service setzt den festen externen Datenpfad |

Windows-Standard: `%LOCALAPPDATA%/LLMTradingArena/data`. Linux-Standard seit P1: `$HOME/.local/share/llm-trading-arena`, identisch zum Service. Ein früherer manueller Linux-Start konnte Daten unter `apps/arena/data` angelegt haben: diese zuerst sichern und bewusst migrieren, niemals mit `init-live` umgehen.

Dateien: `live_v03_bitvavo.sqlite3` und `demo_v03_bitvavo.sqlite3`. Kein automatisches Fallback von Live auf Demo. `serve --demo` benötigt eine zuvor mit `demo` erzeugte Demo-Datei.

Betriebswerte sind in versionierten Units festgelegt: Neustart 15 s, Stop-Limit 60 s, Worker-Stillstand 45/180/240 s (Quotes dynamisch wie oben), täglicher Backup-Timer 03:15 UTC plus bis 5 min Zufallsverzögerung, 14 automatische Backups, Betriebslogs in DB 30 Tage, eigener Journal-Namensraum 200 MB persistent / 50 MB flüchtig / maximal 14 Tage. Änderungen an diesen Units als überprüften Code-Release ausrollen.

Konfigurationen enthalten Secrets und bleiben außerhalb Git. Vor Updates lokal sichern; der Updater verändert `.env` nicht und kontrolliert deren Hash. Bestehende Gebühren-/Strategieparameter beim Transfer exakt übernehmen.

## Forschungsbetrieb / Betriebsvertrag 2

Monetäre Reservierung, vier Modellpreisvariablen, unveränderte bestehende `.env`-Dateien und vollständige Audit-/Budget-Backups: [RESEARCH_CONTROLS.md](RESEARCH_CONTROLS.md). Die neue Beispielkonfiguration sperrt LLM-Anfragen zunächst mit `LLM_DAILY_BUDGET_EUR=0`. Vor Freischaltung eigene EUR-Modellpreise und Reservierung konfigurieren. Die Backup-Unit verwendet jetzt vollständige ZIP-Pakete und ein Zeitlimit von 1.800 Sekunden.
