# Projektstatus

Stand: 05.11.2026

## Einrichtung abgeschlossen

- v0.3.1-ZIP nach `apps/arena/` entpackt; Original mit SHA-256-Manifest archiviert.
- Originale Projektbeschreibung unverändert nach `PROJECT_ROADMAP.md` umbenannt.
- Research, Experimente, Dokumentation und Planung mit Ablagehinweisen angelegt.
- Root-AGENTS.md und repositoryweiter Gitignore eingerichtet.
- Pi-Codepfade in Installer, systemd-Vorlage und Pi-Anleitung angepasst; Datenpfade unverändert.
- Python-Quellen, Tests und übrige Anwendungsdateien per SHA-256 mit dem Original abgeglichen.

## Validierung

19 bestehende Offline-Tests bestanden unter Windows / Python 3.13, ausgeführt aus `apps/arena/` mit `python -m unittest discover -s tests -v`.

Der erste Lauf scheiterte an Sandbox-Zugriffsrechten für temporäre SQLite-Dateien. Der freigegebene Lauf außerhalb der Sandbox war erfolgreich. Archivprüfsumme und Gitignore-Regeln geprüft.

## P0/P1 – Software umgesetzt, reale Abnahme offen

Ausgangsstand versioniert als `v0.3.1-import` (`c292821`). Bestandsanalyse und Konfiguration dokumentiert. Implementiert: Start-/Schemaschutz, Single-Writer-Lock, überwachter Shutdown/Worker-Neustart, passive Health-Endpunkte, atomare WAL-Backups mit Retention und verifiziertem Restore, systemd-Units/Timer/Journal-Retention sowie Code-Update/Rollback ohne Zurücksetzen der Historie.

57 Tests: Linux-CI/Python 3.11 und 3.13 vollständig bestanden; Windows lokal/CI 56 bestanden plus 1 bewusst übersprungener POSIX-Test. Gerenderte systemd-Units in Linux-CI akzeptiert. Nachweise: [Validierung](../docs/operations/VALIDATION.md).

Die echte Historie liegt laut Nutzer auf einem anderen PC. Auf dessen Wunsch hier unabhängig entwickelt. Keine echten API-Aufrufe, keine Datenmigration, keine Installation auf dem Pi. Reale Backup-/Historienprüfung und Pi-/ARM64-/Reboot-/Stromverlustabnahme bleiben offen; P0/P1 werden daher nicht als vollständig abgenommen markiert.

Anleitungen: [Betrieb](../docs/operations/README.md), [Migration](../docs/operations/MIGRATION.md), [Updates](../docs/operations/UPDATES.md). P2–P6 nicht umgesetzt. Strategien, Parameter, Kosten und Prompts unverändert; automatischer Vertragsvergleich gegen Original-ZIP ergänzt. Entwicklung erfolgt im Branch `codex/p0-p1-pi-operations` für einen Pull Request, ohne Merge.

P0/P1-Nachprüfung: Restore prüft die unveränderliche Zielkopie vor Veröffentlichung; Health berücksichtigt LLM-Fehler je Markt. Backup-Zielartefakte, partielle Idempotenz-Indizes und zusätzliche Secret-/SQLite-Dateivarianten werden abgelehnt. [Review-Bericht](../docs/operations/P0_P1_REVIEW.md).

## Forschungsausbau in Arbeit

Branch `codex/research-phases`, Draft-PR #2: isolierter Replay/Walk-Forward/Sensitivitätslauf, gemeinsame Performanceperiode, FIFO-Accounting und API-Schätzungen; persistente EUR-Reservierungen und Fehlerabrechnung; vollständige DB-/Audit-/Budget-Backups mit verifiziertem Restore; strengere Antwort- und Marktdatenprüfung sowie gefiltertes dunkles Terminal.

Betriebsvertrag 2 schützt die zusätzliche Audit-/Budget-Sicherung vor einem automatischen Rücksprung auf Vertrag 1. Neue Installationen erhalten eine LLM-Tagesgrenze von null bis zur lokalen Preiskonfiguration. SQLite-Schema, Strategieparameter, Handelskosten und Prompts bleiben unverändert.

102 lokale Offline-Tests: 101 bestanden, 1 POSIX-Skip unter Windows. JavaScript-Syntax und Shell-Syntax geprüft. Terminal im Browser mit synthetischen Daten geprüft: Depot-/Markt-/Zeitfilter, Rücksetzen, Exportparameter, schmale Ansicht und zweispaltiger Desktop-Aufbau ohne Dokumentüberlauf. Auf Nutzerwunsch dunkles kompaktes Terminal mit klar getrennten Arbeitsflächen statt Kachelwand.

Vollständiger Umfang und noch offene Kriterien: [Forschungsausbau](../docs/operations/RESEARCH_PHASES.md) und [Betriebskontrollen](../docs/operations/RESEARCH_CONTROLS.md). Reale Pi-/Historien-/Anbieter-/Preistests, empirische Slippage-/Regimeberichte sowie Ablations-/Triggervergleiche und getestete P6-Kandidaten bleiben offen. Keine echten Orders oder bezahlten Modellaufrufe durchgeführt. P2–P6 sind nicht vollständig abgenommen.

CI-Nachweis des Anwendungscodes: [102 Tests und JavaScript-Prüfung](https://github.com/bgaebel/LLM-Trading-Arena/actions/runs/42015288728), vier Jobs erfolgreich.
