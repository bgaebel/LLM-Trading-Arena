# 0003 – Forschungsbetrieb und Audit-Sicherung

Stand: 05.11.2026. Software vorbereitet, reale Pi-Abnahme offen.

Betriebsvertrag 2 erweitert die unveränderte v0.3.1-Trading-Basis um strenge Rohantwortprüfung, private Audit-Snapshots und eine dauerhafte lokale EUR-Reservierung. Deshalb müssen Sicherung und Wiederherstellung SQLite, Audit-Dateien und Budgetjournal zusammen behandeln. Ein Downgrade auf Vertrag 1 würde diese neue Sicherungsinvariante verlieren; der Updater akzeptiert nur Vertrag 2.

Neue Installationen übernehmen eine LLM-Tagesgrenze von null, bis eigene Modellpreise und gewünschtes Budget gesetzt sind. Bestehende Konfigurationen werden nicht ersetzt. Handelsgebühren, Slippage und Strategieregeln bleiben unverändert. API-Kosten werden als lokale Schätzungen ausgewiesen; fehlende Nutzungs-/Preisangaben werden nicht als kostenlos behandelt.

Auf Nutzerwunsch ist die Oberfläche ein kompaktes dunkles Terminal mit getrennten Arbeitsflächen. Die vorherige Kachelwand und Verläufe entfallen. Filter und Exportparameter sind im Browser mit synthetischen Daten geprüft. Die echte Laufzeit-/Historienabnahme steht aus.

Details: [Forschungsbetrieb](../operations/RESEARCH_CONTROLS.md).
