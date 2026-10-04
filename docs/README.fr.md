<div align="center">

<img src="../assets/logo.png" width="140" alt="zt-harvester logo">

# zt-harvester

**Créateur de comptes ZeroTwo en masse · collecteur de session / jeton / cookies · connexion auto à 9Router**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/9Router-compatible-818cf8?style=for-the-badge)](https://9router.com)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI-Compatible-412991?style=for-the-badge&logo=openai&logoColor=white)](#)
[![ZeroTwo](https://img.shields.io/badge/ZeroTwo-app.zerotwo.ai-ec4899?style=for-the-badge)](https://app.zerotwo.ai)
[![Status](https://img.shields.io/badge/status-stable-14b8a6?style=for-the-badge)](#)

*Créez des comptes ZeroTwo en masse, collectez leur session JWT, cookies et jeton CSRF, puis connectez chaque compte à [9Router](https://9router.com) comme fournisseur compatible OpenAI — de bout en bout.*

[English](../README.md) · [Bahasa Indonesia](README.id.md) · [Español](README.es.md) · [日本語](README.ja.md) · [中文](README.zh.md) · [Français](README.fr.md)

</div>

---

## Ce que ça fait

1. **Crée** N comptes ZeroTwo automatiquement, chacun avec une boîte jetable d'un fournisseur compatible mail.tm.
2. **Vérifie** le lien magique et complète l'assistant d'intégration (nom, centres d'intérêt).
3. **Collecte** le JWT Supabase `access_token`, `refresh_token`, tous les cookies (dont `cf_clearance` / `__csrf`), le jeton CSRF, le profil et le catalogue complet des modèles.
4. **Connecte** chaque session collectée à **9Router** comme fournisseur compatible OpenAI, de sorte que tous les comptes soient accessibles via un seul endpoint `/v1`.
5. **Comble** l'écart de protocole avec un shim compatible OpenAI, car l'API ZeroTwo n'est pas au format OpenAI.

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

## Installation

```bash
git clone https://github.com/0xgetz/zt-harvester.git
cd zt-harvester
pip install -e ".[shim]"
```

## Démarrage rapide

**1. Lancez le shim compatible OpenAI** (relie ZeroTwo → format OpenAI) :

```bash
export ZT_ZT_COOKIES="cf_clearance=...; __csrf=..."
export ZT_ZT_CSRF="<token from sessionStorage: zerotwo.csrf.token.v1>"
zt-harvester shim --port 8787
```

**2. Lancez un navigateur avec le débogage distant** (ou un endpoint CDP cloud) :

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
```

**3. Créez et connectez des comptes :**

```bash
zt-harvester run \
  --count 5 \
  --cdp-ws "ws://127.0.0.1:9222/devtools/browser/<id>" \
  --router-url "http://localhost:20128" \
  --shim-base-url "http://localhost:8787/v1"
```

Chaque compte est enregistré dans `harvest/sessions.jsonl` et dans le tableau de bord 9Router.

## CLI

| Commande|Objet | |
| --- | --- |
| `zt-harvester run -n 5` | Créer + collecter + connecter N comptes |
| `zt-harvester shim -p 8787` | Lancer le shim ZeroTwo compatible OpenAI |
| `zt-harvester proxies --check` | Lister et tester le pool de proxys |
| `zt-harvester export -f csv` | Exporter le registre |

## Pool de proxys

Répartissez les limites par IP en faisant tourner l'IP de sortie par compte. Le pool accepte le format courant `host:port:user:pass`.

```bash
zt-harvester run -n 10 --proxy-file proxies.txt
zt-harvester proxies --proxy-file proxies.txt --check
```

## API Python

```python
import asyncio
from ztharvester import Harvester, HarvesterConfig

cfg = HarvesterConfig.from_env()
cfg.browser.cdp_ws = "ws://127.0.0.1:9222/devtools/browser/<id>"
cfg.router.shim_base_url = "http://localhost:8787/v1"
asyncio.run(Harvester(cfg).run(count=10))
```

## Configuration

Copiez `config.example.toml` et `.env.example` :

```bash
cp config.example.toml config.toml
cp .env.example .env
zt-harvester run -n 3 --config config.toml
```

Chaque champ est documenté dans `config.example.toml`.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## Structure du projet

```
src/ztharvester/
  mail.py      Client de boîte jetable compatible mail.tm
  zerotwo.py   Pilote d'inscription / lien magique / intégration + collecteur
  cdp.py       Adaptateurs CDP (websocket local, pont en processus, cloud)
  router9.py   Client de l'API de gestion des fournisseurs 9Router
  shim.py      Pont de protocole compatible OpenAI <-> ZeroTwo
  engine.py    Orchestration concurrente + registre JSONL reprenable
  config.py    Modèles de configuration
  cli.py       Interface en ligne de commande
tests/
docs/          6 translated READMEs
assets/        logo
```

## Prérequis

- Python 3.10+
- Un Chromium accessible via CDP (port de débogage local ou navigateur cloud)
- Une instance [9Router](https://9router.com) en cours (par défaut `http://localhost:20128`)

## Remarques

- L'edge de ZeroTwo exige le cookie `cf_clearance` et un jeton CSRF en plus du JWT ; exportez-les une fois vers le shim.
- Le shim sert tous les comptes depuis un seul processus — le JWT est lu par requête depuis `Authorization`.
- À utiliser de façon responsable et uniquement sur des comptes que vous êtes autorisé à créer.
- ZeroTwo et mail.tm appliquent des limites par IP et par adresse. Gardez `--concurrency` bas (1–2), espacez les exécutions et laissez les réessais gérer les `429` transitoires.

## License

MIT — voir [LICENSE](LICENSE).

<div align="center"><sub>Conçu pour l'écosystème 9Router · non affilié à ZeroTwo ni 9Router</sub></div>
