"""Obsidian vault tools: search, read, create, append, guarded replace, no escapes."""
import pytest

from agent import tools  # noqa: F401  (registers tools)
from agent.registry import ToolError, registry


def run(name, args, perms):
    return registry.validate(name, args).handler(args, perms)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "Vault"
    (v / ".obsidian").mkdir(parents=True)
    (v / "Projects").mkdir()
    (v / "Projects" / "Helixa.md").write_text("# Helixa\nLaunch plan for Helixa Ads in November.\n")
    (v / "Daily.md").write_text("todo: call Anna")
    (tmp_path / "secret.md").write_text("outside")
    return v, {"obsidian_vault": str(v)}


def test_search_and_read(vault):
    v, perms = vault
    r = run("obsidian_search", {"query": "helixa ads"}, perms)
    assert r["results"][0]["note"] == "Projects/Helixa.md" and "Launch plan" in r["results"][0]["snippet"]
    assert "November" in run("obsidian_read", {"note": "Projects/Helixa"}, perms)["content"]


def test_create_append_never_overwrite(vault):
    v, perms = vault
    run("obsidian_create", {"note": "Ideas/New", "content": "one"}, perms)
    with pytest.raises(ToolError):
        run("obsidian_create", {"note": "Ideas/New", "content": "two"}, perms)
    run("obsidian_append", {"note": "Ideas/New", "content": "two"}, perms)
    assert (v / "Ideas" / "New.md").read_text() == "one\ntwo\n"
    assert registry.get("obsidian_replace").sensitive   # replacing always asks first


def test_cannot_escape_vault(vault):
    v, perms = vault
    for bad in ["../secret", "/etc/passwd", ".obsidian/app.json"]:
        with pytest.raises(ToolError):
            run("obsidian_read", {"note": bad}, perms)
    with pytest.raises(ToolError):
        run("obsidian_read", {"note": "Daily"}, {"obsidian_vault": ""})
