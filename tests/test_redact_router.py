"""Privacy guard and model router."""
import os

os.environ["JARVIS_NO_SUPERVISOR"] = "1"
from backend import db, redact, router  # noqa: E402


def test_redacts_common_secrets():
    text = ("my key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456 and password: hunter2!! "
            "card 4111 1111 1111 1111, github ghp_abcdefghijklmnopqrstuvwxyz0123, your verification code is 482913, "
            "twilio 0123456789abcdef0123456789abcdef")
    out, n = redact.redact(text)
    for s in ["sk-ant-api03", "hunter2", "4111 1111", "ghp_", "482913", "0123456789abcdef0123456789abcdef"]:
        assert s not in out
    assert n == 6 and "[REDACTED" in out


def test_leaves_normal_text_and_ids_alone():
    text = "Meet Tuesday at 10:30, invoice 2026-11, call +39 333 123 4567, event 7f3a2c9d1e"
    assert redact.redact(text) == (text, 0)
    obj = {"conversation": "9f86d081884c7d659a2feaa0c55ad015", "ts": 1791848571400}
    assert redact.redact_obj(obj) == (obj, 0)


def test_router_prefix_and_auto():
    db.init()
    db.set_setting("router", {"enabled": True, "auto": True, "routes": {
        "fast": {"model": "claude-haiku-5-5", "provider": "anthropic"},
        "think": {"model": "claude-opus-5-5", "provider": "anthropic"}}})
    assert router.pick("fast: what's 2+2") == ("fast", "what's 2+2")
    assert router.pick("deep: plan my launch")[0] == "think"
    assert router.pick("hi")[0] == "fast"
    assert router.pick("Can you analyze my Q3 numbers and compare them to Q2?")[0] == "think"
    assert router.pick("local: hello")[0] is None          # no local route configured → default model
    db.set_setting("router", {"enabled": False, "routes": {}})
    assert router.pick("fast: hi") == (None, "hi")
