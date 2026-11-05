# LLM Trading Arena – Umzug zu Codex + Raspberry Pi 5

**Ausgangsbasis:** vorhandene v0.3.1 Bitvavo Sandbox, **kein neuer Trading-Algorithmus**, **kein Echtgeldhandel**. Der Code ist hardwareunabhängig (Python-Standardbibliothek) und bleibt auf `127.0.0.1` gebunden.

## A. Quellcode zu GitHub / Codex

1. Repository **privat** anlegen, z. B. `llm-trading-arena`.
2. Unter Windows **nur den Quellcode aus diesem ZIP** hochladen (oder im Terminal `git init`, `git add .`, `git commit`, Remote verbinden und `git push`). `.gitignore` schließt `.env`, SQLite-DBs, Backups und Logs aus. Prüfe vor jedem Push mit `git status`, dass keine Schlüssel erscheinen.
3. In ChatGPT Codex Cloud eine Umgebung für dieses GitHub-Repository erstellen und veröffentlichen. Codex bearbeitet den **Quellcode in der Cloud**, der Trading-Bot läuft **auf dem Raspberry Pi**. GitHub ist die Brücke zwischen beidem. Auch Codex Desktop kann den lokalen Repo-Ordner öffnen.
4. `AGENTS.md` enthält die grundlegenden Architektur- und Sicherheitsregeln für Codex. Cloud-Tests benötigen keine echten API-Schlüssel.
5. Codex-Änderungen zunächst als PR prüfen; erst nach Tests auf den Pi aktualisieren.

## B. Pi vorbereiten

Empfohlen: Raspberry Pi 5, offizielles **27-W-USB-C-Netzteil**, Raspberry Pi OS **64-bit (Lite)**, Ethernet, zuverlässiges Speichermedium (SSD bevorzugt), feste DHCP-Zuordnung, SSH. Benutzername im Beispiel `piuser` ersetzen.

Auf dem Pi nach Installation von OS und SSH:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3 git sqlite3
mkdir -p "$HOME/llm-trading-arena"
```

Repo klonen (empfohlen) oder entpackte Quellen nach `$HOME/llm-trading-arena` kopieren:

```bash
git clone <DEINE-PRIVATE-REPO-URL> "$HOME/llm-trading-arena"
cd "$HOME/llm-trading-arena/apps/arena"
cp .env.example .env
nano .env
chmod 600 .env
python3 -m unittest discover -s tests -v
```

**Secrets:** Nur LLM-Schlüssel in `.env`, niemals im Git-Repo, Chat oder Codex-Prompt. Wenn ein Schlüssel versehentlich geteilt oder committed wurde: sperren/rotieren.

### Erst lokal testen

```bash
python3 main.py once
# Erst wenn erfolgreich:
python3 main.py start
```

`once` kann LLM-API-Kosten auslösen. `start` im Terminal mit `Ctrl+C` beenden, bevor systemd gestartet wird. Kein doppelter Prozess mit derselben SQLite-DB.

### Dienst installieren

```bash
cd "$HOME/llm-trading-arena/apps/arena"
bash scripts/install_pi_service.sh
sudo journalctl -u llm-trading-arena -f
```

Dienst steuern:

```bash
sudo systemctl status llm-trading-arena
sudo systemctl restart llm-trading-arena
sudo systemctl stop llm-trading-arena
```

### Dashboard von Windows aus

Da der Bot absichtlich ausschließlich lokal auf dem Pi lauscht, auf dem Windows-PC in PowerShell:

```powershell
ssh -L 8787:127.0.0.1:8787 piuser@raspberrypi.local
```

Solange die SSH-Sitzung besteht: `http://127.0.0.1:8787` auf Windows öffnen. Alternativ die tatsächliche Pi-IP statt `raspberrypi.local` verwenden. Falls auf Windows noch die alte Arena Port 8787 belegt, alten Bot beenden oder einen anderen lokalen Tunnelport wählen, z. B. `-L 8788:127.0.0.1:8787` und dann `http://127.0.0.1:8788`.

**Kein Port-Forwarding über den Router, kein `0.0.0.0`-Binding ohne vorgeschaltete Authentifizierung.**

## C. Laufende Ergebnisse von Windows übertragen

**Wichtig:** Die Version im ZIP enthält nur Programmcode, *nicht* deine bisherigen Orders und Depots. Die müssen vom laufenden Windows-Rechner separat gesichert und übertragen werden.

1. Windows-Bot vollständig stoppen; Pi-Bot ebenfalls stoppen (falls gestartet).
2. Quell-DB bei Windows liegt standardmäßig unter `%LOCALAPPDATA%\LLMTradingArena\data\live_v03_bitvavo.sqlite3` – sofern keine eigene `LLM_TRADING_ARENA_DATA_DIR` gesetzt ist.
3. Bevorzugt die SQLite-Backup-API verwenden, nicht unkontrolliert eine laufende `*.sqlite3` kopieren. Beispiel in PowerShell im Projektverzeichnis:

```powershell
python scripts/backup_db.py "$env:LOCALAPPDATA\LLMTradingArena\data\live_v03_bitvavo.sqlite3" "$env:USERPROFILE\Desktop\live_v03_bitvavo.sqlite3"
```

4. Datei via `scp` übertragen. Auf Pi Zielverzeichnis anlegen und Rechte setzen:

```bash
mkdir -p "$HOME/.local/share/llm-trading-arena"
chmod 700 "$HOME/.local/share/llm-trading-arena"
```

Windows PowerShell:

```powershell
scp "$env:USERPROFILE\Desktop\live_v03_bitvavo.sqlite3" piuser@raspberrypi.local:~/.local/share/llm-trading-arena/live_v03_bitvavo.sqlite3
```

Pi:

```bash
chmod 600 "$HOME/.local/share/llm-trading-arena/live_v03_bitvavo.sqlite3"
sqlite3 "$HOME/.local/share/llm-trading-arena/live_v03_bitvavo.sqlite3" 'PRAGMA integrity_check;'
# Erwartet: ok
sudo systemctl start llm-trading-arena
```

**Nie Windows- und Pi-Bot gleichzeitig mit derselben übernommenen Testhistorie weiterlaufen lassen.** Nach dem Cutover Windows-Prozess deaktivieren; die Daten würden sonst auseinanderlaufen. SQLite-WAL-Dateien nicht einzeln mit scp übertragen. Backup-Skript nutzt SQLite-Backup-API.

## D. Pi-Betrieb: Risiken und Prioritäten

- Pi 5 ist für zwei Märkte und externe LLM-APIs ausreichend; **kein LLM läuft lokal auf dem Pi**. Die Marktanalyse und das Dashboard sind leichtgewichtig. Eigene Modellinferenz wäre ein anderes Projekt.
- Stromausfälle, unzuverlässige Datenträger, Netzstörungen und API-Ausfälle bleiben relevant. Bei Ausfall läuft kein Bot: Monitoring, Backups und Watchdog sind sinnvolle nächste Aufgaben.
- Systemd startet den Dienst nach Reboot automatisch neu; die DB bleibt persistent.
- Zeitsynchronisierung und UTC-basierte Zeitstempel prüfen (`timedatectl`). Für Handelssignale keine Maschine mit massiv falscher Uhr betreiben.
- Ein Pi OS 64-Bit-System mit SSH, Updates und SSD ist langfristig geeigneter als eine SD-Karte mit vielen SQLite-Schreibvorgängen.
- Source bleibt versionskontrolliert, `.env`/DB lokal und privat. Keine echte Orderfunktion ohne separate Freigabe.

## E. Codex-Auftrag für nächsten Schritt

> Untersuche die Trading Arena v0.3.1. Bewahre vollständige Paper-Trading-Isolation und SQLite-Kontinuität. Ergänze belastbare Health-Checks, tägliche konsistente Backups mit Rotation, Telemetrie für Feed-Latenz und LLM-Kosten, einen sicheren Update-/Rollback-Pfad für Raspberry Pi OS 64-bit und Integrationstests mit gemockten Bitvavo-/LLM-Antworten. Führe die Unit-Tests aus. Ändere keine Strategieregeln und keine Gebühren stillschweigend. Erstelle einen Pull Request mit Migrations- und Testbericht.
