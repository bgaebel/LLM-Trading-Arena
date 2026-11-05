# Raspberry Pi 5 – Installation und Betrieb

Ziel: Raspberry Pi OS **64-bit**, Python **3.11+**, systemd, ausschließlich Paper Trading. Software unter Windows und Linux-CI geprüft; Pi-Hardware-Abnahme offen: [VALIDATION.md](VALIDATION.md). Keine bestehende Handelsdatenbank befindet sich im Repository.

## 1. Pi vorbereiten

Als regulärer Benutzer mit Home `/home/<user>`:

```bash
sudo apt update
sudo apt install -y python3 git sqlite3 curl
python3 --version
uname -m
sudo timedatectl set-ntp true
timedatectl show --property=NTPSynchronized --value
```

Erwartet: Python ≥3.11, `aarch64`, NTP `yes`. Bei unsynchronisierter Uhr versucht systemd den Start später erneut; die Prüfung nicht deaktivieren. Stromversorgung, Datenträger und Netzwerk vor 24/7-Betrieb prüfen.

```bash
git clone https://github.com/bgaebel/LLM-Trading-Arena.git "$HOME/llm-trading-arena"
cd "$HOME/llm-trading-arena"
# Geprüften, freigegebenen Commit einsetzen; bis zum Merge liegt P1 im PR-Branch.
REVISION='GEPRUEFTER_COMMIT_SHA'
git checkout --detach "$REVISION"
cd apps/arena
cp -n .env.example .env
chmod 600 .env
nano .env
python3 -m unittest discover -s tests -v
```

Konfiguration: [CONFIGURATION.md](CONFIGURATION.md). Schlüssel dürfen zunächst leer bleiben. Beispiel-Modellnamen sind aus v0.3.1 übernommen; ihre Verfügbarkeit wurde nicht durch echte API-Aufrufe geprüft. Bestehende Kosten-/Strategieparameter exakt übernehmen.

## 2. Historie übernehmen oder bewusst neu beginnen

**Bestehende Depots:** [MIGRATION.md](MIGRATION.md) durchführen. Windows-Prozess vor finaler Sicherung stoppen und deaktiviert lassen. Kein `init-live` als Ersatz für fehlende Historie.

**Nur für ein ausdrücklich neues Experiment ohne zu übernehmende Historie:**

```bash
python3 main.py init-live
```

Vorhandene Dateien werden abgelehnt. Live-Start/`once` erzeugen keine Ersatzdatenbank. Linux-Standard: `$HOME/.local/share/llm-trading-arena`, identisch zum Service. Sonderpfade benötigen eine bewusst angepasste Service-/Backup-/Updatekonfiguration.

## 3. Service und Backups installieren

Vorher alle manuellen Arena-Prozesse beenden. Aus `apps/arena/`:

```bash
bash scripts/install_pi_service.sh
systemctl status llm-trading-arena.service
systemctl list-timers llm-trading-arena-backup.timer
journalctl --namespace=llm-trading-arena -u llm-trading-arena.service -n 50
```

Der Installer prüft Tests, NTP und DB, erstellt vor dem Start ein privates Backup, verifiziert gerenderte Units und aktiviert Dienst/Timer. Er erzeugt keine neue Historie. Bei bereits laufendem Dienst den Update-Ablauf verwenden.

Code: `/home/<user>/llm-trading-arena/apps/arena`. DB/Backups liegen außerhalb Git. `UMask=0077`, nur Datenverzeichnis schreibbar, Code/Home read-only im Service. systemd startet nach Prozessfehlern nach 15 s neu und aktiviert den Dienst nach Reboot. Feed-/Providerfehler allein verursachen keinen Neustart.

## 4. Health und Dashboard

```bash
curl -sS http://127.0.0.1:8787/api/health
curl -f http://127.0.0.1:8787/health/live
curl -f http://127.0.0.1:8787/health/ready
```

| Endpunkt | Bedeutung |
|---|---|
| `/health/live` | 200 bei laufendem Supervisor und lesbarer DB; externe Ausfälle dürfen degradiert bleiben |
| `/health/ready` | 200 nur bei frischem Feed, gesunden Workern und ohne beobachteten Providerfehler/ungeprüften aktivierten Provider; sonst 503 |
| `/api/health` | JSON mit denselben Details und Liveness-HTTP-Status |

Enthalten: Worker-Heartbeat/letzter Erfolg, Quote-Alter je Markt, SQLite-Lesbarkeit, letzte Entscheidung und letzter beobachteter LLM-Aufruf je Anbieter und Markt. Ein Fehler eines Markts bleibt auch nach einem Erfolg des anderen Markts sichtbar. LLM `disabled`: kein Schlüssel. `untested`: konfiguriert, noch kein Versuch. `ok`: letzter Versuch erfolgreich, **keine aktive Erreichbarkeitsgarantie**. Keine kostenpflichtigen Health-Probes. Alte `PENDING`-Versuche bleiben auditierbar und werden nach 120 s als degradiert angezeigt. `serve` ist read-only ohne Worker und meldet deshalb keine Service-Liveness.

Vollständige SQLite-Integrität wird bei Start und Backup geprüft; HTTP-Health führt keine Vollprüfung pro Anfrage durch.

Von Windows:

```powershell
ssh -L 8787:127.0.0.1:8787 BENUTZER@PI_HOST
```

Dann `http://127.0.0.1:8787` öffnen. Keine Router-Portfreigabe, kein `0.0.0.0`-Binding.

## 5. Stop, Neustart und Diagnose

```bash
sudo systemctl stop llm-trading-arena.service
sudo systemctl start llm-trading-arena.service
sudo systemctl restart llm-trading-arena.service
journalctl --namespace=llm-trading-arena -u llm-trading-arena.service --since '1 hour ago'
```

SIGTERM stoppt neue Zyklen. Laufende Netzwerkanfragen können bis zum Timeout warten. LLM-Antworten nach Stop erzeugen keine Order. Nach 45 s erzwingt die Anwendung Exit 1, wenn Worker nicht enden; systemd hat ein 60-s-Limit. SQLite-Transaktionen/WAL schützen vor halb geschriebenen Depot-/Trade-Änderungen. Echte Stromverlust-/Datenträgertests bleiben erforderlich.

Ein Zweitprozess scheitert am `.writer.lock`. Lockdatei **nicht löschen**: Der Betriebssystem-Lock wird nach Prozessende freigegeben. Alte Programmversionen und andere Rechner beachten ihn nicht.

Bei `Preflight failed` NTP, Python, Datenpfad, Konfiguration und `python3 scripts/check_db.py "$HOME/.local/share/llm-trading-arena/live_v03_bitvavo.sqlite3"` prüfen. Fehlende/inkonsistente Historie nicht neu initialisieren. Fehlerlogs enthalten bewusst keine Providerantworten/Secrets.

## 6. Backups und Aufbewahrung

Täglich 03:15 UTC plus bis 5 Minuten Verzögerung; `Persistent=true` holt verpasste Termine nach:

```bash
sudo systemctl start llm-trading-arena-backup.service
systemctl status llm-trading-arena-backup.service
journalctl --namespace=llm-trading-arena -u llm-trading-arena-backup.service -n 30
```

Es bleiben die **14 neuesten erfolgreichen automatischen Sicherungen je Quellpfad**. Fehlgeschlagene Backups löschen nichts. Manuelle/Installations-/Pre-Update-Sicherungen werden nicht automatisch gelöscht. Die `.manifest.json` gehört zum Backup: SHA-256, Schema-Fingerprint, Inventar. Beides privat und außerhalb Git halten.

Die SQLite-Backup-API berücksichtigt WAL konsistent. Die endgültige Datei erscheint nach Integritätsprüfung/fsync. Atomare Hardlinks benötigen ein geeignetes lokales Dateisystem, z. B. ext4/NTFS; FAT/exFAT und Netzwerkfreigaben sind nicht unterstützt. Separate verschlüsselte Kopien auf zweitem Medium und regelmäßige Wiederherstellungsproben einrichten. Lokale Backups schützen nicht vor Laufwerksausfall.

Eigener Journal-Namensraum: 200 MB/14 Tage. Nach erfolgreichem Tagesbackup werden SQLite-**Logs** älter als 30 Tage entfernt. Trades, Entscheidungen, LLM-Zähler und Equity bleiben erhalten. Kein automatisches VACUUM; Speicherplatz und Wachstum überwachen.

## 7. Update / Rollback

Siehe [UPDATES.md](UPDATES.md). Vor Wechsel Kandidat offline testen, Dienst stoppen und DB sichern. Code-Rollback spult Datenbestände niemals zurück.

## Technische Referenzen

- [SQLite Online Backup API](https://www.sqlite.org/backup.html)
- [systemd-Service-Vertrag](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml)
- [systemd-Timer](https://github.com/systemd/systemd/blob/main/man/systemd.timer.xml)
- [Journal-Retention](https://github.com/systemd/systemd/blob/main/man/journald.conf.xml)

Nachprüfung der Betriebswege und behobene Befunde: [P0_P1_REVIEW.md](P0_P1_REVIEW.md).
