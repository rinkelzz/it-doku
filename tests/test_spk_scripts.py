"""Paket-Skripte: belegter Port wird vor der Installation und beim Start klar gemeldet."""
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "synology" / "scripts"
pytestmark = pytest.mark.skipif(not shutil.which("sh") or os.name == "nt", reason="nur mit POSIX-Shell")


def _script(tmp_path, name):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + (SCRIPTS / "common").read_text(encoding="utf-8") + (SCRIPTS / name).read_text(encoding="utf-8"), encoding="utf-8")
    p.chmod(0o755)
    return p


def _run(tmp_path, name, *args, **env):
    (tmp_path / "target").mkdir(exist_ok=True)
    (tmp_path / "var").mkdir(exist_ok=True)
    msg = tmp_path / "msg"
    if msg.exists():
        msg.unlink()
    e = dict(os.environ, SYNOPKG_PKGDEST=str(tmp_path / "target"), SYNOPKG_PKGVAR=str(tmp_path / "var"),
             SYNOPKG_TEMP_LOGFILE=str(msg), ITD_PYTHON=sys.executable, **env)
    r = subprocess.run(["sh", str(_script(tmp_path, name)), *args], env=e, capture_output=True, text=True, timeout=60)
    return r.returncode, msg.read_text(encoding="utf-8") if msg.exists() else ""


@pytest.fixture()
def busy():
    s = socket.socket()
    s.bind(("0.0.0.0", 0))
    s.listen(1)
    yield s.getsockname()[1]
    s.close()


def test_preinst_rejects_busy_and_dsm_ports(tmp_path, busy):
    rc, msg = _run(tmp_path, "preinst", wizard_port=str(busy))
    assert rc == 1 and "schon belegt" in msg
    rc, msg = _run(tmp_path, "preinst", wizard_port="5000")
    assert rc == 1 and "DSM selbst" in msg
    rc, _ = _run(tmp_path, "preinst", wizard_port=str(busy), SYNOPKG_PKG_STATUS="UPGRADE")
    assert rc == 0


def test_postinst_applies_wizard_port_to_old_config(tmp_path):
    (tmp_path / "var").mkdir()
    (tmp_path / "var" / "config.env").write_text("ITD_PORT=8780\nITD_TIMEZONE=\"Europe/Berlin\"\n", encoding="utf-8")
    _run(tmp_path, "postinst", wizard_port="18781")
    cfg = (tmp_path / "var" / "config.env").read_text(encoding="utf-8")
    assert "ITD_PORT=18781" in cfg and "ITD_TIMEZONE" in cfg


def test_start_reports_busy_port(tmp_path, busy):
    (tmp_path / "var").mkdir()
    (tmp_path / "var" / "config.env").write_text(f"ITD_PORT={busy}\n", encoding="utf-8")
    rc, msg = _run(tmp_path, "start-stop-status", "start")
    assert rc == 1 and f"Port {busy} ist schon belegt" in msg
