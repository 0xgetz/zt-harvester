"""zt-harvester command line interface."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .config import HarvesterConfig
from .engine import Harvester

try:
    import typer
    from rich.console import Console
    from rich.table import Table
except ImportError:  # pragma: no cover
    typer = None
    Console = None
    Table = None


def _console():
    return Console() if Console else None


def _banner() -> None:
    c = _console()
    text = (
        "\n[bold cyan]zt-harvester[/bold cyan] - bulk ZeroTwo account creator & "
        "9Router harvester\n" if c else "zt-harvester\n"
    )
    c.print(text) if c else print(text)


def _log(message: str) -> None:
    c = _console()
    if c:
        c.print(f"[dim]{message}[/dim]")
    else:
        print(message)


if typer is not None:
    app = typer.Typer(add_completion=False, help="Bulk ZeroTwo account creator + 9Router harvester")

    @app.command()
    def run(
        count: int = typer.Option(1, "--count", "-n", help="Number of accounts to create"),
        config: Path | None = typer.Option(None, "--config", "-c", help="TOML config file"),
        cdp_ws: str | None = typer.Option(None, "--cdp-ws", help="CDP websocket URL of a browser"),
        cdp_url: str | None = typer.Option(None, "--cdp-url", help="CDP HTTP endpoint (cloud browser)"),
        cdp_api_key: str | None = typer.Option(None, "--cdp-api-key", help="API key for the cloud browser"),
        router_url: str | None = typer.Option(None, "--router-url", help="9Router base URL"),
        shim_url: str | None = typer.Option(None, "--shim-base-url", help="OpenAI-compatible shim base URL"),
        no_router: bool = typer.Option(False, "--no-router", help="Skip 9Router registration"),
        proxy: list[str] = typer.Option(None, "--proxy", help="Proxy host:port:user:pass (repeatable)"),
        proxy_file: str | None = typer.Option(None, "--proxy-file", help="File with one proxy per line"),
        concurrency: int | None = typer.Option(None, "--concurrency", help="Parallel sign-ups"),
        output: str | None = typer.Option(None, "--output", "-o", help="Output directory"),
    ) -> None:
        """Create accounts and register them into 9Router."""
        _banner()
        cfg = (
            HarvesterConfig.from_toml(config)
            if config and config.exists()
            else HarvesterConfig.from_env()
        )
        if proxy:
            cfg.proxy.enabled = True
            cfg.proxy.inline = list(proxy)
        if proxy_file:
            cfg.proxy.enabled = True
            cfg.proxy.file = proxy_file
        if cdp_ws:
            cfg.browser.cdp_ws = cdp_ws
        if cdp_url:
            cfg.browser.cdp_url = cdp_url
        if cdp_api_key:
            cfg.browser.api_key = cdp_api_key
        if router_url:
            cfg.router.base_url = router_url
        if shim_url:
            cfg.router.shim_base_url = shim_url
        if no_router:
            cfg.router.enabled = False
        if concurrency:
            cfg.concurrency = concurrency
        if output:
            cfg.output_dir = output

        harvester = Harvester(cfg, log=_log)
        summary = asyncio.run(harvester.run(count))
        c = _console()
        if c and Table:
            table = Table(title="Harvest summary")
            table.add_column("Metric")
            table.add_column("Value", justify="right")
            for k, v in summary.items():
                table.add_row(k, str(v))
            c.print(table)
        else:
            print(json.dumps(summary, indent=2))

    @app.command()
    def shim(
        host: str = typer.Option("0.0.0.0", "--host"),
        port: int = typer.Option(8787, "--port", "-p"),
    ) -> None:
        """Run the built-in OpenAI-compatible ZeroTwo shim."""
        _banner()
        from .shim import build_app

        try:
            import uvicorn
        except ImportError:
            print("uvicorn is required for the shim: pip install uvicorn", file=sys.stderr)
            raise typer.Exit(1)
        uvicorn.run(build_app(), host=host, port=port)

    @app.command()
    def proxies(
        proxy: list[str] = typer.Option(None, "--proxy", help="Proxy host:port:user:pass (repeatable)"),
        proxy_file: str | None = typer.Option(None, "--proxy-file"),
        check: bool = typer.Option(False, "--check", help="Test each proxy exit IP"),
    ) -> None:
        """List and optionally test the proxy pool."""
        from .proxy import ProxyPool

        pool = ProxyPool.from_env()
        for line in proxy or []:
            pool.add(line)
        if proxy_file:
            from pathlib import Path

            path = Path(proxy_file)
            if path.exists():
                for line in path.read_text().splitlines():
                    pool.add(line)
        c = _console()
        if not pool:
            msg = "no proxies configured (use --proxy or ZT_PROXIES)"
            c.print(f"[yellow]{msg}[/yellow]") if c else print(msg)
            return
        if not check:
            for i, p in enumerate(pool.proxies, 1):
                print(f"{i:>2}  {p.url}")
            return

        import httpx

        async def _test(p) -> tuple[str, bool, str]:
            try:
                async with httpx.AsyncClient(proxy=p.url, timeout=15) as h:
                    r = await h.get("https://api.ipify.org?format=json")
                    return p.url, True, r.json().get("ip", "")
            except Exception as exc:  # noqa: BLE001
                return p.url, False, str(exc)[:60]

        results = asyncio.run(_gather([_test(p) for p in pool.proxies]))

        if c and Table:
            t = Table(title="Proxy pool")
            t.add_column("Proxy")
            t.add_column("OK")
            t.add_column("Exit IP / error")
            for url, ok, info in results:
                t.add_row(url, "yes" if ok else "no", info)
            c.print(t)
        else:
            for url, ok, info in results:
                print(url, ok, info)

    def _gather(coros):
        async def runner():
            import asyncio as _a

            return await _a.gather(*coros)

        return runner()

    @app.command()
    def export(
        output: str = typer.Option("harvest/sessions.jsonl", "--output", "-o"),
        fmt: str = typer.Option("json", "--format", "-f", help="json | csv"),
    ) -> None:
        """Export harvested sessions to a portable file."""
        from .engine import Ledger

        ledger = Ledger(output)
        records = ledger.records
        if fmt == "csv":
            import csv
            import io

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["email", "access_token", "refresh_token", "default_model"])
            for r in records:
                writer.writerow([
                    r.get("email", ""), r.get("access_token", ""),
                    r.get("refresh_token", ""), r.get("default_model", ""),
                ])
            Path(output).with_suffix(".csv").write_text(buf.getvalue())
            print(f"wrote {output.rsplit('.', 1)[0]}.csv")
        else:
            print(json.dumps(records, indent=2))

    def _entry() -> None:
        app()

else:  # pragma: no cover
    def _entry() -> None:
        print("typer is required: pip install typer", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    _entry()
