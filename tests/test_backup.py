"""Backups: snapshot, prune, restore (and a safety backup before restoring)."""
import os

os.environ["JARVIS_NO_SUPERVISOR"] = "1"
from backend import backup, db, memory  # noqa: E402


def test_backup_and_restore(tmp_path, monkeypatch):
    db.init()
    monkeypatch.setattr(backup, "DIR", tmp_path / "b")
    monkeypatch.setattr(backup, "ICLOUD", tmp_path / "no-icloud")
    m = memory.create("fact", "Favourite coffee: espresso", source="user")
    made = backup.create("test")
    db.ex("DELETE FROM memories WHERE id=?", (m["id"],))
    assert not db.one("SELECT id FROM memories WHERE id=?", (m["id"],))
    backup.restore(made["file"])
    assert db.one("SELECT content FROM memories WHERE id=?", (m["id"],))["content"] == "Favourite coffee: espresso"
    assert len(backup.listing()) == 2          # the restored one + the safety copy taken before restoring


def test_restore_rejects_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "DIR", tmp_path / "b")
    import pytest
    with pytest.raises(ValueError):
        backup.restore("../../etc/passwd")


def test_icloud_copy_and_prune(tmp_path, monkeypatch):
    db.init()
    monkeypatch.setattr(backup, "DIR", tmp_path / "b")
    monkeypatch.setattr(backup, "ICLOUD", tmp_path / "cloud")
    (tmp_path / "cloud").mkdir()
    monkeypatch.setattr(backup, "KEEP", 2)
    import time
    for _ in range(3):
        r = backup.create("t")
        time.sleep(1.05)
    assert r["icloud"] and len(list((tmp_path / "cloud" / "JARVIS Backups").glob("*.zip"))) == 2
    assert len(backup.listing()) == 2
