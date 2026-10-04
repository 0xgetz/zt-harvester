"""OpenAI-compatible shim for ZeroTwo.

9Router talks to upstreams using the OpenAI protocol. ZeroTwo's own API is
*not* OpenAI-compatible: it authenticates with a Supabase JWT and expects a
provider/model pair. This shim bridges the two so a harvested ZeroTwo session
can be plugged straight into 9Router as an OpenAI-compatible provider.

Run it with::

    zt-harvester shim --port 8787

Then register the harvested sessions against ``http://<host>:8787/v1``.

Endpoints
---------
GET  /v1/models
POST /v1/chat/completions   (streaming + non-streaming)
GET  /healthz

The shim reads the ZeroTwo JWT from the request's ``Authorization: Bearer``
header, so a single shim process serves every harvested account. ZeroTwo's edge
also expects the Cloudflare clearance cookie and a CSRF token, so those are
configured once via ``ZT_ZT_COOKIES`` / ``ZT_ZT_CSRF`` (see ``.env.example``).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator

import httpx

ZEROTWO_CHAT = "https://api.zerotwo.ai/api/ai/chat/stream"

# A pragmatic provider map; ZeroTwo model ids are prefixed like "openai/gpt-5".
PROVIDER_BY_PREFIX = {
    "gpt": "openai", "o1": "openai", "o3": "openai", "o4": "openai",
    "claude": "anthropic", "gemini": "google", "gemma": "google",
    "grok": "xai", "deepseek": "deepseek", "qwen": "qwen", "glm": "zai",
    "kimi": "kimi", "command": "cohere", "mistral": "mistral",
    "sonar": "perplexity", "llama": "meta", "minimax": "minimax",
    "mimo": "mimo", "mercury": "inception",
}


def split_model(model: str) -> tuple[str, str]:
    if "/" in model:
        provider, _, name = model.partition("/")
        return provider, name
    base = model.split("-")[0].lower()
    return PROVIDER_BY_PREFIX.get(base, "openai"), model


def _chunk(model: str, delta: dict[str, Any], finish: str | None = None) -> str:
    payload = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload)}\n\n"


class ZeroTwoShim:
    def __init__(self, *, timeout: float = 300.0, cookies: str = "", csrf: str = "") -> None:
        self.timeout = timeout
        self.cookies = cookies
        self.csrf = csrf

    def _headers(self, token: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Origin": "https://app.zerotwo.ai",
            "Referer": "https://app.zerotwo.ai/",
        }
        if self.csrf:
            headers["x-csrf-token"] = self.csrf
        if self.cookies:
            headers["Cookie"] = self.cookies
        return headers

    def _body(self, req: dict[str, Any], *, stream: bool) -> dict[str, Any]:
        provider, model = split_model(req.get("model", "openai/gpt-5"))
        messages = req.get("messages", [])
        # ZeroTwo carries the system prompt in the leading messages; keep the
        # shape close to the web client: provider + model + messages + context.
        clean = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            clean.append({
                "role": m.get("role", "user"),
                "content": m.get("content", ""),
                "id": m.get("id") or str(uuid.uuid4()),
            })
        last_user = next(
            (m["content"] for m in reversed(clean) if m["role"] == "user"), ""
        )
        effort = req.get("reasoning_effort", "medium")
        return {
            "provider": provider,
            "model": model,
            "messages": clean,
            "tool_choice": "auto",
            "reasoning_effort": effort,
            "attachments": [],
            "contextData": {
                "message": last_user,
                "has_files": False,
                "file_count": 0,
                "toolChoice": "auto",
                "reasoning_effort": effort,
                "is_hybrid_reasoning": True,
                "modelProvider": provider,
                "actualProviderName": provider,
                "mode": {"type": "thread", "retrieval": None},
                "unifiedTurnVersion": 1,
                "research_true": False,
                "browserExecution": "executor",
                "approvalPolicy": "never",
                "sandboxMode": "danger-full-access",
                "permissionMode": "bypassPermissions",
            },
            "stream": True,
        }

    async def chat(self, req: dict[str, Any], token: str) -> dict[str, Any]:
        """Non-streaming completion: drain the SSE stream and return one JSON."""
        provider, model = split_model(req.get("model", "openai/gpt-5"))
        text_parts: list[str] = []
        async for piece in self._raw_stream(req, token):
            if piece["type"] == "text":
                text_parts.append(piece["value"])
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"{provider}/{model}",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "".join(text_parts)},
                "finish_reason": "stop",
            }],
            "usage": {},
        }

    async def stream(self, req: dict[str, Any], token: str) -> AsyncIterator[str]:
        provider, model = split_model(req.get("model", "openai/gpt-5"))
        out_model = f"{provider}/{model}"
        yield _chunk(out_model, {"role": "assistant"})
        try:
            async for piece in self._raw_stream(req, token):
                if piece["type"] == "text" and piece["value"]:
                    yield _chunk(out_model, {"content": piece["value"]})
        except httpx.HTTPError as exc:
            yield _chunk(out_model, {"content": f"[shim error: {exc}]"})
        yield _chunk(out_model, {}, finish="stop")
        yield "data: [DONE]\n\n"

    async def _raw_stream(self, req: dict[str, Any], token: str) -> AsyncIterator[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            async with c.stream(
                "POST", ZEROTWO_CHAT, headers=self._headers(token),
                json=self._body(req, stream=True),
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        return
                    try:
                        ev = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    text = self._extract_text(ev)
                    if text:
                        yield {"type": "text", "value": text}

    @staticmethod
    def _extract_text(payload: Any) -> str:
        """Pull assistant text out of ZeroTwo's stream entity payloads."""
        if not isinstance(payload, dict):
            return ""
        # Common ZeroTwo shapes: {entity:'text', delta:'...'} /
        # {entity:'message', v:{content:'...'}} / {v:{content:'...'}}
        v = payload.get("v")
        if isinstance(v, dict):
            for key in ("content", "text", "delta"):
                val = v.get(key)
                if isinstance(val, str):
                    return val
                if isinstance(val, dict) and isinstance(val.get("content"), str):
                    return val["content"]
        for key in ("content", "text", "delta", "output_text"):
            val = payload.get(key)
            if isinstance(val, str):
                return val
            if isinstance(val, dict) and isinstance(val.get("content"), str):
                return val["content"]
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            c = choices[0]
            if isinstance(c, dict):
                if isinstance(c.get("delta", {}).get("content"), str):
                    return c["delta"]["content"]
                if isinstance(c.get("message", {}).get("content"), str):
                    return c["message"]["content"]
                if isinstance(c.get("text"), str):
                    return c["text"]
        return ""


def build_app(shim: ZeroTwoShim | None = None) -> Any:
    """Return an ASGI app exposing the OpenAI-compatible surface."""
    import os

    shim = shim or ZeroTwoShim(
        cookies=os.getenv("ZT_ZT_COOKIES", ""),
        csrf=os.getenv("ZT_ZT_CSRF", ""),
    )

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return
        path = scope["path"]
        method = scope["method"]
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        token = headers.get("authorization", "").removeprefix("Bearer ").strip()

        if path == "/healthz":
            await _json(send, 200, {"status": "ok"})
            return
        if path == "/v1/models" and method == "GET":
            await _json(send, 200, {"object": "list", "data": _model_list()})
            return
        if path == "/v1/chat/completions" and method == "POST":
            body = await _read_json(receive)
            if not token:
                await _json(send, 401, {"error": {"message": "missing bearer token"}})
                return
            if body.get("stream"):
                await _stream(send, shim.stream(body, token))
            else:
                try:
                    result = await shim.chat(body, token)
                    await _json(send, 200, result)
                except httpx.HTTPError as exc:
                    await _json(send, 502, {"error": {"message": str(exc)}})
            return
        await _json(send, 404, {"error": {"message": "not found"}})

    return app


def _model_list() -> list[dict[str, Any]]:
    return [
        {"id": "openai/gpt-5.6-luna", "object": "model", "owned_by": "zerotwo"},
        {"id": "openai/gpt-5.2", "object": "model", "owned_by": "zerotwo"},
        {"id": "anthropic/claude-sonnet-4.5", "object": "model", "owned_by": "zerotwo"},
        {"id": "google/gemini-3-pro", "object": "model", "owned_by": "zerotwo"},
        {"id": "xai/grok-4.1-fast", "object": "model", "owned_by": "zerotwo"},
    ]


async def _read_json(receive: Any) -> dict[str, Any]:
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body"):
            break
    return json.loads(body or b"{}")


async def _json(send: Any, status: int, payload: Any) -> None:
    data = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": data})


async def _stream(send: Any, gen: AsyncIterator[str]) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": [
        (b"content-type", b"text/event-stream"),
        (b"cache-control", b"no-cache"),
        (b"connection", b"keep-alive"),
    ]})
    async for chunk in gen:
        await send({"type": "http.response.body", "body": chunk.encode(),
                    "more_body": True})
    await send({"type": "http.response.body", "body": b"", "more_body": False})
