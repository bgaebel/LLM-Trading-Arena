# Sichere Code-Updates und Rollback

Voraussetzung: P1-Service aktiv, sauberer Git-Arbeitsbaum, Standarddatenpfad und unveränderte lokale `.env`. Unterstützt werden Releases mit `deploy/OPERATIONS_VERSION=1` und unverändertem v0.3.1-Schema. **Keine DB-Migration.** `v0.3.1-import` ist kein automatisches Rollback-Ziel: Dort fehlt der neue Betriebsvertrag.

Aus `~/llm-trading-arena/apps/arena`, als regulärer Pi-Benutzer:

```bash
python3 scripts/deploy_release.py GEPRUEFTER_COMMIT_SHA_ODER_TAG
```

1. Installation/Arbeitsbaum prüfen, sudo authentifizieren, Git-Refs aktualisieren, Ziel zu exaktem Commit auflösen.
2. Kandidaten per `git archive` temporär entpacken. Symlinks/Pfadtraversal, Laufzeitdateien und inkompatible Betriebsversion ablehnen. Offline-Tests ohne geerbte LLM-Schlüssel ausführen. Die Arena läuft bis dahin weiter.
3. Deployment-Lock setzen, Arbeitsbaum erneut prüfen. Backup-Timer/-Job und Dienst stoppen. DB-Schreiblock übernehmen.
4. Historie prüfen, verifiziertes Backup unter `~/.local/share/llm-trading-arena/pre-update/` anlegen. Kandidat muss bestehende DB read-only akzeptieren.
5. Exakten Commit auschecken (`detached HEAD`), unveränderte Konfiguration per Hash prüfen, Units installieren/laden. Lock freigeben und Dienst starten.
6. Bis 60 s auf lokale Liveness warten; Antwort muss zur systemd-PID passen. Externe Markt-/Providerprobleme dürfen weiterhin `degraded` sein. Zuvor aktiven Backup-Timer wieder starten.
7. Fehler nach Stop: Dienst stoppen, **alten Code und alte Units** zurückholen, dieselbe aktuelle DB prüfen/starten. Kein Backup überschreibt die aktuelle Historie. Scheitert auch diese Wiederherstellung, Dienstzustand und Journal manuell untersuchen; das Werkzeug meldet einen Fehler.

## Bewusster Rollback

Derselbe Befehl mit älterem **kompatiblem** geprüftem Commit. Alte/neue Commit-SHAs lokal dokumentieren. Code-Rollback bewahrt Trades seit dem Update. `.env` wird weder ersetzt noch versioniert.

Schema-/Strategieänderungen benötigen eigenen Migrations-/Experimentauftrag. Keine ungeprüften Codewechsel über einen laufenden Prozess, kein Hard-Reset und keine ältere DB als Ersatz für einen Code-Rollback.

## Nachkontrolle

```bash
systemctl status llm-trading-arena.service
systemctl list-timers llm-trading-arena-backup.timer
curl -sS http://127.0.0.1:8787/api/health
journalctl --namespace=llm-trading-arena -u llm-trading-arena.service -n 50
```

Revision, erwartete Modellkonfiguration, Feed-Erholung, unveränderte alte Trades und fehlende doppelte Startkäufe prüfen. Pre-Update-Backups erst nach dokumentierter Abnahme und separater Kopie ausdünnen.

**Validierungsgrenze:** Ablauflogik inklusive Backupfehler und fehlerhaftem neuem Dienst ist mit echten temporären SQLite-Dateien und gemockten Git-/systemd-Aufrufen getestet. Kompletter Rollout mit sudo/systemd/echter Konfiguration/Reboot bleibt Pi-Abnahme.
