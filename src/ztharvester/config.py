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
    # When true, the browser's own traffic exits through a pool proxy. Local
    # Chromium cannot change proxy per tab, so this applies to cloud browsers
    # that accept a proxy configuration at creation time.
    route_through_pool: bool = False


@dataclass
class ProxyConfig:
    """Exit-IP pool used to spread per-IP rate limits."""

    enabled: bool = False
    scheme: str = "http"
    inline: list[str] = field(default_factory=list)
    file: str | None = None
    sticky: bool = True



@dataclass
class HarvesterConfig:
    mail: MailConfig = field(default_factory=MailConfig)
    zerotwo: ZeroTwoConfig = field(default_factory=ZeroTwoConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
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
        proxies = os.getenv("ZT_PROXIES", "")
        if proxies.strip():
            cfg.proxy.enabled = True
            cfg.proxy.inline = [
                p for p in proxies.replace(",", "\n").splitlines() if p.strip()
            ]
        cfg.proxy.file = os.getenv("ZT_PROXY_FILE") or cfg.proxy.file
        cfg.proxy.scheme = os.getenv("ZT_PROXY_SCHEME", cfg.proxy.scheme)
        cfg.proxy.sticky = os.getenv("ZT_PROXY_STICKY", "1") not in ("0", "false", "False")
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
            proxy=ProxyConfig(**data.get("proxy", {})),
            concurrency=data.get("concurrency", 1),
            output_dir=data.get("output_dir", "harvest"),
        )

    def build_proxy_pool(self) -> "ProxyPool":
        from .proxy import ProxyPool

        if not self.proxy.enabled:
            return ProxyPool()
        pool = ProxyPool(scheme=self.proxy.scheme)
        for line in self.proxy.inline:
            pool.add(line)
        if self.proxy.file:
            from pathlib import Path

            path = Path(self.proxy.file)
            if path.exists():
                for line in path.read_text().splitlines():
                    pool.add(line)
        return pool
