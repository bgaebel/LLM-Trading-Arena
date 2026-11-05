# 0001 – Repository-Struktur

Datum: 2026-11-05. Status: umgesetzt.

Die v0.3.1-Anwendung wird unter `apps/arena/` eingebettet. Ihre internen Python-Imports, Tests, statischen Dateien und Konfiguration bleiben zusammen. So können später weitere Anwendungen oder gemeinsame Pakete ergänzt werden, ohne Research und Produktivcode zu vermischen.

Eine sofortige Umstellung auf ein installierbares Python-Paket mit `src/` würde Import-, Start- und Teständerungen erfordern und ist nicht Teil dieser Einrichtung.

`research/` enthält Erkenntnisse und Quellen, `experiments/` reproduzierbare Versuchsbeschreibungen, `docs/` dauerhafte Dokumentation und `planning/` den Arbeitsstand. Die zentrale Roadmap bleibt im Projektstamm. Anwendungsbezogene Tests und Deploymentdateien bleiben bei der Anwendung.

Pi-Codepfade wurden auf `apps/arena/` angepasst. Persistente Datenpfade bleiben unverändert. Die ursprüngliche ZIP einschließlich Prüfsummen dient als Referenz.
