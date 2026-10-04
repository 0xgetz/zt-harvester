"""CDP adapters.

Three adapters are provided:

* ``LocalCDP``  - drives a Chromium launched with ``--remote-debugging-port``
                  over a raw websocket (uses ``websockets`` + the JSON CDP
                  protocol directly, no heavyweight dependency).
* ``BridgeCDP`` - wraps an existing in-process CDP session object that already
                  exposes ``Page`` / ``Runtime`` / ``Input`` domain methods
                  (used by the Browser Use harness).
* ``HttpCDP``   - talks to a Browser Use cloud browser bootstrap endpoint.

All adapters implement the same tiny surface used by
:class:`~ztharvester.zerotwo.ZeroTwoCreator`.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx


async def _poll(predicate, timeout: float = 20.0, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return value
        await asyncio.sleep(interval)
    return None


class LocalCDP:
    """Minimal CDP client over a websocket to a local Chromium."""

    def __init__(self, ws_url: str, page_url: str | None = None) -> None:
        self.ws_url = ws_url
        self.page_url = page_url
        self._ws = None
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._session_id: str | None = None
        self._target_id: str | None = None
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> "LocalCDP":
        import websockets

        self._ws = await websockets.connect(self.ws_url, max_size=64 * 1024 * 1024)
        self._reader_task = asyncio.create_task(self._reader())
        targets = await self._send("Target.getTargets", {})
        page = None
        for t in targets["targetInfos"]:
            if t["type"] == "page" and not t["url"].startswith("chrome://"):
                if self.page_url is None or self.page_url in t["url"]:
                    page = t
                    break
        if page is None:
            page = next(
                (t for t in targets["targetInfos"]
                 if t["type"] == "page" and not t["url"].startswith("chrome://")),
                None,
            )
        if page is None:
            created = await self._send("Target.createTarget", {"url": "about:blank"})
            self._target_id = created["targetId"]
        else:
            self._target_id = page["targetId"]
        attached = await self._send(
            "Target.attachToTarget", {"targetId": self._target_id, "flatten": True}
        )
        self._session_id = attached["sessionId"]
        await self._send("Page.enable", {}, session=True)
        await self._send("Runtime.enable", {}, session=True)
        await self._send("Network.enable", {}, session=True)
        return self

    async def _reader(self) -> None:
        assert self._ws is not None
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mid = msg.get("id")
            if mid is not None and mid in self._pending:
                fut = self._pending.pop(mid)
                if not fut.done():
                    if "error" in msg:
                        fut.set_exception(RuntimeError(str(msg["error"])))
                    else:
                        fut.set_result(msg.get("result", {}))

    async def _send(self, method: str, params: dict[str, Any], session: bool = False) -> Any:
        assert self._ws is not None
        self._id += 1
        mid = self._id
        payload: dict[str, Any] = {"id": mid, "method": method, "params": params}
        if session and self._session_id:
            payload["sessionId"] = self._session_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send(json.dumps(payload))
        return await fut

    async def navigate(self, url: str, wait_ms: int = 15000) -> None:
        await self._send("Page.navigate", {"url": url}, session=True)
        await self._wait_ready(wait_ms)

    async def _wait_ready(self, wait_ms: int) -> None:
        deadline = time.monotonic() + wait_ms / 1000
        while time.monotonic() < deadline:
            try:
                state = await self.evaluate("document.readyState")
                if state == "complete":
                    return
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.5)

    async def evaluate(self, expression: str, await_promise: bool = False) -> Any:
        res = await self._send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
                "userGesture": True,
            },
            session=True,
        )
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"].get("text", "evaluate error"))
        return res.get("result", {}).get("value")

    async def click_selector(self, selector: str) -> bool:
        return bool(
            await self.evaluate(
                "(()=>{const e=document.querySelector(%s);if(e){e.click();return true;}"
                "return false;})()" % json.dumps(selector)
            )
        )

    async def click_text(self, text: str) -> bool:
        return bool(
            await self.evaluate(
                "(()=>{const b=[...document.querySelectorAll('button,a')]"
                ".find(x=>(x.innerText||'').trim()===%s);if(b){b.click();return true;}"
                "return false;})()" % json.dumps(text)
            )
        )

    async def type_text(self, selector: str, text: str) -> None:
        await self.evaluate(
            "(()=>{const e=document.querySelector(%s);if(!e)return;"
            "const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;"
            "s.call(e,%s);e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));e.focus();})()"
            % (json.dumps(selector), json.dumps(text))
        )

    async def screenshot(self) -> bytes | None:
        res = await self._send("Page.captureScreenshot", {"format": "png"}, session=True)
        import base64

        return base64.b64decode(res["data"]) if res.get("data") else None

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._ws is not None:
            await self._ws.close()


class BridgeCDP:
    """Adapter around an existing in-process CDP session (Browser Use harness).

    ``session`` must expose ``Page``, ``Runtime``, ``Input`` and ``Network``
    attributes with async methods; it is the object available inside a
    ``browser_execute`` snippet.
    """

    def __init__(self, session: Any, target_id: str | None = None) -> None:
        self.session = session
        self.target_id = target_id

    async def _use_target(self) -> None:
        if self.target_id:
            await self.session.use(self.target_id)

    async def navigate(self, url: str, wait_ms: int = 15000) -> None:
        await self._use_target()
        await self.session.Page.enable()
        try:
            await self.session.Page.navigate({"url": url})
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(min(wait_ms, 12000) / 1000)

    async def evaluate(self, expression: str, await_promise: bool = False) -> Any:
        await self._use_target()
        res = await self.session.Runtime.evaluate(
            {"expression": expression, "returnByValue": True,
             "awaitPromise": await_promise, "userGesture": True}
        )
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"].get("text", "evaluate error"))
        return res.get("result", {}).get("value")

    async def click_selector(self, selector: str) -> bool:
        return bool(await self.evaluate(
            "(()=>{const e=document.querySelector(%s);if(e){e.click();return true;}"
            "return false;})()" % json.dumps(selector)))

    async def click_text(self, text: str) -> bool:
        return bool(await self.evaluate(
            "(()=>{const b=[...document.querySelectorAll('button,a')]"
            ".find(x=>(x.innerText||'').trim()===%s);if(b){b.click();return true;}"
            "return false;})()" % json.dumps(text)))

    async def type_text(self, selector: str, text: str) -> None:
        await self.evaluate(
            "(()=>{const e=document.querySelector(%s);if(!e)return;"
            "const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;"
            "s.call(e,%s);e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));e.focus();})()"
            % (json.dumps(selector), json.dumps(text)))

    async def screenshot(self) -> bytes | None:
        res = await self.session.Page.captureScreenshot({"format": "png"})
        import base64

        return base64.b64decode(res["data"]) if res.get("data") else None


class HttpCDP(LocalCDP):
    """Browser Use cloud browser: resolve the websocket URL then use LocalCDP."""

    def __init__(self, cdp_url: str, api_key: str | None = None) -> None:
        self.cdp_url = cdp_url.rstrip("/")
        self.api_key = api_key
        super().__init__(ws_url="")

    async def connect(self) -> "HttpCDP":
        headers = {}
        if self.api_key:
            headers["X-Browser-Use-API-Key"] = self.api_key
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{self.cdp_url}/json/version", headers=headers)
            r.raise_for_status()
            ws = r.json()["webSocketDebuggerUrl"]
        self.ws_url = ws
        return await super().connect()  # type: ignore[return-value]
