# P0/P1 – Nachprüfung und Korrekturen

Stand: 05.11.2026. Geprüfter Ausgangspunkt: PR #1, Commit `c1f7eb2`. Korrekturcommit: `ad59b12`. Gezielte Eigenprüfung der Betriebs- und Datenintegritätspfade; kein externes Review und keine Pi-Hardware-Abnahme.

## Nachgewiesene Befunde

| Priorität | Auslöser und bisheriges Verhalten | Korrektur |
|---|---|---|
| P1 | Eine Backup-Quelle ändert sich zwischen Prüfsummenprüfung und Restore. Wenn Zeilenzahlen/letzte Zeitstempel gleich bleiben, konnte ein anderer Depotstand importiert werden. Eine abweichende Zielinventur wurde zudem erst nach Veröffentlichung festgestellt. | Restore kopiert zunächst privat ins Zielverzeichnis. SHA-256, Live-Modus und Inventar werden an genau dieser Kopie geprüft. Erst danach wird dieselbe Datei atomar veröffentlicht. |
| P2 | Ein späterer erfolgreicher ETH-Aufruf verdeckte einen vorherigen BTC-Fehler desselben LLM-Anbieters; Health meldete insgesamt `ok`. | Letzte Beobachtung pro Anbieter **und Markt**. Der Gesamtstatus berücksichtigt beide Märkte; ein Fehler wird nicht durch Erfolg im anderen Markt aufgehoben. |
| P2 | Bei einem neuen Backup-Ziel mit altem Manifest oder SQLite-Seitendateien konnte bereits eine DB veröffentlicht werden, bevor der Vorgang scheiterte. Auch Fehler beim Schreiben des Manifests traten erst nach DB-Veröffentlichung auf. | DB, WAL, SHM, Journal und Manifest müssen fehlen. Manifest wird vorbereitet und synchronisiert, bevor DB/Manifest veröffentlicht werden. |
| P2 | Die Schema-Prüfung akzeptierte einen partiellen Unique-Index als vollständige Idempotenzgarantie, obwohl dieser nur einen Teil der Entscheidungen schützt. | Nur nicht-partielle eindeutige Indizes mit den erforderlichen Spalten werden akzeptiert. Keine Reparatur/Änderung der geprüften Datenbank. |
| P2 | Release-Archive wurden auf `.env`/DB-Dateien geprüft, aber `.env.production`, WAL/SHM/Journal und DB-Manifeste konnten diesen Filter passieren. | Prüfung umfasst diese Dateivarianten; Abbruch vor Kandidatentests oder Dienststop. `.env.example` bleibt zulässig. |

## Regressionen

Sieben zusätzliche Tests in `tests/test_operations.py` und `tests/test_deployment.py`:

1. Quelle wird direkt nach Hashberechnung verändert; Restore erhält trotzdem den exakt geprüften Depotstand.
2. Abweichende Inventur verhindert die Veröffentlichung des Restore-Ziels.
3. Simulierter Fehler beim Schreiben des Manifests veröffentlicht weder Backup- noch Restore-Zieldatei.
4. Vorhandene WAL-/SHM-/Journal-/Manifestdateien bleiben unverändert und verhindern das Backup am gleichen Ziel.
5. Partieller Unique-Index wird ohne Schemaänderung abgelehnt.
6. BTC-Providerfehler bleibt nach späterem ETH-Erfolg sichtbar; Readiness ist falsch, Liveness bleibt wahr.
7. Verbotene Secret-/SQLite-Dateivarianten in Release-Archiven werden vor Tests abgelehnt.

Die ersten sechs hinzugefügten Testmethoden reproduzierten die Befunde vor der Korrektur; der zusätzliche Manifest-Schreibfehlertest sichert die überarbeitete Veröffentlichungsreihenfolge ab. Lokal umfasst die Suite nun 57 Tests: 56 bestanden, der POSIX-SIGTERM-Test ist unter Windows bewusst ausgenommen. CI-Nachweis: [VALIDATION.md](VALIDATION.md).

Zusätzlich werden SQLite-Verbindungen beim Backup auch dann geschlossen, wenn das Öffnen der temporären Zieldatei scheitert. Strategien, Gebühren, Risikoparameter, Prompts und Schema bleiben unverändert; der bestehende Trading-Vertragstest bleibt aktiv.

## Verbleibende Grenzen

DB und Manifest benötigen zwei atomare Dateiverknüpfungen. Ein harter Abbruch zwischen beiden kann weiterhin eine **vollständige** DB ohne Manifest hinterlassen; die automatische Retention ignoriert sie. Dies ist kein teilweise geschriebenes SQLite-Backup. Echte Hardware-, Stromverlust-, Datenmigrations- und systemd-Lifecycle-Tests bleiben offen. Details in der [Abnahmeliste](VALIDATION.md).
