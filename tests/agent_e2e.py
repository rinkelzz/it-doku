"""Ende-zu-Ende-Test für die Agenten (läuft in CI auf Windows, macOS und Linux).

Startet die App mit leerer Datenbank auf 127.0.0.1, legt einen Agenten an, führt den übergebenen Befehl aus
({url} und {token} werden ersetzt) und prüft, dass ein Bericht angekommen und ein Gerät angelegt ist.

  python tests/agent_e2e.py python3 app/agent/itdoku-agent.py --run --url {url} --token {token} --allow-http
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.update({"ITD_DATA_DIR": tempfile.mkdtemp(), "ITD_SCHEDULER": "0", "ITD_UPDATE_CHECK": "0",
                   "ITD_SELF_RESTART": "0", "ITD_ADMIN_PASSWORD": "e2e-passwort-123"})


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    import uvicorn

    from app import agents
    from app.config import settings
    from app.main import app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    token = agents.new_token()
    aid = conn.execute("INSERT INTO agents(name, token_hash, token_hint, created_at) VALUES ('e2e', ?, ?, '2026-01-01T00:00:00Z')",
                       (agents.token_hash(token), agents.hint(token))).lastrowid
    args = sys.argv[1:]
    expect_scan = "--expect-scan" in args
    if expect_scan:
        args.remove("--expect-scan")
        # Netz, das der Agent vor Ort scannen soll (Loopback: 127.0.0.1 antwortet immer)
        conn.execute("INSERT INTO networks(name, cidr, scan, scan_agent_id, scan_requested, sort, created_at) VALUES ('Loopback', '127.0.0.0/30', 1, ?, 1, 0, '2026-01-01T00:00:00+00:00')",
                     (aid,))
    conn.commit()
    cmd = [a.replace("{url}", f"http://127.0.0.1:{port}").replace("{token}", token) for a in args]
    print("Starte:", " ".join(c if token not in c else "<token>" for c in cmd), flush=True)
    rc = subprocess.call(cmd, cwd=str(ROOT), timeout=900)
    a = conn.execute("SELECT * FROM agents WHERE name = 'e2e'").fetchone()
    server.should_exit = True
    if rc != 0:
        print(f"Agent endete mit Code {rc}")
        return 1
    if not a["report"] or not a["device_id"]:
        print("Kein Bericht angekommen")
        return 1
    rep = json.loads(a["report"])
    d = conn.execute("SELECT * FROM devices WHERE id = ?", (a["device_id"],)).fetchone()
    summary = {"platform": rep["platform"], "hostname": rep["hostname"], "os": rep["os"]["name"], "cpu": rep["hardware"]["cpu"],
               "ram_mb": rep["hardware"]["ram_mb"], "disks": len(rep["disks"]), "interfaces": len(rep["network"]["interfaces"]),
               "software": len(rep["software"]), "services": len(rep["services"]), "updates": rep["updates"],
               "device": dict(d)}
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str)[:4000])
    problems = [k for k in ("platform", "hostname", "os", "cpu", "ram_mb", "disks", "interfaces", "software") if not summary[k]]
    if expect_scan:
        run = conn.execute("SELECT * FROM scan_runs WHERE agent_id = ?", (aid,)).fetchone()
        hosts = [dict(h) for h in conn.execute("SELECT ip, ports FROM scan_hosts WHERE run_id = ?", (run["id"],))] if run else []
        print("Scan:", dict(run) if run else None, hosts)
        if not run or not any(h["ip"] == "127.0.0.1" for h in hosts):
            problems.append("Scan-Ergebnis (127.0.0.1)")
    if problems:
        print("Fehlt im Bericht:", ", ".join(problems))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
