import json

from backend import browser_policy, hermes

PERMS = {"approved_domains": ["example.com", "github.com"], "disabled_tools": [],
         "browser": {"ask_outside_approved_domains": True,
                     "always_ask": ["browser_fill_form", "browser_evaluate", "browser_run_code_unsafe"],
                     "risky_words": ["buy", "pay", "order", "submit", "send", "delete", "confirm"]}}


def d(tool, args=None, url="https://example.com/x"):
    return browser_policy.assess(tool, args or {}, PERMS, url)[0]


def test_browser_policy():
    assert d("browser_snapshot", url="https://anything.org") == "allow"
    assert d("browser_navigate", {"url": "https://github.com/a"}) == "allow"
    assert d("browser_navigate", {"url": "https://shop.evil.org"}) == "ask"
    assert d("browser_navigate", {"url": "file:///etc/passwd"}) == "deny"
    assert d("browser_navigate", {"url": "javascript:alert(1)"}) == "deny"
    assert d("browser_click", {"element": "Next page link"}) == "allow"
    assert d("browser_click", {"element": "Buy now"}) == "ask"
    assert d("browser_click", {"element": "Ordering guide"}) == "allow"   # whole words only
    assert d("browser_type", {"element": "Search box", "text": "x"}) == "allow"
    assert d("browser_type", {"element": "Password field", "text": "x"}) == "ask"
    assert d("browser_type", {"element": "Search", "text": "x", "submit": True}, url="https://other.org") == "ask"
    assert d("browser_press_key", {"key": "Enter"}) == "allow"
    assert d("browser_press_key", {"key": "Enter"}, url="https://other.org") == "ask"
    assert d("browser_fill_form", {"fields": []}) == "ask"
    assert d("browser_something_new") == "ask"


def test_translate_hermes_events():
    names = {}
    tr = hermes._translate
    assert tr({"type": "response.output_text.delta", "delta": "Hi"}, names) == [{"type": "text", "delta": "Hi"}]
    start = tr({"type": "response.output_item.added", "item": {"type": "function_call", "name": "mcp_jarvis_open_app",
                                                               "call_id": "c1", "arguments": "{\"name\": \"Notes\"}"}}, names)
    assert start[0]["name"] == "open_app" and start[0]["input"] == {"name": "Notes"}
    done = tr({"type": "response.output_item.done", "item": {"type": "function_call_output", "call_id": "c1",
                                                             "output": [{"type": "input_text", "text": "{\"opened\": \"Notes\"}"}]}}, names)
    assert done[0]["status"] == "ok" and done[0]["name"] == "open_app"
    err = tr({"type": "response.output_item.done", "item": {"type": "function_call_output", "call_id": "c1",
                                                            "output": "Error: The user denied this action."}}, names)
    assert err[0]["status"] == "error"
    assert tr({"type": "response.completed", "response": {}}, names) == [{"type": "done"}]
    f = tr({"type": "response.failed", "response": {"error": {"message": "No provider configured"}}}, names)
    assert f[0]["type"] == "error" and "No provider" in f[0]["message"]


def test_ensure_config_preserves_user_settings(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("# my notes\nmodel:\n  default: nous/hermes-4  # keep this\nmcp_servers:\n  github:\n    command: npx\n")
    r = hermes.ensure_config(tmp_path)
    assert set(r["changed"]) == {"mcp_servers.jarvis", "platform_toolsets.api_server"}
    text = cfg.read_text()
    assert "# my notes" in text and "# keep this" in text and "github" in text
    assert (tmp_path / "config.yaml.before-jarvis").exists()
    assert hermes.ensure_config(tmp_path)["changed"] == []            # idempotent
    assert hermes.model_configured(tmp_path) is True
    from ruamel.yaml import YAML
    data = YAML(typ="safe").load(text)
    assert data["platform_toolsets"]["api_server"] == hermes.API_SERVER_TOOLSETS
    assert "terminal" not in data["platform_toolsets"]["api_server"]
    assert data["mcp_servers"]["jarvis"]["args"] == ["-m", "jarvis_mcp.server"]


def test_model_configured_missing(tmp_path):
    assert hermes.model_configured(tmp_path) is False
    (tmp_path / "config.yaml").write_text(json.dumps({"model": {"provider": "auto"}}))
    assert hermes.model_configured(tmp_path) is False


def test_ensure_env_keeps_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=abc\nAPI_SERVER_KEY=old\nAPI_SERVER_KEY=dup\n# note\n")
    changed = hermes.ensure_env(tmp_path, key="k" * 40, port=8642)
    text = env.read_text()
    assert "OPENROUTER_API_KEY=abc" in text and "# note" in text
    assert text.count("API_SERVER_KEY=") == 1 and "API_SERVER_KEY=" + "k" * 40 in text
    assert "API_SERVER_ENABLED=true" in text and "API_SERVER_HOST=127.0.0.1" in text
    assert "API_SERVER_KEY" in changed
    assert hermes.ensure_env(tmp_path, key="k" * 40, port=8642) == []
    assert oct(env.stat().st_mode)[-3:] == "600"
