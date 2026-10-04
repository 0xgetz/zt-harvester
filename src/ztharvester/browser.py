"""Launch a local Chromium with a fresh debug port and optional proxy."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHROME_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def find_chrome(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if Path(explicit).exists() or shutil.which(explicit) else None
    for name in CHROME_CANDIDATES:
        path = shutil.which(name) if not name.startswith("/") and "\\" not in name else name
        if path and Path(path).exists():
            return path
    return None


def free_port(preferred: int = 9222) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ChromeLauncher:
    """Start Chromium with a debug port, fresh profile and optional proxy."""

    def __init__(
        self,
        *,
        chrome: str | None = None,
        port: int = 9222,
        proxy: str | None = None,
        headless: bool = True,
        profile_dir: str | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        self.chrome = chrome
        self.port = port
        self.proxy = proxy
        self.headless = headless
        self.profile_dir = profile_dir or tempfile.mkdtemp(prefix="zt-chrome-")
        self.extra_args = extra_args or []
        self.proc: subprocess.Popen | None = None

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/devtools/browser"

    def command(self) -> list[str]:
        binary = find_chrome(self.chrome)
        if not binary:
            raise RuntimeError("no Chrome/Chromium found; pass --chrome or install one")
        args = [
            binary,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
        ]
        if self.headless:
            args.append("--headless=new")
        if self.proxy:
            args.append(f"--proxy-server={self.proxy}")
        args.extend(self.extra_args)
        args.append("about:blank")
        return args

    def start(self) -> str:
        self.proc = subprocess.Popen(
            self.command(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self._debug_ready():
                return self.ws_url
            if self.proc.poll() is not None:
                raise RuntimeError("Chrome exited immediately; check the binary/flags")
            time.sleep(0.3)
        raise RuntimeError("Chrome debug port did not open in time")

    def _debug_ready(self) -> bool:
        import httpx

        try:
            r = httpx.get(f"http://127.0.0.1:{self.port}/json/version", timeout=2)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


async def launch_async(**kwargs) -> ChromeLauncher:
    launcher = ChromeLauncher(**kwargs)
    await asyncio.get_event_loop().run_in_executor(None, launcher.start)
    return launcher
