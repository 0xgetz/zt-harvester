from ztharvester.zerotwo import ZeroTwoCreator


class _Msg:
    def __init__(self, text="", html=""):
        self.text = text
        self.html = html


def test_extract_link_prefers_sendgrid():
    html = (
        '<img src="https://zerotwo.ai/assets/zerotwo-icon-light-mode-small.png">'
        '<a href="https://u56196570.ct.sendgrid.net/ls/click?upn=abc">Confirm</a>'
        '<img src="https://via.placeholder.com/60?text=ZT">'
    )
    msg = _Msg(text="Click https://u56196570.ct.sendgrid.net/ls/click?upn=abc", html=html)
    assert ZeroTwoCreator.extract_link(msg) == "https://u56196570.ct.sendgrid.net/ls/click?upn=abc"


def test_extract_link_skips_assets():
    msg = _Msg(html='<img src="https://zerotwo.ai/assets/logo.png">')
    assert ZeroTwoCreator.extract_link(msg) is None


def test_extract_link_fallback_confirm():
    msg = _Msg(text="Go to https://app.zerotwo.ai/auth/confirm?token=1")
    assert ZeroTwoCreator.extract_link(msg) == "https://app.zerotwo.ai/auth/confirm?token=1"
