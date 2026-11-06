"""Regressionstest: Login muss sofort gelten, auch wenn das Aufräumen nach der
Antwort langsam ist (so wie auf der DS918+ mit Festplatten)."""
import os
import socket
import threading
import time

import httpx
import uvicorn

from app import db as dbmod
from app.main import app


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_login_then_me_immediately_with_slow_cleanup():
    def slow_get_db():
        conn = dbmod.connect()
        try:
            yield conn
        finally:
            time.sleep(1.0)  # simuliert langsame Platte nach dem Senden der Antwort
            conn.close()

    app.dependency_overrides[dbmod.get_db] = slow_get_db
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    try:
        for _ in range(50):
            if server.started:
                break
            time.sleep(0.1)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as c:
            r = c.post("/api/v1/auth/login", json={"username": "admin", "password": os.environ["ITD_ADMIN_PASSWORD"]})
            assert r.status_code == 200, r.text
            r = c.get("/api/v1/me")  # sofort, ohne auf das Aufräumen zu warten
            assert r.status_code == 200, "Session war beim direkten Folgeaufruf noch nicht gespeichert"
        # Viele schnelle Aufrufe am echten Server (Thread-Wechsel der Verbindung)
        app.dependency_overrides.clear()
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as c:
            c.post("/api/v1/auth/login", json={"username": "admin", "password": os.environ["ITD_ADMIN_PASSWORD"]})
            codes = [c.patch("/api/v1/me", json={"display_name": f"Admin {i}"}).status_code for i in range(40)]
            codes += [c.get("/api/v1/me").status_code for _ in range(20)]
            c.patch("/api/v1/me", json={"display_name": "Administrator"})
            assert set(codes) == {200}, codes
    finally:
        server.should_exit = True
        t.join(5)
        app.dependency_overrides.clear()
