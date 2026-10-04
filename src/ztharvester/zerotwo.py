"""ZeroTwo account creator driver.

Drives the ZeroTwo web sign-up / magic-link flow inside a live browser
fashion (a CDP-controlled Chromium) and harvests the resulting session.

The driver is intentionally transport-agnostic: it operates on an object that
exposes the small subset of Chrome DevTools Protocol calls it needs, so it can
be backed by Browser Use cloud browsers, a locally launched Chromium, or any
other CDP endpoint.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class CDP(Protocol):
    async def navigate(self, url: str, wait_ms: int = 15000) -> None: ...
    async def evaluate(self, expression: str, await_promise: bool = False) -> Any: ...
    async def click_text(self, text: str) -> bool: ...
    async def click_selector(self, selector: str) -> bool: ...
    async def type_text(self, selector: str, text: str) -> None: ...
    async def screenshot(self) -> bytes | None: ...


LINK_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


@dataclass
class HarvestedSession:
    email: str
    password: str
    access_token: str = ""
    refresh_token: str = ""
    user_id: str = ""
    user: dict[str, Any] = field(default_factory=dict)
    cookies: list[dict[str, Any]] = field(default_factory=list)
    csrf_token: str = ""
    models: list[dict[str, Any]] = field(default_factory=list)
    default_model: str = ""
    credits: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.access_token) and self.error is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "password": self.password,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "user_id": self.user_id,
            "user": self.user,
            "cookies": self.cookies,
            "csrf_token": self.csrf_token,
            "models": self.models,
            "default_model": self.default_model,
            "credits": self.credits,
            "created_at": self.created_at,
            "error": self.error,
        }


class ZeroTwoCreator:
    """Automates the ZeroTwo sign-up and session harvest."""

    APP_ORIGIN = "https://app.zerotwo.ai"
    API_ORIGIN = "https://api.zerotwo.ai"

    def __init__(
        self,
        cdp: CDP,
        *,
        name: str = "Burz",
        interest: str = "Just exploring",
        log: Any = print,
    ) -> None:
        self.cdp = cdp
        self.name = name
        self.interest = interest
        self.log = log

    async def _sleep(self, ms: int) -> None:
        await asyncio.sleep(ms / 1000)

    async def submit_email(self, email: str) -> bool:
        """Open the signup page, enter the email and trigger the magic link."""
        await self.cdp.navigate(f"{self.APP_ORIGIN}/c", wait_ms=12000)
        await self._sleep(2500)
        # Make sure we are on the email-entry screen.
        ok = await self.cdp.evaluate(
            """(()=>{
              const i=document.querySelector('#email');
              if(!i) return false;
              const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
              setter.call(i, %s);
              i.dispatchEvent(new Event('input',{bubbles:true}));
              i.dispatchEvent(new Event('change',{bubbles:true}));
              i.focus();
              return true;
            })()""" % json.dumps(email),
        )
        if not ok:
            return False
        # Wait for the Cloudflare Turnstile to solve, then press Continue.
        for _ in range(30):
            state = await self.cdp.evaluate(
                "(()=>{const b=[...document.querySelectorAll('button')]"
                ".find(x=>x.innerText.trim()==='Continue');"
                "return b&&!b.disabled;})()"
            )
            if state:
                break
            await self._sleep(2000)
        await self.cdp.evaluate(
            "(()=>{const b=[...document.querySelectorAll('button')]"
            ".find(x=>x.innerText.trim()==='Continue');if(b)b.click();return !!b;})()"
        )
        await self._sleep(5000)
        text = await self.cdp.evaluate("document.body.innerText.slice(0,200)")
        return "check your email" in (text or "").lower()

    async def complete_onboarding(self) -> bool:
        """Walk the post-verification onboarding wizard."""
        # Name step
        await self._sleep(2000)
        typed = await self.cdp.evaluate(
            "(()=>{const i=document.querySelector('input');if(!i)return false;i.focus();return true;})()"
        )
        if typed:
            await self.cdp.evaluate(
                "(()=>{const i=document.querySelector('input');"
                "const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;"
                "setter.call(i,%s);i.dispatchEvent(new Event('input',{bubbles:true}));"
                "i.dispatchEvent(new Event('change',{bubbles:true}));i.focus();return true;})()"
                % json.dumps(self.name)
            )
            await self._sleep(500)
            # Click the arrow submit button.
            await self.cdp.evaluate(
                "(()=>{const b=document.querySelector('button[type=submit]');"
                "if(b){b.click();return true;}return false;})()"
            )
            await self._sleep(3500)
        # Interests step
        await self.cdp.evaluate(
            "(()=>{const b=[...document.querySelectorAll('button')]"
            ".find(x=>x.innerText.trim()===%s);if(b)b.click();return !!b;})()"
            % json.dumps(self.interest)
        )
        await self._sleep(800)
        await self.cdp.evaluate(
            "(()=>{const b=[...document.querySelectorAll('button')]"
            ".find(x=>x.innerText.trim()==='Continue');if(b)b.click();return !!b;})()"
        )
        await self._sleep(5000)
        url = await self.cdp.evaluate("location.href")
        return "/c" in (url or "") and "onboarding" not in (url or "")

    async def harvest(self, *, waittime: float = 180.0, mail_provider: Any = None,
                      mailbox: Any = None) -> HarvestedSession:
        """Full flow: create mailbox -> link -> onboarding -> harvest."""
        session = HarvestedSession(email=getattr(mailbox, "address", ""),
                                   password=getattr(mailbox, "password", ""))
        try:
            sent = await self.submit_email(session.email)
            if not sent:
                session.error = "magic link request did not reach confirmation screen"
                return session
            msg = await mail_provider.wait_for_message(
                mailbox, timeout=waittime, interval=5, match_sender="zerotwo"
            )
            if msg is None:
                session.error = "confirmation email not received"
                return session
            link = self.extract_link(msg)
            if not link:
                session.error = "no confirmation link found in email"
                return session
            await self.cdp.navigate(link, wait_ms=15000)
            await self._sleep(4000)
            await self.complete_onboarding()
            await self.collect(session)
        except Exception as exc:  # noqa: BLE001 - surfaced on the session object
            session.error = f"{type(exc).__name__}: {exc}"
        return session

    @staticmethod
    def extract_link(msg: Any) -> str | None:
        """Pull the ZeroTwo confirmation link out of a mail message."""
        candidates = LINK_RE.findall(getattr(msg, "text", "") or "")
        candidates += LINK_RE.findall(getattr(msg, "html", "") or "")
        for url in candidates:
            if "sendgrid" in url or "zerotwo" in url:
                return url
        return candidates[0] if candidates else None

    async def collect(self, session: HarvestedSession) -> None:
        """Read token, refresh token, user and cookies from the live page."""
        data = await self.cdp.evaluate(
            """(()=>{
              const raw=localStorage.getItem('app-session');
              const auth=localStorage.getItem('auth-storage');
              const sess=raw?JSON.parse(raw):{};
              const a=auth?JSON.parse(auth):{};
              return {
                access_token:sess.access_token||'',
                refresh_token:sess.refresh_token||'',
                user:sess.user||{},
                profile:(a.state&&a.state.profile)||{},
                csrf:sessionStorage.getItem('zerotwo.csrf.token.v1')||''
              };
            })()"""
        )
        if not isinstance(data, dict):
            raise RuntimeError("could not read local storage session")
        session.access_token = data.get("access_token", "")
        session.refresh_token = data.get("refresh_token", "")
        session.user = data.get("user", {})
        session.user_id = session.user.get("id", "")
        session.csrf_token = data.get("csrf", "")
        profile = data.get("profile", {}) or {}
        session.default_model = (profile.get("metadata") or {}).get("model", "")
        session.cookies = await self._cookies()
        session.models = await self._models(session.access_token)
        session.credits = await self._credits(session.access_token)

    async def _cookies(self) -> list[dict[str, Any]]:
        try:
            raw = await self.cdp.evaluate(
                "(()=>{const out=document.cookie.split(';').map(c=>{"
                "const i=c.indexOf('=');return {name:c.slice(0,i).trim(),"
                "value:c.slice(i+1).trim(),domain:location.hostname};});"
                "return out;})()"
            )
            return raw or []
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def cookie_header(cookies: list[dict[str, Any]]) -> str:
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))

    async def _models(self, token: str) -> list[dict[str, Any]]:
        if not token:
            return []
        data = await self.cdp.evaluate(
            """(async()=>{
              try{
                const r=await fetch('https://api.zerotwo.ai/api/ai/capabilities/models',
                  {headers:{Authorization:'Bearer '+%s},credentials:'include'});
                const j=await r.json();
                return Object.entries(j.models||{}).map(([id,v])=>({
                  id, name:v.display_name||id, provider:v.normalized_provider||v.provider||'',
                  context:v.context_window||v.context_window_tokens||null,
                  images:!!v.supports_images, thinking:!!v.thinking_enabled
                }));
              }catch(e){return [];}
            })()""" % json.dumps(token),
            await_promise=True,
        )
        return data or []

    async def _credits(self, token: str) -> dict[str, Any]:
        if not token:
            return {}
        try:
            return await self.cdp.evaluate(
                """(async()=>{
                  try{
                    const r=await fetch('https://api.zerotwo.ai/api/credits/wallet',
                      {headers:{Authorization:'Bearer '+%s},credentials:'include'});
                    return await r.json();
                  }catch(e){return {};}
                })()""" % json.dumps(token),
                await_promise=True,
            ) or {}
        except Exception:  # noqa: BLE001
            return {}
