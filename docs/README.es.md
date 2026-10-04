<div align="center">

<img src="../assets/logo.png" width="140" alt="zt-harvester logo">

# zt-harvester

**Creador masivo de cuentas ZeroTwo · recolector de sesión / token / cookies · conexión automática a 9Router**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/9Router-compatible-818cf8?style=for-the-badge)](https://9router.com)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI-Compatible-412991?style=for-the-badge&logo=openai&logoColor=white)](#)
[![ZeroTwo](https://img.shields.io/badge/ZeroTwo-app.zerotwo.ai-ec4899?style=for-the-badge)](https://app.zerotwo.ai)
[![Status](https://img.shields.io/badge/status-stable-14b8a6?style=for-the-badge)](#)

*Crea cuentas de ZeroTwo en masa, recolecta su sesión JWT, cookies y token CSRF, y conecta cada cuenta a [9Router](https://9router.com) como proveedor compatible con OpenAI — de principio a fin.*

[English](../README.md) · [Bahasa Indonesia](README.id.md) · [Español](README.es.md) · [日本語](README.ja.md) · [中文](README.zh.md) · [Français](README.fr.md)

</div>

---

## Qué hace

1. **Crea** N cuentas ZeroTwo automáticamente, cada una con un correo desechable de un proveedor compatible con mail.tm.
2. **Verifica** el enlace mágico y completa el asistente de incorporación (nombre, intereses).
3. **Recolecta** el JWT de Supabase `access_token`, `refresh_token`, todas las cookies (incl. `cf_clearance` / `__csrf`), el token CSRF, el perfil y el catálogo completo de modelos.
4. **Conecta** cada sesión recolectada a **9Router** como proveedor compatible con OpenAI, de modo que todas las cuentas sean accesibles por un único endpoint `/v1`.
5. **Tiende un puente** entre protocolos con un shim compatible con OpenAI, porque la API de ZeroTwo no tiene forma OpenAI.

## Arquitectura

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

## Instalación

```bash
git clone https://github.com/0xgetz/zt-harvester.git
cd zt-harvester
pip install -e ".[shim]"
```

## Inicio rápido

**1. Inicia el shim compatible con OpenAI** (traduce ZeroTwo → formato OpenAI):

```bash
export ZT_ZT_COOKIES="cf_clearance=...; __csrf=..."
export ZT_ZT_CSRF="<token from sessionStorage: zerotwo.csrf.token.v1>"
zt-harvester shim --port 8787
```

**2. Lanza un navegador con depuración remota** (o usa un endpoint CDP en la nube):

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
```

**3. Crea y conecta cuentas:**

```bash
zt-harvester run \
  --count 5 \
  --cdp-ws "ws://127.0.0.1:9222/devtools/browser/<id>" \
  --router-url "http://localhost:20128" \
  --shim-base-url "http://localhost:8787/v1"
```

Cada cuenta queda en `harvest/sessions.jsonl` y en el panel de 9Router.

## CLI

| Comando|Propósito | |
| --- | --- |
| `zt-harvester run -n 5` | Crear + recolectar + conectar N cuentas |
| `zt-harvester shim -p 8787` | Ejecutar el shim ZeroTwo compatible con OpenAI |
| `zt-harvester export -f csv` | Exportar el registro |

## API de Python

```python
import asyncio
from ztharvester import Harvester, HarvesterConfig

cfg = HarvesterConfig.from_env()
cfg.browser.cdp_ws = "ws://127.0.0.1:9222/devtools/browser/<id>"
cfg.router.shim_base_url = "http://localhost:8787/v1"
asyncio.run(Harvester(cfg).run(count=10))
```

## Configuración

Copia `config.example.toml` y `.env.example`:

```bash
cp config.example.toml config.toml
cp .env.example .env
zt-harvester run -n 3 --config config.toml
```

Cada campo está documentado dentro de `config.example.toml`.

## Pruebas

```bash
pip install -e ".[dev]"
pytest -q
```

## Estructura del proyecto

```
src/ztharvester/
  mail.py      Cliente de correo desechable compatible con mail.tm
  zerotwo.py   Controlador de registro / enlace mágico / incorporación + recolector
  cdp.py       Adaptadores CDP (websocket local, puente en proceso, nube)
  router9.py   Cliente de la API de gestión de proveedores de 9Router
  shim.py      Puente de protocolo compatible con OpenAI <-> ZeroTwo
  engine.py    Orquestación concurrente + registro JSONL reanudable
  config.py    Modelos de configuración
  cli.py       Interfaz de línea de comandos
tests/
docs/          6 translated READMEs
assets/        logo
```

## Requisitos

- Python 3.10+
- Un Chromium accesible por CDP (puerto de depuración local o navegador en la nube)
- Una instancia de [9Router](https://9router.com) en ejecución (por defecto `http://localhost:20128`)

## Notas

- El edge de ZeroTwo requiere la cookie `cf_clearance` y un token CSRF además del JWT; expórtalos al shim una vez.
- El shim sirve todas las cuentas desde un solo proceso — el JWT se lee por petición desde `Authorization`.
- Úsalo con responsabilidad y solo en cuentas que estés autorizado a crear.

## License

MIT — consulta [LICENSE](LICENSE).

<div align="center"><sub>Hecho para el ecosistema 9Router · sin afiliación con ZeroTwo ni 9Router</sub></div>
