"""Phone access: local requests are open; remote ones need the passcode cookie; brute force is locked out."""
import os

from fastapi.testclient import TestClient

os.environ["JARVIS_NO_SUPERVISOR"] = "1"
from backend import db, main, remote  # noqa: E402

REMOTE = {"host": "macbook.tail1234.ts.net", "x-forwarded-for": "100.101.102.103", "tailscale-user-login": "me@example.com"}


def test_remote_needs_passcode():
    db.init()
    remote._fails.clear()
    c = TestClient(main.app, base_url="https://macbook.tail1234.ts.net")
    local = TestClient(main.app)
    assert local.get("/api/settings").status_code == 200                      # on the Mac: unchanged
    assert c.get("/api/settings", headers=REMOTE).json()["detail"] == "remote_login_required"
    assert c.post("/api/remote/passcode", json={"passcode": "123456"}, headers=REMOTE).status_code == 401   # can't set it remotely
    assert local.post("/api/remote/passcode", json={"passcode": "correct horse"}).status_code == 200
    assert c.post("/api/remote/login", json={"passcode": "nope"}, headers=REMOTE).status_code == 401
    r = c.post("/api/remote/login", json={"passcode": "correct horse"}, headers=REMOTE)
    assert r.status_code == 200 and remote.COOKIE in r.cookies
    assert c.get("/api/settings", headers=REMOTE).status_code == 200
    assert c.get("/", headers=REMOTE).status_code == 200                      # the app shell itself is public


def test_lockout_after_five_wrong_tries():
    db.init()
    remote._fails.clear()
    TestClient(main.app).post("/api/remote/passcode", json={"passcode": "correct horse"})
    c = TestClient(main.app, base_url="https://macbook.tail1234.ts.net")
    for _ in range(5):
        assert c.post("/api/remote/login", json={"passcode": "bad"}, headers=REMOTE).status_code == 401
    assert c.post("/api/remote/login", json={"passcode": "correct horse"}, headers=REMOTE).status_code == 429


def test_forged_cookie_rejected():
    assert not remote.valid_session("v1.9999999999.deadbeef")
    assert remote.valid_session(remote.make_session())
