<div align="center">

<img src="assets/logo.png" width="140" alt="zt-harvester logo">

# zt-harvester

**Bulk ZeroTwo account creator · session / token / cookie harvester · 9Router auto-connect**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/9Router-compatible-818cf8?style=for-the-badge)](https://9router.com)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI-Compatible-412991?style=for-the-badge&logo=openai&logoColor=white)](#)
[![ZeroTwo](https://img.shields.io/badge/ZeroTwo-app.zerotwo.ai-ec4899?style=for-the-badge)](https://app.zerotwo.ai)
[![Status](https://img.shields.io/badge/status-stable-14b8a6?style=for-the-badge)](#)

*Create ZeroTwo accounts in bulk, harvest their JWT session, cookies and CSRF token, and wire every account into [9Router](https://9router.com) as an OpenAI-compatible provider — end to end.*

[English](README.md) · [Bahasa Indonesia](docs/README.id.md) · [Español](docs/README.es.md) · [日本語](docs/README.ja.md) · [中文](docs/README.zh.md) · [Français](docs/README.fr.md)

</div>

---

## What it does

1. **Creates** N ZeroTwo accounts automatically, each with a disposable mailbox from a mail.tm-compatible provider.
2. **Verifies** the magic link and walks the onboarding wizard (name, interests).
3. **Harvests** the Supabase JWT `access_token`, `refresh_token`, the full cookie jar (incl. `cf_clearance` / `__csrf`), the CSRF token, the account profile, and the complete model catalog.
4. **Connects** every harvested session into **9Router** as an OpenAI-compatible provider connection, so all accounts are reachable through one `/v1` endpoint.
5. **Bridges the protocol gap** with a built-in OpenAI-compatible shim, because ZeroTwo's own API is not OpenAI-shaped.

Everything is written to a crash-safe JSONL ledger you can resume, export or audit.

## Architecture

```
                 +-------------------+        magic link         +------------------+
   create -----> |  mail.tm mailbox  | <------------------------ |                  |
                 +-------------------+                           |                  |
                                                               |   ZeroTwo web /  |
                 +-------------------+     CDP automation        |   API endpoints  |
   drive  ----> |  Chromium (CDP)   | ------------------------> |                  |
                 +-------------------+                           +------------------+
                                                                         |
                              harvest JWT + cookies + csrf               |
                 +-------------------+ <---------------------------------+
                 |     Harvester     |
                 +---------+---------+
                           |
              +------------+-------------+
              |                          |
      +-------v-------+         +--------v---------+
      |  sessions.jsonl|         |  OpenAI shim     |
      +---------------+         |  (port 8787)     |
                                +--------+---------+
                                         |
                                +--------v---------+
                                |     9Router      |
                                |   :20128 /v1     |
                                +------------------+
```

## Install

```bash
git clone https://github.com/0xgetz/zt-harvester.git
cd zt-harvester
pip install -e ".[shim]"
```

## Quickstart

**1. Start the OpenAI-compatible shim** (bridges ZeroTwo → OpenAI wire format):

```bash
export ZT_ZT_COOKIES="cf_clearance=...; __csrf=..."
export ZT_ZT_CSRF="<token from sessionStorage: zerotwo.csrf.token.v1>"
zt-harvester shim --port 8787
```

**2. Launch a browser with remote debugging** (or use a cloud CDP endpoint):

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
```

**3. Create and connect accounts:**

```bash
zt-harvester run \
  --count 5 \
  --cdp-ws "ws://127.0.0.1:9222/devtools/browser/<id>" \
  --router-url "http://localhost:20128" \
  --shim-base-url "http://localhost:8787/v1"
```

Every account lands in `harvest/sessions.jsonl` and in the 9Router dashboard.

## CLI

| Command | Purpose |
| --- | --- |
| `zt-harvester run -n 5` | Create + harvest + connect N accounts |
| `zt-harvester shim -p 8787` | Run the OpenAI-compatible ZeroTwo shim |
| `zt-harvester export -f csv` | Export the harvest ledger |

## Python API

```python
import asyncio
from ztharvester import Harvester, HarvesterConfig

cfg = HarvesterConfig.from_env()
cfg.browser.cdp_ws = "ws://127.0.0.1:9222/devtools/browser/<id>"
cfg.router.shim_base_url = "http://localhost:8787/v1"
asyncio.run(Harvester(cfg).run(count=10))
```

## Configuration

Copy `config.example.toml` and `env.example`:

```bash
cp config.example.toml config.toml
cp .env.example .env
zt-harvester run -n 3 --config config.toml
```

Every field is documented inline in `config.example.toml`.

## Test

```bash
pip install -e ".[dev]"
pytest -q
```

## Project layout

```
src/ztharvester/
  mail.py      mail.tm-compatible disposable mailbox client
  zerotwo.py   sign-up / magic-link / onboarding driver + harvester
  cdp.py       CDP adapters (local websocket, in-process bridge, cloud)
  router9.py   9Router provider-management API client
  shim.py      OpenAI-compatible <-> ZeroTwo protocol bridge
  engine.py    concurrent orchestration + resumable JSONL ledger
  config.py    configuration models
  cli.py       command line interface
tests/
docs/          6 translated READMEs
assets/        logo
```

## Requirements

- Python 3.10+
- A Chromium reachable over CDP (local debug port or a cloud browser)
- A running [9Router](https://9router.com) instance (default `http://localhost:20128`)

## Notes

- ZeroTwo's edge requires the `cf_clearance` cookie and a CSRF token in addition to the JWT; export them to the shim once.
- The shim keeps a single process serving every harvested account — the JWT is read per request from `Authorization`.
- Both ZeroTwo and mail.tm apply per-IP and per-address rate limits. Keep `--concurrency` low (1–2), space out runs, and let the built-in retries handle transient `429`s.
- Use responsibly and only on accounts you are authorised to create.

## License

MIT — see [LICENSE](LICENSE).

<div align="center"><sub>Built for the 9Router ecosystem · not affiliated with ZeroTwo or 9Router</sub></div>
