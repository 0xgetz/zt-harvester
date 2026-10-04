"""Mail provider abstraction (mail.tm and compatible Hydra APIs)."""

from __future__ import annotations

import asyncio
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


def _rand_username(prefix: str = "zt") -> str:
    alphabet = string.ascii_lowercase + string.digits
    return prefix + "".join(secrets.choice(alphabet) for _ in range(8))


def _rand_password() -> str:
    return "Zt" + secrets.token_hex(6) + "aA1!"


@dataclass
class Mailbox:
    address: str
    password: str
    domain: str
    token: str | None = None
    account_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "password": self.password,
            "domain": self.domain,
            "token": self.token,
            "account_id": self.account_id,
        }


@dataclass
class Message:
    id: str
    subject: str
    sender: str
    text: str
    html: str
    seen: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


class MailProvider:
    """Thin client for the mail.tm / mail.gw Hydra REST API.

    The provider is disposable-mail oriented: create a mailbox, then poll for
    an inbound message and extract links / OTP codes from it.
    """

    def __init__(
        self,
        base_url: str = "https://api.mail.tm",
        timeout: float = 30.0,
        proxy: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.proxy = proxy
        self._client: httpx.AsyncClient | None = None

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        return kwargs

    async def __aenter__(self) -> "MailProvider":
        self._client = httpx.AsyncClient(**self._client_kwargs())
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("MailProvider must be used as an async context manager")
        return self._client

    async def domains(self) -> list[str]:
        r = await self.client.get(f"{self.base_url}/domains")
        r.raise_for_status()
        data = r.json()
        members = data.get("hydra:member", data if isinstance(data, list) else [])
        return [m["domain"] for m in members if m.get("isActive", True)]

    async def create_mailbox(self, domain: str | None = None, prefix: str = "zt") -> Mailbox:
        if domain is None:
            domains = await self.domains()
            if not domains:
                raise RuntimeError("mail provider returned no active domains")
            domain = secrets.choice(domains)
        last_error = ""
        for attempt in range(5):
            username = _rand_username(prefix)
            address = f"{username}@{domain}"
            password = _rand_password()
            r = await self.client.post(
                f"{self.base_url}/accounts",
                json={"address": address, "password": password},
            )
            if r.status_code == 429:
                last_error = "429 rate limited"
                await asyncio.sleep(5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                last_error = f"{r.status_code} {r.text[:200]}"
                # Retry with a fresh username for validation-style errors.
                await asyncio.sleep(1)
                continue
            body = r.json()
            mb = Mailbox(
                address=address,
                password=password,
                domain=domain,
                account_id=body.get("id"),
            )
            await self.login(mb)
            return mb
        raise RuntimeError(f"mailbox creation failed: {last_error}")

    async def login(self, mailbox: Mailbox) -> str:
        r = await self.client.post(
            f"{self.base_url}/token",
            json={"address": mailbox.address, "password": mailbox.password},
        )
        r.raise_for_status()
        mailbox.token = r.json().get("token")
        return mailbox.token or ""

    async def messages(self, mailbox: Mailbox) -> list[Message]:
        if not mailbox.token:
            await self.login(mailbox)
        r = await self.client.get(
            f"{self.base_url}/messages",
            headers={"Authorization": f"Bearer {mailbox.token}"},
        )
        r.raise_for_status()
        data = r.json()
        return [
            Message(
                id=m["id"],
                subject=m.get("subject", ""),
                sender=(m.get("from") or {}).get("address", ""),
                text="",
                html="",
                seen=m.get("seen", False),
                raw=m,
            )
            for m in data.get("hydra:member", [])
        ]

    async def message(self, mailbox: Mailbox, message_id: str) -> Message:
        if not mailbox.token:
            await self.login(mailbox)
        r = await self.client.get(
            f"{self.base_url}/messages/{message_id}",
            headers={"Authorization": f"Bearer {mailbox.token}"},
        )
        r.raise_for_status()
        m = r.json()
        return Message(
            id=m["id"],
            subject=m.get("subject", ""),
            sender=(m.get("from") or {}).get("address", ""),
            text=m.get("text", "") or "",
            html="\n".join(m.get("html", []) or []),
            seen=m.get("seen", False),
            raw=m,
        )

    async def wait_for_message(
        self,
        mailbox: Mailbox,
        *,
        timeout: float = 180.0,
        interval: float = 5.0,
        match: str | None = None,
        match_sender: str | None = None,
    ) -> Message | None:
        """Poll the mailbox until a matching message arrives or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msgs = await self.messages(mailbox)
            except httpx.HTTPError:
                msgs = []
            for m in msgs:
                sender_ok = match_sender is None or match_sender.lower() in m.sender.lower()
                subject_ok = match is None or match.lower() in m.subject.lower()
                if sender_ok and subject_ok:
                    return await self.message(mailbox, m.id)
            await asyncio.sleep(interval)
        return None
