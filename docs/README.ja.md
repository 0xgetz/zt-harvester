<div align="center">

<img src="../assets/logo.png" width="140" alt="zt-harvester logo">

# zt-harvester

**ZeroTwo 一括アカウント作成 · セッション / トークン / Cookie ハーベスタ · 9Router 自動接続**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/9Router-compatible-818cf8?style=for-the-badge)](https://9router.com)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI-Compatible-412991?style=for-the-badge&logo=openai&logoColor=white)](#)
[![ZeroTwo](https://img.shields.io/badge/ZeroTwo-app.zerotwo.ai-ec4899?style=for-the-badge)](https://app.zerotwo.ai)
[![Status](https://img.shields.io/badge/status-stable-14b8a6?style=for-the-badge)](#)

*ZeroTwo アカウントを一括作成し、JWT セッション・Cookie・CSRF トークンを収集して、各アカウントを OpenAI 互換プロバイダとして [9Router](https://9router.com) に接続します — エンドツーエンド。*

[English](../README.md) · [Bahasa Indonesia](README.id.md) · [Español](README.es.md) · [日本語](README.ja.md) · [中文](README.zh.md) · [Français](README.fr.md)

</div>

---

## できること

1. **作成** — mail.tm 互換プロバイダの使い捨てメールで N 個の ZeroTwo アカウントを自動作成。
2. **認証** — マジックリンクを検証し、オンボーディング（名前・興味）を自動で完了。
3. **収集** — Supabase JWT `access_token`、`refresh_token`、全 Cookie（`cf_clearance` / `__csrf` を含む）、CSRF トークン、プロフィール、全モデルカタログを取得。
4. **接続** — 各セッションを OpenAI 互換プロバイダとして **9Router** に登録し、1 つの `/v1` エンドポイントから全アカウントへアクセス可能に。
5. **橋渡し** — ZeroTwo 独自 API は OpenAI 形式でないため、OpenAI 互換 shim を内蔵。

## アーキテクチャ

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

## インストール

```bash
git clone https://github.com/0xgetz/zt-harvester.git
cd zt-harvester
pip install -e ".[shim]"
```

## クイックスタート

**1. OpenAI 互換 shim を起動**（ZeroTwo → OpenAI 形式に変換）:

```bash
export ZT_ZT_COOKIES="cf_clearance=...; __csrf=..."
export ZT_ZT_CSRF="<token from sessionStorage: zerotwo.csrf.token.v1>"
zt-harvester shim --port 8787
```

**2. リモートデバッグ付きでブラウザを起動**（またはクラウド CDP を使用）:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=./chrome-data
```

**3. アカウントを作成して接続:**

```bash
zt-harvester run \
  --count 5 \
  --cdp-ws "ws://127.0.0.1:9222/devtools/browser/<id>" \
  --router-url "http://localhost:20128" \
  --shim-base-url "http://localhost:8787/v1"
```

各アカウントは `harvest/sessions.jsonl` と 9Router ダッシュボードに保存されます。

## CLI

| コマンド|用途 | |
| --- | --- |
| `zt-harvester run -n 5` | N 個のアカウントを作成・収集・接続 |
| `zt-harvester shim -p 8787` | OpenAI 互換 ZeroTwo shim を実行 |
| `zt-harvester proxies --check` | プロキシプールを一覧・テスト |
| `zt-harvester export -f csv` | 収集レジャーをエクスポート |

## プロキシプール

アカウントごとに出口 IP をローテーションして IP 単位のレート制限を分散します。一般的な `host:port:user:pass` 形式に対応。

```bash
zt-harvester run -n 10 --proxy-file proxies.txt
zt-harvester proxies --proxy-file proxies.txt --check
```

## Python API

```python
import asyncio
from ztharvester import Harvester, HarvesterConfig

cfg = HarvesterConfig.from_env()
cfg.browser.cdp_ws = "ws://127.0.0.1:9222/devtools/browser/<id>"
cfg.router.shim_base_url = "http://localhost:8787/v1"
asyncio.run(Harvester(cfg).run(count=10))
```

## 設定

`config.example.toml` と `.env.example` をコピー:

```bash
cp config.example.toml config.toml
cp .env.example .env
zt-harvester run -n 3 --config config.toml
```

各項目は `config.example.toml` 内に記載されています。

## テスト

```bash
pip install -e ".[dev]"
pytest -q
```

## プロジェクト構成

```
src/ztharvester/
  mail.py      mail.tm 互換の使い捨てメールクライアント
  zerotwo.py   登録 / マジックリンク / オンボーディングのドライバ＋ハーベスタ
  cdp.py       CDP アダプタ（ローカル websocket、プロセス内ブリッジ、クラウド）
  router9.py   9Router プロバイダ管理 API クライアント
  shim.py      OpenAI 互換 <-> ZeroTwo プロトコルブリッジ
  engine.py    並行オーケストレーション＋再開可能な JSONL レジャー
  config.py    設定モデル
  cli.py       コマンドラインインターフェース
tests/
docs/          6 translated READMEs
assets/        logo
```

## 必要条件

- Python 3.10+
- CDP 経由でアクセス可能な Chromium（ローカルデバッグポートまたはクラウドブラウザ）
- 稼働中の [9Router](https://9router.com)（既定 `http://localhost:20128`）

## 注意

- ZeroTwo の edge は JWT に加えて `cf_clearance` Cookie と CSRF トークンが必要です。一度 shim にエクスポートしてください。
- shim は単一プロセスで全アカウントを処理し、JWT はリクエストごとに `Authorization` から読み取ります。
- 責任を持って、作成権限のあるアカウントにのみ使用してください。
- ZeroTwo と mail.tm は IP ごと・アドレスごとのレート制限を適用します。`--concurrency` は低め（1–2）にし、実行間隔を空け、一時的な `429` はリトライに任せてください。

## License

MIT — [LICENSE](LICENSE) を参照。

<div align="center"><sub>9Router エコシステム向け · ZeroTwo / 9Router とは無関係</sub></div>
