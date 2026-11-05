# Windows-Historie übernehmen und Wiederherstellung prüfen

**Nicht mit echten Daten ausgeführt:** Die bisherige Historie liegt laut Nutzer auf einem anderen PC. Entwicklung/Tests verwenden temporäre synthetische DBs.

## Finaler Windows-Snapshot

1. Tatsächliche Quelle ermitteln: Standard `%LOCALAPPDATA%/LLMTradingArena/data/live_v03_bitvavo.sqlite3`, eventuell `LLM_TRADING_ARENA_DATA_DIR`. Bei fehlender DB keine neue erzeugen.
2. Windows-Bot vollständig beenden, automatische Starts deaktivieren. Pi-Dienst ebenfalls stoppen. Neue Schreibsperre schützt nicht gegen alte Versionen oder einen zweiten Rechner.
3. Aktuelle P1-Skripte auf Windows verwenden, aus `apps/arena/`:

```powershell
$sourceDb = "$env:LOCALAPPDATA\LLMTradingArena\data\live_v03_bitvavo.sqlite3"
$migrationDir = "$env:USERPROFILE\ArenaMigration"
New-Item -ItemType Directory -Force -Path $migrationDir
python scripts/check_db.py $sourceDb
python scripts/backup_db.py $sourceDb "$migrationDir\live_v03_bitvavo.sqlite3"
python scripts/backup_db.py "$migrationDir\live_v03_bitvavo.sqlite3" --verify
```

Ziel muss neu sein; für Wiederholungen neuen privaten Migrationsordner verwenden. Original-DB bleibt unverändert. `live_v03_bitvavo.sqlite3.manifest.json` enthält Prüfsumme, Tabellen-Zeilenzahlen und letzte Trade-/Entscheidungszeit. Lokal prüfen/archivieren, **nicht im PR veröffentlichen**.

Schema-, Referenz-, Portfolio- oder Modusfehler an einer Kopie untersuchen. Keine automatische Reparatur/Migration.

## Zum Pi übertragen

Auf dem Pi:

```bash
sudo systemctl stop llm-trading-arena.service  # falls bereits installiert
mkdir -p "$HOME/arena-migration" "$HOME/.local/share/llm-trading-arena"
chmod 700 "$HOME/arena-migration" "$HOME/.local/share/llm-trading-arena"
```

Windows:

```powershell
scp "$migrationDir\live_v03_bitvavo.sqlite3" "$migrationDir\live_v03_bitvavo.sqlite3.manifest.json" BENUTZER@PI_HOST:~/arena-migration/
```

Pi, aus `~/llm-trading-arena/apps/arena`:

```bash
chmod 600 "$HOME/arena-migration/"*
python3 scripts/backup_db.py "$HOME/arena-migration/live_v03_bitvavo.sqlite3" --verify
python3 scripts/restore_db.py "$HOME/arena-migration/live_v03_bitvavo.sqlite3" "$HOME/.local/share/llm-trading-arena/live_v03_bitvavo.sqlite3"
python3 scripts/check_db.py "$HOME/.local/share/llm-trading-arena/live_v03_bitvavo.sqlite3"
```

Restore kopiert zuerst in eine private temporäre Datei im Zielverzeichnis. An dieser Datei werden Quellchecksumme, Live-Modus und Inventar geprüft; erst danach wird genau diese Kopie atomar am Ziel veröffentlicht. Spätere Quelländerungen ändern die geprüfte Zielkopie nicht. Der Ziel-Schreiblock wird gehalten; bestehende DBs/WAL/SHM/Journal-/Manifestdateien werden abgelehnt. **Kein `init-live` vor Erstübernahme.**

Service gemäß [README.md](README.md) installieren/starten. Depots, Trade-Anzahl und Zeitstempel vor Start mit privatem Inventar vergleichen. Nach erstem Tick dürfen neue Equity-/Marktdaten entstehen; historische Trades bleiben vollständig. Windows bleibt gestoppt.

## Wiederherstellungsprobe und Schadensfall

Regelmäßig Sicherung plus Manifest in separates privates Verzeichnis kopieren. `restore_db.py` auf **neuen** Prüffad ausführen, `check_db.py` und Inventarvergleich durchführen. Auf der Kopie keinen Live-Bot parallel starten.

Bei echtem Schaden alle Schreiber stoppen, defekten Bestand einschließlich vorhandener WAL/SHM-Dateien unverändert in privater Quarantäne sichern. Erst nach Ursachenanalyse neuen Zielpfad vorbereiten. Kein automatischer Datenrollback: Trades nach dem Backup fehlen darin und müssen bewusst behandelt werden. `.writer.lock` am ursprünglichen Ort belassen. Migration/Restore auf echter Hardware bleiben Abnahmepunkte.
