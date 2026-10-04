"""9Router connector.

Registers harvested ZeroTwo sessions into a running 9Router instance
(https://9router.com) so they appear as OpenAI-compatible provider
connections and are available through the single 9Router endpoint.

9Router exposes a local REST API (default ``http://localhost:20128``):

* ``POST /api/provider-nodes``          create a custom OpenAI-compatible node
* ``POST /api/providers``               create a provider connection
* ``GET  /api/providers``               list connections
* ``GET  /v1/models``                   OpenAI-compatible model list

ZeroTwo does not speak the OpenAI protocol itself, so the connector ships with
an optional built-in shim (:mod:`ztharvester.shim`) and registers ZeroTwo via
that shim by default. If you already run an external ZeroTwo->OpenAI proxy,
point ``--shim-base-url`` at it instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


DEFAULT_ROUTER_URL = "http://localhost:20128"
SHIM_PREFIX = "zerotwo"


@dataclass
class RouterResult:
    ok: bool
    node_id: str | None = None
    connection_id: str | None = None
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class NineRouterClient:
    """Small client for the 9Router provider-management API."""

    def __init__(
        self,
        base_url: str = DEFAULT_ROUTER_URL,
        *,
        api_key: str = "sk_9router",
        timeout: float = 30.0,
        log: Any = print,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.log = log

    @property
    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"}

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"{self.base_url}/api/settings", headers=self._headers)
                return r.status_code < 500
        except httpx.HTTPError:
            return False

    async def list_providers(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.get(f"{self.base_url}/api/providers", headers=self._headers)
            if r.status_code >= 400:
                return []
            data = r.json()
        if isinstance(data, dict):
            return data.get("providers") or data.get("data") or []
        return data or []

    async def ensure_node(
        self,
        *,
        name: str = "ZeroTwo (shim)",
        base_url: str,
        prefix: str = SHIM_PREFIX,
        api_type: str = "openai",
    ) -> str | None:
        """Create (or find) an OpenAI-compatible provider node for ZeroTwo."""
        existing = await self._find_node(prefix)
        if existing:
            return existing
        payload = {
            "type": "openai-compatible",
            "name": name,
            "baseUrl": base_url,
            "prefix": prefix,
            "apiType": api_type,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/provider-nodes",
                headers=self._headers,
                json=payload,
            )
        if r.status_code >= 400:
            self.log(f"[router] node create failed: {r.status_code} {r.text[:180]}")
            return None
        body = r.json()
        return body.get("id") or body.get("nodeId")

    async def _find_node(self, prefix: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r = await c.get(f"{self.base_url}/api/provider-nodes", headers=self._headers)
            if r.status_code >= 400:
                return None
            data = r.json()
            nodes = data.get("nodes", data) if isinstance(data, dict) else data
            for n in nodes or []:
                if n.get("prefix") == prefix:
                    return n.get("id")
        except httpx.HTTPError:
            return None
        return None

    async def add_connection(
        self,
        *,
        provider: str,
        api_key: str,
        name: str,
        provider_specific: dict[str, Any] | None = None,
    ) -> RouterResult:
        payload: dict[str, Any] = {
            "provider": provider,
            "apiKey": api_key,
            "name": name,
        }
        if provider_specific:
            payload["providerSpecificData"] = provider_specific
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/providers", headers=self._headers, json=payload
            )
        if r.status_code >= 400:
            return RouterResult(ok=False, message=f"{r.status_code}: {r.text[:200]}")
        body = r.json()
        conn = body.get("provider") or body.get("data") or body
        return RouterResult(
            ok=True,
            connection_id=conn.get("id") if isinstance(conn, dict) else None,
            message="connected",
            raw=body,
        )

    async def connect_session(
        self,
        *,
        email: str,
        access_token: str,
        node_id: str | None,
        node_prefix: str = SHIM_PREFIX,
        extra: dict[str, Any] | None = None,
    ) -> RouterResult:
        """Register one harvested ZeroTwo session as a 9Router connection.

        The harvested JWT is stored as the connection's credential; the shim
        reads it from the ``Authorization`` header. Because ZeroTwo bulk
        accounts share a provider, every account becomes its own connection
        under the shared ZeroTwo node - exactly like 9Router's multi-key
        pooling.
        """
        if not access_token:
            return RouterResult(ok=False, message="missing access token")
        provider = f"openai-compatible-{node_prefix}"
        psd: dict[str, Any] = {
            "baseUrl": (extra or {}).get("base_url", ""),
            "apiType": "openai",
            "nodeId": node_id,
            "email": email,
            "accountType": "zerotwo",
        }
        return await self.add_connection(
            provider=provider,
            api_key=access_token,
            name=f"ZeroTwo · {email}",
            provider_specific=psd,
        )
