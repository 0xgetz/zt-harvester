"""Bulk orchestration engine.

Creates N accounts concurrently, harvests each session, persists every result
to disk in a resumable JSONL ledger, and registers the sessions into 9Router.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .cdp import BridgeCDP, HttpCDP, LocalCDP
from .config import HarvesterConfig
from .mail import MailProvider
from .router9 import NineRouterClient
from .zerotwo import HarvestedSession, ZeroTwoCreator


class Ledger:
    """Append-only, crash-safe record of every harvested session."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[dict[str, Any]] = []
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    try:
                        self._records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    def append(self, record: dict[str, Any]) -> None:
        self._records.append(record)
        with self.path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def summary(self) -> dict[str, Any]:
        total = len(self._records)
        ok = sum(1 for r in self._records if r.get("access_token"))
        routed = sum(1 for r in self._records if r.get("router", {}).get("ok"))
        return {"total": total, "harvested": ok, "routed": routed}


class Harvester:
    def __init__(self, config: HarvesterConfig, log: Any = print) -> None:
        self.config = config
        self.log = log
        self.ledger = Ledger(Path(config.output_dir) / "sessions.jsonl")

    async def _make_cdp(self, proxy: str | None = None) -> Any:
        b = self.config.browser
        if b.mode == "bridge":
            raise RuntimeError("bridge mode is only available inside the browser harness")
        if b.mode == "cloud" and b.cdp_url:
            cdp = HttpCDP(b.cdp_url, b.api_key)
            return await cdp.connect()
        if b.cdp_ws:
            return await LocalCDP(b.cdp_ws).connect()
        if b.cdp_url:
            cdp = HttpCDP(b.cdp_url, b.api_key)
            return await cdp.connect()
        # No endpoint configured: launch a local Chromium, optionally proxied.
        from .browser import ChromeLauncher

        launcher = ChromeLauncher(
            chrome=b.launch_path,
            proxy=proxy,
            headless=b.headless,
        )
        ws = await asyncio.get_event_loop().run_in_executor(None, launcher.start)
        cdp = await LocalCDP(ws).connect()
        cdp._launcher = launcher  # type: ignore[attr-defined]
        return cdp

    async def create_one(
        self,
        index: int,
        *,
        mail: MailProvider,
        router: NineRouterClient | None,
        node_id: str | None,
        proxy: str | None = None,
    ) -> dict[str, Any]:
        cfg = self.config
        account: dict[str, Any] = {"index": index, "started_at": time.time()}
        mailbox = None
        session: HarvestedSession | None = None
        for attempt in range(1, cfg.zerotwo.max_retries + 2):
            mailbox = await mail.create_mailbox(cfg.mail.domain, cfg.mail.prefix)
            self.log(f"[{index}] attempt {attempt}: mailbox {mailbox.address}"
                     + (f" via {proxy}" if proxy else ""))
            cdp = await self._make_cdp(proxy)
            try:
                creator = ZeroTwoCreator(
                    cdp, name=cfg.zerotwo.name, interest=cfg.zerotwo.interest,
                    log=self.log,
                )
                session = await creator.harvest(
                    waittime=cfg.zerotwo.wait_seconds, mail_provider=mail,
                    mailbox=mailbox,
                )
                if session.ok:
                    self.log(f"[{index}] harvested {session.email} "
                             f"({len(session.models)} models)")
                    break
                self.log(f"[{index}] failed: {session.error}")
            finally:
                launcher = getattr(cdp, "_launcher", None)
                if launcher:
                    try:
                        launcher.stop()
                    except Exception:  # noqa: BLE001
                        pass
                close = getattr(cdp, "close", None)
                if close:
                    try:
                        await close()
                    except Exception:  # noqa: BLE001
                        pass
        if session is None:
            session = HarvestedSession(
                email=getattr(mailbox, "address", ""),
                password=getattr(mailbox, "password", ""),
                error="no attempt completed",
            )
        record = asdict(session)
        record["index"] = index
        record["mailbox"] = mailbox.as_dict() if mailbox else {}
        record["finished_at"] = time.time()
        record.update(account)
        if router is not None and session.ok and cfg.router.enabled:
            result = await router.connect_session(
                email=session.email,
                access_token=session.access_token,
                node_id=node_id,
                node_prefix=cfg.router.node_prefix,
                extra={"base_url": cfg.router.shim_base_url},
            )
            record["router"] = asdict(result)
            self.log(f"[{index}] 9router: {'ok' if result.ok else result.message}")
        self.ledger.append(record)
        return record

    async def run(self, count: int) -> dict[str, Any]:
        cfg = self.config
        pool = cfg.build_proxy_pool()
        if pool:
            self.log(f"proxy pool: {len(pool)} exit IPs")

        router: NineRouterClient | None = None
        node_id: str | None = None
        if cfg.router.enabled:
            router = NineRouterClient(
                cfg.router.base_url, api_key=cfg.router.api_key, log=self.log
            )
            if await router.health():
                node_id = await router.ensure_node(
                    name=cfg.router.node_name,
                    base_url=cfg.router.shim_base_url,
                    prefix=cfg.router.node_prefix,
                )
                self.log(f"9router online, node={node_id}")
            else:
                self.log("9router unreachable - sessions will be saved but not routed "
                         f"({cfg.router.base_url})")
                router = None

        sem = asyncio.Semaphore(max(1, cfg.concurrency))

        async def worker(i: int) -> dict[str, Any]:
            async with sem:
                proxy = pool.next(key=str(i), sticky=cfg.proxy.sticky) if pool else None
                proxy_url = proxy.url if proxy else None
                mail = MailProvider(cfg.mail.base_url, proxy=proxy_url)
                async with mail:
                    return await self.create_one(
                        i, mail=mail, router=router, node_id=node_id,
                        proxy=proxy_url,
                    )

        results = await asyncio.gather(*(worker(i) for i in range(1, count + 1)))
        summary = self.ledger.summary()
        summary["proxies"] = len(pool)
        self.log(f"done: {summary}")
        return summary
