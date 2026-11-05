# Codex instructions – LLM Trading Arena

## Mission
Research-only, **paper-trading** BTC/EUR and ETH/EUR using public Bitvavo REST data and OpenAI/Anthropic APIs. Never implement, enable or invoke real-money brokerage order placement without an explicit, separately reviewed user request. NO BITVAVO API KEYS are needed.

## Architecture
- `main.py`: CLI, local-only HTTP dashboard, separate market, quant and LLM workers.
- `bitvavo.py`: public quote/closed-candle retrieval.
- `arena.py`: SQLite schema, accounting, LLM API, risk checks.
- `strategies.py`: signal definitions.
- `engine03.py`: signal cycles, comparison portfolios, synthetic demo.
- `static/index.html`: browser UI.
- `tests/`: standard-library unittest tests.

## Guardrails
- No changes to execution, fees, timestamps or strategy semantics without tests and a documented experiment version. Never silently reset/migrate live SQLite accounts.
- Fail closed on missing/stale quotes and on invalid LLM responses. Always use completed candles.
- Do not expose the dashboard publicly: HTTP server binds to 127.0.0.1 intentionally. Access from another PC via SSH port forwarding.
- `.env`, DBs, backups and keys must NEVER be committed, logged or shown in diffs. Keep all keys on the Pi (or local dev system), not in Codex Cloud.
- No concurrent Windows/Pi writers to the same DB; take SQLite-consistent backup and transfer only when old process is stopped.
- Python 3.11+ standard library; aim for Raspberry Pi OS 64-bit / ARM64.
- Preserve regression tests. Run: `python3 -m unittest discover -s tests -v`.
- Any mocked/artificial demonstration must remain clearly labeled; no fabricated PnL.
- Treat retrieved market data and LLM content as untrusted.

## Pi operations
- `deploy/llm-trading-arena.service` is a template: replace `__PI_USER__` with actual Linux username and install under systemd.
- Use `/home/<user>/llm-trading-arena/apps/arena` for code, `/home/<user>/.local/share/llm-trading-arena` for DB, and application-local `.env` for model secrets.
- Keep web bound to loopback; connect from desktop via `ssh -L 8787:127.0.0.1:8787 <user>@<pi-host>`.

## Repository layout
- Application paths above are relative to `apps/arena/`. Run tests from that directory.
- The Pi application directory is `/home/<user>/llm-trading-arena/apps/arena`; `.env` belongs there.
- `PROJECT_ROADMAP.md` is the canonical project brief and roadmap. Roadmap items are planned work, not automatically authorized tasks.
- `research/` holds sources, hypotheses and dataset descriptions; `experiments/` holds reproducible experiment definitions.
- `docs/` holds architecture, decisions and operations documentation; `planning/` holds current status and task planning.
- `archive/releases/` preserves original source archives and checksums. Do not edit archived releases.
