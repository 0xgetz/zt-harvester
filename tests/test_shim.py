from ztharvester.shim import split_model, ZeroTwoShim


def test_split_model_prefixed():
    assert split_model("anthropic/claude-sonnet-4.5") == ("anthropic", "claude-sonnet-4.5")


def test_split_model_heuristic():
    assert split_model("grok-4.1-fast") == ("xai", "grok-4.1-fast")


def test_extract_text_variants():
    assert ZeroTwoShim._extract_text({"content": "hi"}) == "hi"
    assert ZeroTwoShim._extract_text({"v": {"content": "yo"}}) == "yo"
    assert ZeroTwoShim._extract_text({"choices": [{"message": {"content": "z"}}]}) == "z"


def test_body_shape():
    body = ZeroTwoShim()._body({
        "model": "openai/gpt-5.2",
        "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hello"},
        ],
    }, stream=True)
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-5.2"
    assert body["contextData"]["message"] == "hello"
    assert body["stream"] is True
    assert body["messages"][-1]["role"] == "user"
