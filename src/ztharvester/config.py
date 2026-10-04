"""Configuration models for zt-harvester."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MailConfig:
    base_url: str = "https://api.mail.tm"
    domain: str | None = None
    prefix: str = "zt"


@dataclass
class ZeroTwoConfig:
    name: str = "Burz"
    interest: str = "Just exploring"
    wait_seconds: float = 240.0
    max_retries: int = 2


@dataclass
class RouterConfig:
    base_url: str = "http://localhost:20128"
    api_key: str = "sk_9router"
    shim_base_url: str = "http://localhost:8787/v1"
    node_name: str = "ZeroTwo (shim)"
    node_prefix: str = "zerotwo"
    enabled: bool = True


@dataclass
class BrowserConfig:
    """How to reach the Chromium instance used for sign-ups."""

    mode: str = "cdp"  # cdp | bridge | cloud
    cdp_ws: str | None = None
    cdp_url: str | None = None
    api_key: str | None = None
    headless: bool = True
    launch_path: str | None = None


@dataclass
class HarvesterConfig:
    mail: MailConfig = field(default_factory=MailConfig)
    zerotwo: ZeroTwoConfig = field(default_factory=ZeroTwoConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    concurrency: int = 1
    output_dir: str = "harvest"

    @classmethod
    def from_env(cls, **overrides: Any) -> "HarvesterConfig":
        cfg = cls()
        cfg.mail.base_url = os.getenv("ZT_MAIL_BASE_URL", cfg.mail.base_url)
        cfg.mail.domain = os.getenv("ZT_MAIL_DOMAIN") or None
        cfg.zerotwo.name = os.getenv("ZT_NAME", cfg.zerotwo.name)
        cfg.zerotwo.interest = os.getenv("ZT_INTEREST", cfg.zerotwo.interest)
        cfg.router.base_url = os.getenv("NINEROUTER_URL", cfg.router.base_url)
        cfg.router.api_key = os.getenv("NINEROUTER_API_KEY", cfg.router.api_key)
        cfg.router.shim_base_url = os.getenv("ZT_SHIM_BASE_URL", cfg.router.shim_base_url)
        cfg.browser.cdp_ws = os.getenv("ZT_CDP_WS") or None
        cfg.browser.cdp_url = os.getenv("ZT_CDP_URL") or None
        cfg.browser.api_key = os.getenv("BROWSER_USE_API_KEY") or None
        cfg.browser.mode = os.getenv("ZT_BROWSER_MODE", cfg.browser.mode)
        cfg.concurrency = int(os.getenv("ZT_CONCURRENCY", str(cfg.concurrency)))
        for key, value in overrides.items():
            if isinstance(value, dict) and hasattr(cfg, key):
                section = getattr(cfg, key)
                for k, v in value.items():
                    setattr(section, k, v)
            elif hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg

    @classmethod
    def from_toml(cls, path: str | Path) -> "HarvesterConfig":
        import tomllib

        data = tomllib.loads(Path(path).read_text())
        return cls(
            mail=MailConfig(**data.get("mail", {})),
            zerotwo=ZeroTwoConfig(**data.get("zerotwo", {})),
            router=RouterConfig(**data.get("router", {})),
            browser=BrowserConfig(**data.get("browser", {})),
            concurrency=data.get("concurrency", 1),
            output_dir=data.get("output_dir", "harvest"),
        )
