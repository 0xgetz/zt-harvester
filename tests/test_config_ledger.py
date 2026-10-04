import json
from ztharvester.config import HarvesterConfig
from ztharvester.engine import Ledger


def test_config_env(monkeypatch):
    monkeypatch.setenv("NINEROUTER_URL", "http://x:1")
    monkeypatch.setenv("ZT_CONCURRENCY", "3")
    cfg = HarvesterConfig.from_env()
    assert cfg.router.base_url == "http://x:1"
    assert cfg.concurrency == 3


def test_ledger_append_and_summary(tmp_path):
    led = Ledger(tmp_path / "s.jsonl")
    led.append({"email": "a@b.c", "access_token": "t", "router": {"ok": True}})
    led.append({"email": "d@e.f", "access_token": "", "router": {"ok": False}})
    assert led.summary() == {"total": 2, "harvested": 1, "routed": 1}
    reloaded = Ledger(tmp_path / "s.jsonl")
    assert len(reloaded.records) == 2
