from ztharvester.proxy import Proxy, ProxyPool


def test_parse_userpass():
    p = Proxy.parse("31.59.20.176:6754:ipqievzh:wd6foi2vce6h")
    assert p.host == "31.59.20.176" and p.port == 6754
    assert p.username == "ipqievzh" and p.password == "wd6foi2vce6h"
    assert p.url == "http://ipqievzh:wd6foi2vce6h@31.59.20.176:6754"


def test_parse_hostport():
    p = Proxy.parse("127.0.0.1:8080")
    assert p.url == "http://127.0.0.1:8080"


def test_pool_round_robin_and_sticky():
    pool = ProxyPool.from_lines([
        "1.1.1.1:1:u:p",
        "2.2.2.2:2:u:p",
    ])
    assert len(pool) == 2
    a = pool.next(key="acct-1", sticky=True)
    assert pool.next(key="acct-1", sticky=True) is a
    b = pool.next(key="acct-2", sticky=True)
    assert a.url != b.url


def test_pool_from_env(monkeypatch):
    monkeypatch.setenv("ZT_PROXIES", "1.1.1.1:1:u:p\n2.2.2.2:2:u:p")
    pool = ProxyPool.from_env()
    assert len(pool) == 2
