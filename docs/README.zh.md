<div align="center">

<img src="../assets/logo.png" width="140" alt="zt-harvester logo">

# zt-harvester

**ZeroTwo 批量账号创建器 · 会话 / 令牌 / Cookie 采集 · 9Router 自动连接**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/9Router-compatible-818cf8?style=for-the-badge)](https://9router.com)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI-Compatible-412991?style=for-the-badge&logo=openai&logoColor=white)](#)
[![ZeroTwo](https://img.shields.io/badge/ZeroTwo-app.zerotwo.ai-ec4899?style=for-the-badge)](https://app.zerotwo.ai)
[![Status](https://img.shields.io/badge/status-stable-14b8a6?style=for-the-badge)](#)

*批量创建 ZeroTwo 账号，采集其 JWT 会话、Cookie 与 CSRF 令牌，并将每个账号作为兼容 OpenAI 的提供方接入 [9Router](https://9router.com) —— 端到端。*

[English](../README.md) · [Bahasa Indonesia](README.id.md) · [Español](README.es.md) · [日本語](README.ja.md) · [中文](README.zh.md) · [Français](README.fr.md)

</div>

---

## 功能

1. **创建** N 个 ZeroTwo 账号，每个使用兼容 mail.tm 提供方的临时邮箱。
2. **验证** 魔法链接并完成入门向导（姓名、兴趣）。
3. **采集** Supabase JWT `access_token`、`refresh_token`、完整 Cookie（含 `cf_clearance` / `__csrf`）、CSRF 令牌、账号资料与完整模型目录。
4. **接入** 将每个采集的会话注册为 **9Router** 的兼容 OpenAI 提供方，使所有账号可通过单一 `/v1` 端点访问。
5. **桥接** 协议差异：由于 ZeroTwo 自有 API 并非 OpenAI 格式，内置兼容 OpenAI 的 shim。

## 架构

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

## 安装

```bash
git clone https://github.com/0xgetz/zt-harvester.git
cd zt-harvester
pip install -e ".[shim]"
```

## 快速开始

**1. 启动兼容 OpenAI 的 shim**（将 ZeroTwo 转换为 OpenAI 格式）:

```bash
export ZT_ZT_COOKIES="cf_clearance=...; __csrf=..."
export ZT_ZT_CSRF="<token from sessionStorage: zerotwo.csrf.token.v1>"
zt-harvester shim --port 8787
```

**2. 以远程调试启动浏览器**（或使用云端 CDP 端点）:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
```

**3. 创建并连接账号:**

```bash
zt-harvester run \
  --count 5 \
  --cdp-ws "ws://127.0.0.1:9222/devtools/browser/<id>" \
  --router-url "http://localhost:20128" \
  --shim-base-url "http://localhost:8787/v1"
```

每个账号都会写入 `harvest/sessions.jsonl` 并显示在 9Router 面板中。

## 命令行

| 命令|用途 | |
| --- | --- |
| `zt-harvester run -n 5` | 创建 + 采集 + 连接 N 个账号 |
| `zt-harvester shim -p 8787` | 运行兼容 OpenAI 的 ZeroTwo shim |
| `zt-harvester export -f csv` | 导出采集账本 |

## Python API

```python
import asyncio
from ztharvester import Harvester, HarvesterConfig

cfg = HarvesterConfig.from_env()
cfg.browser.cdp_ws = "ws://127.0.0.1:9222/devtools/browser/<id>"
cfg.router.shim_base_url = "http://localhost:8787/v1"
asyncio.run(Harvester(cfg).run(count=10))
```

## 配置

复制 `config.example.toml` 与 `.env.example`:

```bash
cp config.example.toml config.toml
cp .env.example .env
zt-harvester run -n 3 --config config.toml
```

所有字段均在 `config.example.toml` 中有说明。

## 测试

```bash
pip install -e ".[dev]"
pytest -q
```

## 项目结构

```
src/ztharvester/
  mail.py      兼容 mail.tm 的临时邮箱客户端
  zerotwo.py   注册 / 魔法链接 / 入门驱动 + 采集器
  cdp.py       CDP 适配器（本地 websocket、进程内桥接、云端）
  router9.py   9Router 提供方管理 API 客户端
  shim.py      兼容 OpenAI <-> ZeroTwo 协议桥接
  engine.py    并发编排 + 可续传 JSONL 账本
  config.py    配置模型
  cli.py       命令行接口
tests/
docs/          6 translated READMEs
assets/        logo
```

## 要求

- Python 3.10+
- 可通过 CDP 访问的 Chromium（本地调试端口或云端浏览器）
- 运行中的 [9Router](https://9router.com)（默认 `http://localhost:20128`）

## 说明

- ZeroTwo 的边缘除 JWT 外还需要 `cf_clearance` Cookie 与 CSRF 令牌；请一次性导出到 shim。
- shim 以单进程服务所有采集账号 —— JWT 按请求从 `Authorization` 读取。
- 请负责任地使用，仅用于你有权创建的账号。

## License

MIT —— 见 [LICENSE](LICENSE)。

<div align="center"><sub>为 9Router 生态而建 · 与 ZeroTwo 或 9Router 无关联</sub></div>
