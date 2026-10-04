import httpx
import pytest
from ztharvester.router9 import NineRouterClient


@pytest.mark.asyncio
async def test_connect_session_requires_token():
    client = NineRouterClient("http://localhost:1")
    res = await client.connect_session(email="a@b.c", access_token="", node_id=None)
    assert res.ok is False
