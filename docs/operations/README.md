# Betrieb

Die [Pi-Anleitung](../../apps/arena/README_PI_CODEX.md) und die [Anwendungsanleitung](../../apps/arena/README.md) liegen bei der Anwendung. Befehle darin sind aus dem Anwendungsverzeichnis auszuführen.

Bei einem Clone nach `/home/<user>/llm-trading-arena` gilt:

- Anwendung und Arbeitsverzeichnis: `/home/<user>/llm-trading-arena/apps/arena`
- Lokale Konfiguration: `apps/arena/.env`
- Installation aus `apps/arena/`: `bash scripts/install_pi_service.sh`
- Pi-Daten bleiben unter `/home/<user>/.local/share/llm-trading-arena`
- Dashboard bleibt an Loopback gebunden; Zugriff per SSH-Tunnel.

Installer und systemd-Vorlage verwenden den neuen Codepfad. Ein bereits installierter Dienst wird durch diese Dateiumordnung nicht automatisch aktualisiert. Pi-Installation und Dienststart wurden hier nicht ausgeführt.

Update/Rollback, Backup-Retention, Monitoring und Migration der bestehenden Windows-Historie sind offene Roadmap-Arbeiten. Keine Live-Datenbank wurde verschoben oder verändert.
