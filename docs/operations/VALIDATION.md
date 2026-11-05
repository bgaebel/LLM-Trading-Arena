# P0/P1 – Testnachweis und offene Abnahme

Stand: 05.11.2026. Betriebsvertrag `OPS-P1-001`, Strategiebasis v0.3.1.

## Tatsächlich geprüft

| Prüfung | Ergebnis / Umgebung |
|---|---|
| Ausgangsstand | Alle 19 ursprünglichen Tests unter Windows/Python 3.13 bestanden |
| Erweiterte Suite | 57 Tests, lokal Windows/Python 3.13: 56 bestanden, 1 POSIX-Test bewusst übersprungen |
| Linux-CI | Ubuntu/Python 3.11 und 3.13: alle 57 Tests bestanden, einschließlich echtem SIGTERM |
| Windows-CI | Python 3.11 und 3.13: 56 bestanden, 1 POSIX-Test übersprungen |
| Shell | `bash -n` bestanden (lokal Git Bash und Linux-CI) |
| systemd | Gerenderte Service-/Timer-Units in Linux-CI mit `systemd-analyze verify` akzeptiert; keine Pi-Installation |
| Python | `compileall` bestanden |
| Trading-Vertrag | AST-Vergleich gegen Original-ZIP: Strategiemodul, Kosten-/Risiko-/Ausführungsfunktionen, Modellaufrufe, Prompts und Konstanten unverändert |
| Archiv | SHA-256 der unveränderten Original-ZIP stimmt mit Importmanifest überein |
| Veröffentlichung | Versionierte/Kandidaten-Dateien auf `.env`, Datenbanken, private Backup-Manifeste und typische Credential-Muster geprüft; keine Treffer |

Aktueller Anwendungscode `ad59b12`: [CI-Nachprüfung mit vier erfolgreichen Jobs](https://github.com/bgaebel/LLM-Trading-Arena/actions/runs/41995757799), 57 Tests einschließlich sieben zusätzlicher Review-Regressionen. Befunde und Korrekturen: [P0_P1_REVIEW.md](P0_P1_REVIEW.md).

Historische Nachweise: [50 Tests vor Nachprüfung](https://github.com/bgaebel/LLM-Trading-Arena/actions/runs/41993179806), [ursprüngliche Erweiterung auf 48 Tests](https://github.com/bgaebel/LLM-Trading-Arena/actions/runs/41992019152).

## Abgedeckte Fehlerszenarien

- Reopen/Neustart erhält alle Tabellenzeilen; keine doppelten Startkäufe.
- Zwei konkurrierende Benchmark-Worker erzeugen insgesamt nur zwei Käufe.
- Simulierter Schreibfehler rollt Entscheidung, Trade und Depot vollständig zurück.
- Prozessabbruch während uncommitteter Transaktion erhält ursprüngliche Historie.
- Betriebssystem-Schreiblock blockiert zweiten Prozess und wird nach hartem Prozessende freigegeben.
- WAL-Snapshot enthält committete Daten, nicht uncommittete Änderungen.
- Backupfehler veröffentlicht keine Teilkopie und löscht keine alten Backups.
- Retention behält konfigurierte Anzahl und lässt manuelle/fremde Dateien unberührt.
- Manipulierte Prüfsumme, vorhandenes Restore-Ziel und alte WAL-Seitendatei werden abgelehnt.
- Verifiziertes Restore erhält alle Tabellenzeilen; Original wird nicht überschrieben.
- Feed-Ausfall erzeugt keine Startkäufe; Erholung initialisiert genau einmal.
- Stale Feed leert den Snapshot-Cache; Providerfehler erzeugen keine Trades und keine Secrets in Fehlerlogs.
- Shutdown während Modellantwort protokolliert `CANCELLED` ohne Order.
- Gestorbener Worker führt zu Exit 1; SIGTERM beendet kooperierende Worker auf Linux sauber.
- Health/CSV/Dashboard ändern keine Historie; HTTP bindet nur an Loopback.
- NTP-Preflight lehnt nicht synchronisierte Uhr vor DB-Zugriff ab (gemockte NTP-Abfrage).
- Fehlende Live-DB wird nicht angelegt; explizite Neuanlage überschreibt nichts.
- Update sichert nach Stop vor Codewechsel; Backupfehler verhindert neuen Checkout.
- Fehlerhafter neuer Dienst stellt alten Code/Units wieder her und erhält zwischenzeitliche DB-Ereignisse. Git/systemd sind in diesen Ablauftests gemockt; Backups verwenden echtes SQLite.

Weitere Regressionen der Nachprüfung: Quelländerung während Restore, Inventurprüfung vor Veröffentlichung, fehlgeschlagene Manifest-Erzeugung, verwaiste SQLite-Seitendateien, partieller Unique-Index, verdeckte marktweise Providerfehler und Secret-/SQLite-Dateivarianten in Release-Archiven.

## Noch auf dem Raspberry Pi / Quell-PC zu prüfen

- [ ] Tatsächliche Windows-DB bei gestopptem Altprozess sichern; privates Inventar/Checksumme prüfen.
- [ ] Restore und Portfolio-/Trade-/Zeitstempelvergleich vor dem Pi-Start durchführen.
- [ ] Raspberry Pi OS 64-bit/ARM64, Python ≥3.11, Benutzer/Pfade, Dateirechte und lokales ext4 prüfen.
- [ ] NTP beim Kaltstart sowie nach Netzausfall; Service soll bis zur Synchronisierung warten.
- [ ] Installer mit sudo/systemd/Journal-Namensraum vollständig durchlaufen.
- [ ] Start/Stop, Reboot und Prozessabbruch: erhaltene Historie, keine doppelten Initialkäufe.
- [ ] Netzunterbrechung und Wiederkehr: Health degradiert/erholt sich; keine Ausführung mit veralteten Quotes.
- [ ] Langsamer/ausfallender Provider behindert Quote-Worker nicht; echte API-Verfügbarkeit/Modellnamen lokal prüfen.
- [ ] Timer, verpassten Tageslauf, Retention, Rechte und Wiederherstellungsprobe auf echtem Datenträger prüfen.
- [ ] Update und Code-Rollback mit kompatiblen Release-Commits einschließlich absichtlich fehlerhaftem Kandidaten erproben.
- [ ] Speicherplatz-/Journalwachstum und mindestens 24–72 Stunden Dauerlauf beobachten.
- [ ] Stromverlust/WAL-Recovery nur an einer entbehrlichen Kopie und mit vorheriger externer Sicherung erproben.
- [ ] Netzwerkzugriff: nur Loopback; Dashboard ausschließlich über SSH-Tunnel erreichbar.

Echte APIs, echte Depots, physischer Stromverlust und ARM64-Hardware wurden hier nicht verwendet. P0/P1 sind softwareseitig vorbereitet; die vollständigen Roadmap-Akzeptanzkriterien sind bis zur realen Daten-/Hardware-Abnahme offen.

## Verbleibende Risiken

Lokale Backups sind kein Schutz vor Laufwerksausfall. Hart abgebrochene Backups können ignorierte temporäre Dateien hinterlassen. Historische Equity-/Trade-Daten wachsen ohne automatische Löschung. Ein fehlender Marktquote pausiert weiterhin beide Märkte, weil das bestehende Risikomodell beide Bewertungen benötigt. Modellverfügbarkeit und API-Kosten werden hier nicht verifiziert. Das Repository ist aktuell öffentlich statt wie in der Roadmap vorgesehen privat; keine automatische Sichtbarkeitsänderung.
