"""Updater: version check and download against a mocked GitHub."""
import io
import os
import tarfile

import httpx
import pytest

os.environ["JARVIS_NO_SUPERVISOR"] = "1"

from backend import updater  # noqa: E402

SHA = "a" * 40


def tarball(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def github(files):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.github.com":
            return httpx.Response(200, json={"sha": SHA, "commit": {"message": "Add phone line\n\nmore", "committer": {"date": "2026-10-12"}}})
        if req.url.host == "codeload.github.com" and req.url.path.endswith(SHA):
            return httpx.Response(200, content=tarball(files))
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "VERSION_FILE", tmp_path / "version")
    monkeypatch.setattr(updater, "WORK", tmp_path / "update")
    monkeypatch.setattr(updater, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(updater, "ROOT", tmp_path / "root")
    updater.STATE.update(checked_at=None, latest=None, error=None, running=False)
    started = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda argv, **kw: started.append(argv))
    yield tmp_path, started
    updater._transport = None


@pytest.mark.anyio
async def test_check_reports_update(env):
    tmp, _ = env
    updater._transport = github({})
    (tmp / "version").write_text("b" * 40)
    r = await updater.check()
    assert r["available"] and r["latest"]["message"] == "Add phone line"
    (tmp / "version").write_text(SHA)
    assert not updater.info()["available"]


@pytest.mark.anyio
async def test_apply_downloads_and_runs_update_script(env):
    tmp, started = env
    updater._transport = github({"jarvis-abc/scripts/update.sh": "echo hi", "jarvis-abc/README.md": "x"})
    r = await updater.apply()
    assert r["running"]
    src = tmp / "update" / "jarvis-abc"
    assert (src / ".release").read_text() == SHA
    assert started[0][1:] == [str(src / "scripts" / "update.sh"), str(src), str(tmp / "root"), SHA]


@pytest.mark.anyio
async def test_apply_rejects_non_jarvis_archive(env):
    updater._transport = github({"other/readme.txt": "nope"})
    with pytest.raises(RuntimeError):
        await updater.apply()


@pytest.mark.anyio
async def test_check_handles_offline(env):
    updater._transport = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    r = await updater.check()
    assert not r["available"] and "Couldn't check" in r["error"]
