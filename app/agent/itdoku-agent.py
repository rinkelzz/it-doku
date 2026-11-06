#!/usr/bin/env python3
"""IT-Dokumentation – Agent für Linux und macOS.

Sammelt Hardware, System, Datenträger, Netzwerk, installierte Software, Updates und Dienste und schickt sie per HTTPS
an die IT-Dokumentation. Braucht nur Python 3.6+ (Standardbibliothek), keine Zusatzpakete.

  Einrichten (als root):   sudo python3 itdoku-agent.py --install --url https://doku.example.de --token itd_…
  Einmal melden:           sudo itdoku-agent --run
  Nur ansehen (nichts senden): python3 itdoku-agent.py --print
  Entfernen:               sudo itdoku-agent --uninstall

Linux: systemd-Timer (täglich + 2 Minuten nach dem Start), ohne systemd ein Cron-Eintrag.
macOS: LaunchDaemon (täglich + beim Start).
Konfiguration: /etc/itdoku-agent.conf (nur für root lesbar).
"""
import argparse
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = "1.0"
CONF = "/etc/itdoku-agent.conf"
BIN = "/usr/local/bin/itdoku-agent"
IS_MAC = sys.platform == "darwin"
SYSTEMD_SERVICE = "/etc/systemd/system/itdoku-agent.service"
SYSTEMD_TIMER = "/etc/systemd/system/itdoku-agent.timer"
CRON_FILE = "/etc/cron.d/itdoku-agent"
PLIST = "/Library/LaunchDaemons/de.itdoku.agent.plist"


# --- Hilfen -----------------------------------------------------------------

def run(cmd, timeout=60):
    """Befehl ausführen, Ausgabe als Text; bei Fehler leer (der Agent soll nie an einem einzelnen Teil scheitern)."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C", LANG="C"))
        return p.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def run_rc(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                           env=dict(os.environ, LC_ALL="C", LANG="C"))
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None, ""


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def which(name):
    return shutil.which(name, path=os.environ.get("PATH", "") + ":/usr/sbin:/sbin:/usr/bin:/bin:/usr/local/bin")


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def part(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 – ein kaputter Teil darf den Bericht nicht verhindern
        return default


# --- Linux ------------------------------------------------------------------

def linux_os():
    rel = {}
    for line in read("/etc/os-release").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            rel[k] = v.strip().strip('"')
    return {"name": rel.get("PRETTY_NAME") or rel.get("NAME") or "Linux", "version": rel.get("VERSION_ID", ""),
            "build": "", "arch": platform.machine(), "kernel": platform.release()}


def linux_hw():
    dmi = "/sys/class/dmi/id/"
    cpu, cores = "", 0
    for line in read("/proc/cpuinfo").splitlines():
        if line.startswith(("model name", "Hardware", "Model")) and not cpu:
            cpu = line.split(":", 1)[1].strip()
        if line.startswith("processor"):
            cores += 1
    mem = re.search(r"MemTotal:\s+(\d+)", read("/proc/meminfo"))
    chassis_type = read(dmi + "chassis_type")
    virt = run(["systemd-detect-virt"], 10).strip() if which("systemd-detect-virt") else ""
    chassis = "desktop"
    if chassis_type in ("8", "9", "10", "14", "31", "32"):
        chassis = "laptop"
    elif chassis_type in ("17", "23", "28", "29"):
        chassis = "server"
    if virt and virt != "none":
        chassis = "vm"
    return {"manufacturer": read(dmi + "sys_vendor"), "model": read(dmi + "product_name"),
            "serial": read(dmi + "product_serial"), "cpu": cpu, "cores": cores or os.cpu_count(),
            "ram_mb": int(mem.group(1)) // 1024 if mem else None, "chassis": chassis,
            "virtual": bool(virt and virt != "none"), "bios": " ".join(x for x in (read(dmi + "bios_vendor"), read(dmi + "bios_version")) if x)}


REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "vfat", "exfat", "ntfs", "ntfs3", "f2fs", "jfs", "reiserfs", "apfs", "hfs"}


def linux_disks():
    out, seen = [], set()
    for line in read("/proc/mounts").splitlines():
        f = line.split()
        if len(f) < 3 or f[2] not in REAL_FS or f[0] in seen:
            continue
        mount = f[1].replace("\\040", " ")
        if mount.startswith(("/snap/", "/boot/efi")) or "/docker/" in mount:
            continue
        seen.add(f[0])
        try:
            st = os.statvfs(mount)
        except OSError:
            continue
        out.append({"mount": mount, "fs": f[2], "total_gb": round(st.f_blocks * st.f_frsize / 1e9, 1),
                    "free_gb": round(st.f_bavail * st.f_frsize / 1e9, 1)})
    return out


def linux_net():
    ifaces = []
    data = run(["ip", "-j", "addr"], 10) if which("ip") else ""
    try:
        for i in json.loads(data or "[]"):
            if i.get("ifname") == "lo":
                continue
            v4 = [a["local"] for a in i.get("addr_info", []) if a.get("family") == "inet"]
            v6 = [a["local"] for a in i.get("addr_info", []) if a.get("family") == "inet6" and a.get("scope") == "global"]
            ifaces.append({"name": i.get("ifname", ""), "mac": i.get("address", ""), "ipv4": v4, "ipv6": v6})
    except ValueError:
        pass
    if not ifaces:
        ifaces = linux_ifaces_fallback()
    gw = []
    for line in read("/proc/net/route").splitlines()[1:]:
        f = line.split()
        if len(f) > 2 and f[1] == "00000000" and f[2] != "00000000":
            g = bytes.fromhex(f[2])[::-1]
            gw.append(".".join(str(b) for b in g))
    dns = re.findall(r"^\s*nameserver\s+(\S+)", read("/etc/resolv.conf"), re.M)
    if dns == ["127.0.0.53"] and which("resolvectl"):
        found = re.findall(r"DNS Servers?:\s*(.+)", run(["resolvectl", "status"], 10))
        real = [x for line in found for x in line.split()]
        dns = real or dns
    return {"interfaces": ifaces, "gateway": gw, "dns": dns}


def linux_ifaces_fallback():
    """Ohne „ip“-Befehl (z. B. Minimal-Container): Schnittstellen aus /sys, IPv4 per ioctl, IPv6 aus /proc."""
    import fcntl
    import struct
    v6 = {}
    for line in read("/proc/net/if_inet6").splitlines():
        f = line.split()
        if len(f) >= 6 and f[3] == "00":  # global
            h = f[0]
            v6.setdefault(f[5], []).append(":".join(h[i:i + 4] for i in range(0, 32, 4)))
    out = []
    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        names = []
    for name in names:
        if name == "lo":
            continue
        v4 = []
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            res = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", name[:15].encode()))  # SIOCGIFADDR
            v4.append(socket.inet_ntoa(res[20:24]))
        except OSError:
            pass
        finally:
            s.close()
        if v4 or v6.get(name):
            out.append({"name": name, "mac": read("/sys/class/net/{}/address".format(name)), "ipv4": v4, "ipv6": v6.get(name, [])})
    return out


def linux_software():
    if which("dpkg-query"):
        out = run(["dpkg-query", "-W", "-f", "${db:Status-Abbrev}\t${Package}\t${Version}\t${Maintainer}\n"], 120)
        return [{"name": f[1], "version": f[2], "publisher": re.sub(r"\s*<.*>", "", f[3]) if len(f) > 3 else ""}
                for f in (line.split("\t") for line in out.splitlines()) if len(f) >= 3 and f[0].startswith("ii")]
    if which("rpm"):
        out = run(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\t%{VENDOR}\t%{INSTALLTIME}\n"], 120)
        res = []
        for f in (line.split("\t") for line in out.splitlines()):
            if len(f) >= 2 and not f[0].startswith("gpg-pubkey"):
                inst = iso(int(f[3])) if len(f) > 3 and f[3].isdigit() else ""
                res.append({"name": f[0], "version": f[1], "publisher": f[2] if len(f) > 2 and f[2] != "(none)" else "", "installed_on": inst})
        return res
    if which("apk"):
        return [{"name": m.group(1), "version": m.group(2)} for m in
                (re.match(r"^(.+)-(\d[^-]*-r\d+)", line) for line in run(["apk", "info", "-v"], 60).splitlines()) if m]
    if which("pacman"):
        return [{"name": f[0], "version": f[1]} for f in (line.split() for line in run(["pacman", "-Q"], 60).splitlines()) if len(f) == 2]
    return []


def linux_updates():
    res = {"pending": None, "security": None, "items": [], "reboot_required": None, "last_installed": ""}
    if which("apt-get"):
        out = run(["apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"], 180)
        items = re.findall(r"^Inst (\S+) (?:\[\S+\] )?\((\S+) ([^)]*)\)", out, re.M)
        res["pending"] = len(items)
        res["security"] = sum(1 for i in items if "security" in i[2].lower())
        res["items"] = ["{} {}".format(n, v) for n, v, _ in items][:300]
        res["reboot_required"] = os.path.exists("/var/run/reboot-required")
        hist = read("/var/log/apt/history.log")
        dates = re.findall(r"^End-Date: (\d{4}-\d{2}-\d{2})", hist, re.M)
        if dates:
            res["last_installed"] = dates[-1]
    elif which("dnf") or which("yum"):
        tool = "dnf" if which("dnf") else "yum"
        rc, out = run_rc([tool, "-q", "check-update"], 300)
        lines = [line for line in out.splitlines() if re.match(r"^\S+\.\S+\s+\S+\s+\S+", line)]
        res["pending"] = len(lines) if rc in (0, 100) else None
        res["items"] = [" ".join(line.split()[:2]) for line in lines][:300]
        if which("needs-restarting"):
            rc2, _ = run_rc(["needs-restarting", "-r"], 60)
            res["reboot_required"] = rc2 == 1 if rc2 is not None else None
        last = run(["rpm", "-qa", "--last"], 60).splitlines()[:1]
        if last:
            m = re.search(r"\s{2,}(.+)$", last[0])
            if m:
                try:
                    res["last_installed"] = datetime.strptime(m.group(1).strip()[:24], "%a %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
                except ValueError:
                    pass
    elif which("apk"):
        out = run(["apk", "version", "-l", "<"], 120)
        res["pending"] = max(0, len(out.splitlines()) - 1)
    return res


def linux_services():
    if not which("systemctl"):
        return []
    enabled = {}
    for line in run(["systemctl", "list-unit-files", "--type=service", "--no-legend", "--plain"], 30).splitlines():
        f = line.split()
        if len(f) >= 2:
            enabled[f[0]] = f[1]
    out = []
    for line in run(["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--plain"], 30).splitlines():
        f = line.split(None, 4)
        if len(f) < 4 or not f[0].endswith(".service"):
            continue
        name, active, sub = f[0], f[2], f[3]
        en = enabled.get(name, "")
        if en in ("static", "indirect", "generated", "transient", "alias") or "@" in name:
            continue  # nur echte, gezielt eingeschaltete Dienste
        state = "running" if sub == "running" else "failed" if active == "failed" else "stopped"
        if sub == "exited" and active == "active":
            state = "running"  # Einmal-Dienste (oneshot) gelten als in Ordnung
        out.append({"name": name[:-8], "display": f[4] if len(f) > 4 else "", "state": state,
                    "start": "auto" if en == "enabled" else "disabled" if en in ("disabled", "masked") else "manual"})
    return out


def linux_boot():
    m = re.search(r"^btime (\d+)", read("/proc/stat"), re.M)
    return iso(int(m.group(1))) if m else ""


# --- macOS ------------------------------------------------------------------

def mac_profiler(kind, timeout=120):
    try:
        return json.loads(run(["system_profiler", "-json", kind], timeout) or "{}").get(kind, [])
    except ValueError:
        return []


def mac_os():
    return {"name": "macOS " + run(["sw_vers", "-productVersion"]).strip(), "version": run(["sw_vers", "-productVersion"]).strip(),
            "build": run(["sw_vers", "-buildVersion"]).strip(), "arch": platform.machine(), "kernel": platform.release()}


def mac_hw():
    hw = (mac_profiler("SPHardwareDataType", 30) or [{}])[0]
    model = hw.get("machine_name", "") or run(["sysctl", "-n", "hw.model"]).strip()
    mem = run(["sysctl", "-n", "hw.memsize"]).strip()
    cpu = run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or hw.get("chip_type", "")
    return {"manufacturer": "Apple", "model": " ".join(x for x in (model, hw.get("machine_model", "")) if x),
            "serial": hw.get("serial_number", ""), "cpu": cpu, "cores": int(run(["sysctl", "-n", "hw.ncpu"]).strip() or 0) or None,
            "ram_mb": int(mem) // 1048576 if mem.isdigit() else None,
            "chassis": "laptop" if "book" in model.lower() else "desktop", "virtual": "virtual" in model.lower(),
            "bios": hw.get("boot_rom_version", "")}


def mac_disks():
    out = []
    for mount in ("/", "/System/Volumes/Data"):
        try:
            st = os.statvfs(mount)
        except OSError:
            continue
        out.append({"mount": mount, "fs": "apfs", "total_gb": round(st.f_blocks * st.f_frsize / 1e9, 1),
                    "free_gb": round(st.f_bavail * st.f_frsize / 1e9, 1)})
    if len(out) == 2 and out[0]["total_gb"] == out[1]["total_gb"]:
        out = out[1:]  # Systemvolume und Datenvolume teilen sich den Container
    for line in run(["df", "-kP"]).splitlines()[1:]:
        f = line.split(None, 5)
        if len(f) == 6 and f[5].startswith("/Volumes/") and f[0].startswith("/dev/"):
            out.append({"mount": f[5], "fs": "", "total_gb": round(int(f[1]) * 1024 / 1e9, 1), "free_gb": round(int(f[3]) * 1024 / 1e9, 1)})
    return out


def mac_net():
    ifaces, cur = [], None
    for line in run(["ifconfig"]).splitlines():
        m = re.match(r"^(\w[\w.]*): flags", line)
        if m:
            cur = {"name": m.group(1), "mac": "", "ipv4": [], "ipv6": []}
            if not cur["name"].startswith(("lo", "gif", "stf", "awdl", "llw", "utun", "anpi", "ap", "bridge")):
                ifaces.append(cur)
            continue
        if not cur:
            continue
        f = line.split()
        if f and f[0] == "ether":
            cur["mac"] = f[1]
        elif f and f[0] == "inet":
            cur["ipv4"].append(f[1])
        elif f and f[0] == "inet6" and not f[1].startswith("fe80"):
            cur["ipv6"].append(f[1].split("%")[0])
    ifaces = [i for i in ifaces if i["ipv4"] or i["ipv6"]]
    gw = re.findall(r"gateway: (\S+)", run(["route", "-n", "get", "default"]))
    dns = []
    for x in re.findall(r"nameserver\[\d+\] : (\S+)", run(["scutil", "--dns"])):
        if x not in dns:
            dns.append(x)
    return {"interfaces": ifaces, "gateway": gw, "dns": dns[:8]}


def mac_software():
    out = []
    for a in mac_profiler("SPApplicationsDataType", 240):
        path = a.get("path", "")
        if path.startswith(("/System/", "/Library/Apple/")) or "/Contents/" in path:
            continue
        out.append({"name": a.get("_name", ""), "version": a.get("version", ""),
                    "publisher": (a.get("signed_by") or [""])[0].replace("Developer ID Application: ", "") if isinstance(a.get("signed_by"), list) else "",
                    "installed_on": (a.get("lastModified") or "")[:10]})
    brew = which("brew")
    if brew:
        for line in run([brew, "list", "--versions"], 60).splitlines():
            f = line.split()
            if len(f) >= 2:
                out.append({"name": f[0], "version": f[-1], "publisher": "Homebrew"})
    return out


def mac_updates():
    out = run(["softwareupdate", "-l"], 300)
    items = re.findall(r"^\s*\* Label: (.+)$", out, re.M)
    hist = mac_profiler("SPInstallHistoryDataType", 60)
    dates = sorted((h.get("install_date") or "")[:10] for h in hist if h.get("install_date"))
    return {"pending": len(items), "items": items, "security": sum(1 for i in items if "security" in i.lower()),
            "reboot_required": any("restart" in line.lower() for line in out.splitlines() if "Action" in line or "[restart]" in line),
            "last_installed": dates[-1] if dates else ""}


def mac_services():
    running = {}
    for line in run(["launchctl", "list"]).splitlines()[1:]:
        f = line.split("\t")
        if len(f) == 3:
            running[f[2]] = f[0] != "-"
    out = []
    for folder in ("/Library/LaunchDaemons", "/Library/LaunchAgents"):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for fn in names:
            if not fn.endswith(".plist") or fn.startswith("com.apple."):
                continue
            label = fn[:-6]
            out.append({"name": label, "display": folder.split("/")[-1], "state": "running" if running.get(label) else "stopped",
                        "start": "auto" if "RunAtLoad" in read(os.path.join(folder, fn)) and "KeepAlive" in read(os.path.join(folder, fn)) else "manual"})
    return out


def mac_boot():
    m = re.search(r"sec = (\d+)", run(["sysctl", "-n", "kern.boottime"]))
    return iso(int(m.group(1))) if m else ""


# --- Bericht ----------------------------------------------------------------

def collect():
    host = socket.gethostname()
    if IS_MAC:
        host = run(["scutil", "--get", "LocalHostName"]).strip() or host
        rep = {"platform": "macos", "os": part(mac_os, {}), "hardware": part(mac_hw, {}), "disks": part(mac_disks, []),
               "network": part(mac_net, {}), "software": part(mac_software, []), "updates": part(mac_updates, {}),
               "services": part(mac_services, []), "boot_time": part(mac_boot, "")}
    else:
        rep = {"platform": "linux", "os": part(linux_os, {}), "hardware": part(linux_hw, {}), "disks": part(linux_disks, []),
               "network": part(linux_net, {}), "software": part(linux_software, []), "updates": part(linux_updates, {}),
               "services": part(linux_services, []), "boot_time": part(linux_boot, "")}
    rep.update({"agent_version": VERSION, "hostname": host.split(".")[0], "domain": ".".join(socket.getfqdn().split(".")[1:])})
    return rep


def load_conf():
    try:
        with open(CONF, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        sys.exit("Keine Konfiguration in {} – zuerst mit --install --url … --token … einrichten".format(CONF))


def check_url(url, allow_http):
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("https", "http") or not p.netloc:
        sys.exit("Ungültige Adresse: " + url)
    if p.scheme == "http" and not allow_http:
        sys.exit("Unverschlüsselte Adresse (http://). Nur im VPN/LAN sinnvoll – dann mit --allow-http bestätigen.")
    return url.rstrip("/")


def send(conf, rep):
    data = json.dumps(rep).encode("utf-8")
    req = urllib.request.Request(conf["url"] + "/api/agent/v1/report", data=data, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + conf["token"],
                                          "User-Agent": "itdoku-agent/" + VERSION})
    ctx = ssl.create_default_context()
    if conf.get("insecure"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            if e.code in (401, 403, 413, 400):
                sys.exit("Abgelehnt ({}): {}".format(e.code, msg))
            last = "HTTP {}: {}".format(e.code, msg)
        except (urllib.error.URLError, OSError) as e:
            last = str(e)
        time.sleep(10 * (attempt + 1))
    sys.exit("Senden fehlgeschlagen: " + str(last))


# --- Einrichten -------------------------------------------------------------

def install(args):
    if os.geteuid() != 0:
        sys.exit("Bitte als root ausführen (sudo).")
    conf = {"url": check_url(args.url, args.allow_http), "token": args.token.strip(), "insecure": bool(args.insecure)}
    if not conf["token"].startswith("itd_"):
        sys.exit("Der Schlüssel beginnt mit itd_ – bitte aus der IT-Dokumentation kopieren.")
    old = os.umask(0o077)
    try:
        with open(CONF, "w", encoding="utf-8") as f:
            json.dump(conf, f)
    finally:
        os.umask(old)
    os.chmod(CONF, 0o600)
    os.makedirs(os.path.dirname(BIN), exist_ok=True)
    shutil.copyfile(os.path.abspath(__file__), BIN)
    os.chmod(BIN, 0o755)
    py = sys.executable or "/usr/bin/python3"
    if IS_MAC:
        with open(PLIST, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>de.itdoku.agent</string>
  <key>ProgramArguments</key><array><string>{py}</string><string>{bin}</string><string>--run</string><string>--quiet</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>86400</integer>
  <key>StandardErrorPath</key><string>/var/log/itdoku-agent.log</string>
</dict></plist>
""".format(py=py, bin=BIN))
        os.chmod(PLIST, 0o644)
        run(["launchctl", "unload", PLIST], 30)
        run(["launchctl", "load", "-w", PLIST], 30)
        print("Eingerichtet: LaunchDaemon de.itdoku.agent (täglich und beim Start).")
    elif which("systemctl") and os.path.isdir("/run/systemd/system"):
        with open(SYSTEMD_SERVICE, "w", encoding="utf-8") as f:
            f.write("[Unit]\nDescription=IT-Dokumentation Agent\nWants=network-online.target\nAfter=network-online.target\n\n"
                    "[Service]\nType=oneshot\nExecStart={} {} --run --quiet\nNice=10\nIOSchedulingClass=idle\n".format(py, BIN))
        with open(SYSTEMD_TIMER, "w", encoding="utf-8") as f:
            f.write("[Unit]\nDescription=IT-Dokumentation Agent (täglich)\n\n[Timer]\nOnBootSec=2min\nOnUnitActiveSec=1d\n"
                    "RandomizedDelaySec=30min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n")
        run(["systemctl", "daemon-reload"], 30)
        run(["systemctl", "enable", "--now", "itdoku-agent.timer"], 30)
        print("Eingerichtet: systemd-Timer itdoku-agent.timer (täglich und nach dem Start).")
    else:
        with open(CRON_FILE, "w", encoding="utf-8") as f:
            f.write("SHELL=/bin/sh\n{m} {h} * * * root {py} {bin} --run --quiet\n@reboot root sleep 120 && {py} {bin} --run --quiet\n".format(
                m=int(time.time()) % 60, h=int(time.time() / 60) % 24, py=py, bin=BIN))
        print("Eingerichtet: Cron-Eintrag {} (täglich und nach dem Start).".format(CRON_FILE))
    res = send(conf, collect())
    print("Erster Bericht gesendet – Gerät #{} in der IT-Dokumentation{}.".format(res.get("device_id"), " (neu angelegt)" if res.get("created") else ""))


def uninstall():
    if os.geteuid() != 0:
        sys.exit("Bitte als root ausführen (sudo).")
    if IS_MAC:
        run(["launchctl", "unload", "-w", PLIST], 30)
    elif which("systemctl"):
        run(["systemctl", "disable", "--now", "itdoku-agent.timer"], 30)
    for p in (PLIST, SYSTEMD_SERVICE, SYSTEMD_TIMER, CRON_FILE, CONF, BIN):
        try:
            os.remove(p)
        except OSError:
            pass
    if not IS_MAC and which("systemctl"):
        run(["systemctl", "daemon-reload"], 30)
    print("Agent entfernt. Den Agenten in der IT-Dokumentation bitte unter Verwaltung → Agenten löschen oder sperren.")


def main():
    ap = argparse.ArgumentParser(description="IT-Dokumentation – Agent für Linux und macOS")
    ap.add_argument("--install", action="store_true", help="einrichten (root): Konfiguration, Zeitplan, erster Bericht")
    ap.add_argument("--uninstall", action="store_true", help="entfernen (root)")
    ap.add_argument("--run", action="store_true", help="Bericht jetzt senden")
    ap.add_argument("--print", action="store_true", help="Bericht nur anzeigen, nichts senden")
    ap.add_argument("--url", help="Adresse der IT-Dokumentation, z. B. https://doku.example.de (bei --run: statt der Konfiguration)")
    ap.add_argument("--token", help="Agent-Schlüssel (itd_…)")
    ap.add_argument("--allow-http", action="store_true", help="unverschlüsseltes http:// erlauben (nur im VPN/LAN)")
    ap.add_argument("--insecure", action="store_true", help="Zertifikat nicht prüfen (nur für selbstsignierte Zertifikate im LAN)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args()
    if args.print:
        print(json.dumps(collect(), indent=2, ensure_ascii=False))
    elif args.install:
        if not args.url or not args.token:
            ap.error("--install braucht --url und --token")
        install(args)
    elif args.uninstall:
        uninstall()
    elif args.run:
        conf = load_conf() if not (args.url and args.token) else \
            {"url": check_url(args.url, args.allow_http), "token": args.token.strip(), "insecure": bool(args.insecure)}
        res = send(conf, collect())
        if not args.quiet:
            print("Bericht gesendet (Gerät #{}).".format(res.get("device_id")))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
