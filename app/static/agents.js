// IT-Dokumentation – Agenten: Verwaltung, Einrichtung, Bericht am Gerät, Hinweis auf der Übersicht
"use strict";

const AG_PLAT = { windows: "Windows", linux: "Linux", macos: "macOS", synology: "Synology" };
const agState = { list: [], settings: {} };

function agAgo(ts) {
  if (!ts) return "noch nie";
  const min = Math.round((Date.now() - new Date(ts).getTime()) / 60000);
  if (min < 2) return "gerade eben";
  if (min < 60) return `vor ${min} Min.`;
  if (min < 48 * 60) return `vor ${Math.round(min / 60)} Std.`;
  return `vor ${Math.round(min / 1440)} Tagen`;
}
const gb = (n) => n == null ? "?" : (n >= 1000 ? (n / 1000).toFixed(1) + " TB" : (n >= 100 ? Math.round(n) : n.toFixed(1)) + " GB").replace(".", ",");
const ramText = (mb) => !mb ? "" : mb >= 1024 ? Math.round(mb / 1024) + " GB" : mb + " MB";

// ---------- Einrichtungs-Dialog (Schlüssel + Befehl) ----------
function agCommands(url, token) {
  const http = url.startsWith("http://");
  return {
    windows: `[Net.ServicePointManager]::SecurityProtocol = 'Tls12'\n` +
      `iwr ${url}/agent/itdoku-agent.ps1 -OutFile $env:TEMP\\itdoku-agent.ps1 -UseBasicParsing\n` +
      `powershell -ExecutionPolicy Bypass -File $env:TEMP\\itdoku-agent.ps1 -Install -Url ${url} -Token ${token}${http ? " -AllowHttp" : ""}`,
    linux: `curl -fsSL ${url}/agent/itdoku-agent.py -o /tmp/itdoku-agent.py\n` +
      `sudo python3 /tmp/itdoku-agent.py --install --url ${url} --token ${token}${http ? " --allow-http" : ""}`,
    macos: `curl -fsSL ${url}/agent/itdoku-agent.py -o /tmp/itdoku-agent.py\n` +
      `sudo /usr/bin/python3 /tmp/itdoku-agent.py --install --url ${url} --token ${token}${http ? " --allow-http" : ""}`,
    synology: `sudo -i\n` +
      `curl -fsSL ${url}/agent/itdoku-agent.py -o /tmp/itdoku-agent.py\n` +
      `python3 /tmp/itdoku-agent.py --install --url ${url} --token ${token}${http ? " --allow-http" : ""}`,
  };
}
const AG_NOTES = {
  windows: "In einer PowerShell <b>als Administrator</b> einfügen. Legt die geplante Aufgabe „ITDoku Agent“ an (läuft als SYSTEM, täglich und nach dem Start) und schickt sofort den ersten Bericht. Keine Zusatzmodule nötig (ab Windows 10 / Server 2016).",
  linux: "Als Benutzer mit sudo einfügen. Installiert nach /usr/local/bin, legt einen systemd-Timer an (täglich und nach dem Start; ohne systemd einen Cron-Eintrag) und schickt sofort den ersten Bericht. Braucht nur Python 3 (Standardbibliothek).",
  synology: "Per SSH auf der Synology anmelden (DSM: Systemsteuerung → Terminal &amp; SNMP → SSH aktivieren; Benutzer aus der Gruppe administrators) und einfügen. " +
    "Danach im <b>DSM-Aufgabenplaner</b> die Aufgabe anlegen, die der Befehl am Ende anzeigt (Benutzer root, stündlich) – DSM-Updates lassen sie stehen. " +
    "Die NAS meldet sich dann selbst (Modell, Seriennummer, DSM-Version, Volumes, Pakete) und kann <b>das Netz vor Ort scannen</b>: " +
    "am Netz unter „Gescannt von“ diesen Agenten wählen. SSH danach gern wieder ausschalten.",
  macos: "Im Terminal einfügen (Administrator). Legt einen LaunchDaemon an (täglich und beim Start) und schickt sofort den ersten Bericht. Python 3 kommt mit den Command Line Tools (<span class=\"mono\">xcode-select --install</span>).",
};
function agSetup(name, token, urls, platform) {
  let plat = platform || "windows";
  const choices = [urls.lan ? ["lan", "Im LAN / VPN", urls.lan] : null, urls.external ? ["external", "Von außen", urls.external] : null].filter(Boolean);
  let where = choices[0][0];
  let url = choices[0][2];
  $("sheet").innerHTML = `<div class="card">
    <div class="toolbar"><h2>Agent „${esc(name)}“ einrichten</h2><button data-x title="Schließen">✕</button></div>
    <p class="small" style="margin:0">Schlüssel – <b>nur jetzt sichtbar</b>: <span class="mono">${esc(token)}</span> <button class="mini" data-copytok>⧉ kopieren</button></p>
    <div class="row" style="margin:12px 0 8px;gap:12px;flex-wrap:wrap">
      <div class="seg">${Object.entries(AG_PLAT).map(([k, l]) => `<button data-plat="${k}">${l}</button>`).join("")}</div>
      ${choices.length > 1 ? `<div class="seg">${choices.map(([k, l]) => `<button data-where="${k}">${l}</button>`).join("")}</div>` : ""}
    </div>
    <p class="muted small" style="margin:0 0 6px">Adresse: <span class="mono" data-url></span></p>
    <div class="cmd" data-cmd></div>
    <div class="row" style="margin-top:8px"><button class="primary" data-copycmd>⧉ Befehl kopieren</button><span class="muted small" data-ok></span></div>
    <p class="muted small" data-note></p>
    <div class="httpwarn small hidden" data-httpw>Unverschlüsselt (http://) – nur für Rechner im LAN oder per VPN. Für Rechner draußen unter
      Einstellungen eine https-Adresse „von außen“ eintragen.</div>
    <div class="row"><button data-x>Fertig</button></div></div>`;
  $("sheet").classList.remove("hidden");
  const card = $("sheet").firstElementChild;
  let cmds;
  const show = () => {
    url = choices.find(c => c[0] === where)[2];
    cmds = agCommands(url, token);
    $$("[data-plat]", card).forEach(b => b.classList.toggle("on", b.dataset.plat === plat));
    $$("[data-where]", card).forEach(b => b.classList.toggle("on", b.dataset.where === where));
    card.querySelector("[data-url]").textContent = url;
    card.querySelector("[data-httpw]").classList.toggle("hidden", !url.startsWith("http://") || where !== "external");
    card.querySelector("[data-cmd]").textContent = cmds[plat];
    card.querySelector("[data-note]").innerHTML = AG_NOTES[plat];
  };
  show();
  $$("[data-plat]", card).forEach(b => b.onclick = () => { plat = b.dataset.plat; show(); });
  $$("[data-where]", card).forEach(b => b.onclick = () => { where = b.dataset.where; show(); });
  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text); okMsg(card.querySelector("[data-ok]"), "Kopiert."); }
    catch (e) { card.querySelector("[data-ok]").textContent = "Kopieren nicht möglich – bitte markieren und kopieren."; }
  };
  card.querySelector("[data-copytok]").onclick = () => copy(token);
  card.querySelector("[data-copycmd]").onclick = () => copy(cmds[plat]);
  $$("[data-x]", card).forEach(b => b.onclick = () => { closeSheet(); if (window.loadAgents && !$("agTable").closest(".hidden")) loadAgents(); });
}

async function agRenew(a, after) {
  if (!confirm(`Neuen Schlüssel für „${a.name}“ erzeugen? Der alte Schlüssel wird sofort ungültig – der Agent muss mit dem neuen Befehl neu eingerichtet werden.`)) return;
  try {
    const r = await api(`agents/${a.id}/token`, { method: "POST" });
    agSetup(a.name, r.token, r.urls, a.platform_label === "Synology" ? "synology" : a.platform);
    if (after) after();
  } catch (e) { alert(e.message); }
}
async function agToggle(a, after) {
  if (!a.disabled && !confirm(`Agent „${a.name}“ sperren? Seine Berichte werden dann abgelehnt.`)) return;
  try { await api(`agents/${a.id}`, { method: "PATCH", body: { disabled: !a.disabled } }); if (after) after(); } catch (e) { alert(e.message); }
}

// ---------- Verwaltung → Agenten ----------
async function loadAgents() {
  const r = await api("agents");
  agState.list = r.agents; agState.settings = r.settings;
  const u = r.settings.urls;
  $("agUrlLan").value = r.settings.agent_url_lan || "";
  $("agUrlLan").placeholder = u.lan_auto ? `${u.lan_auto} (automatisch)` : "http://192.168.10.5:8780";
  $("agUrl").value = r.settings.agent_url || "";
  $("agUrl").placeholder = u.external && !r.settings.agent_url ? u.external : "https://agent.kunde.de";
  $("agPort").textContent = r.settings.port;
  const st = $("agStale");
  if (![...st.options].some(o => o.value === String(r.settings.stale_days))) st.insertAdjacentHTML("beforeend", `<option value="${r.settings.stale_days}">${r.settings.stale_days} Tagen</option>`);
  st.value = String(r.settings.stale_days);
  $("agTable").innerHTML = r.agents.length ? `<thead><tr><th>Name</th><th>Gerät</th><th>System</th><th>Letzter Bericht</th></tr></thead><tbody>
    ${r.agents.map(a => {
      const p = a.problems || {};
      const warn = [p.updates_pending ? `${p.updates_pending} Update${p.updates_pending > 1 ? "s" : ""}` : "", p.reboot_required ? "Neustart" : "", p.disks_full ? "Platte voll" : "",
                    (p.services_stopped || []).length ? `${p.services_stopped.length} Dienst${p.services_stopped.length > 1 ? "e" : ""} gestoppt` : ""].filter(Boolean);
      return `<tr data-ag="${a.id}" class="click" title="Bearbeiten, sperren, neuer Schlüssel"><td><b>${esc(a.name)}</b>${a.disabled ? ' <span class="tag off">gesperrt</span>' : ""}<br><small class="muted mono">${esc(a.token_hint)}</small>${(a.scans || []).length ? `<br><span class="tag" title="scannt vor Ort">🔍 ${esc(a.scans.join(", "))}</span>` : ""}</td>
      <td>${a.device_id ? `<a href="#devices/${a.device_id}">${esc(a.device_icon || "🖥️")} ${esc(a.device_name)}</a>` : '<span class="muted">wird beim ersten Bericht zugeordnet</span>'}</td>
      <td>${esc(a.os_name || a.platform_label || "–")}${warn.length ? `<br>${warn.map(w => `<span class="tag warn">${esc(w)}</span>`).join(" ")}` : ""}</td>
      <td class="nowrap" data-sort="${esc(a.last_report_at || "")}">${a.last_report_at ? (a.stale ? `<span class="tag bad">${agAgo(a.last_report_at)}</span>` : agAgo(a.last_report_at)) : '<span class="muted">wartet</span>'}</td>
</tr>`;
    }).join("")}</tbody>` : '<tbody><tr><td class="muted">Noch kein Agent. Mit „＋ Agent“ einen Schlüssel erzeugen und den angezeigten Befehl auf dem Server ausführen.</td></tr></tbody>';
  sortTable($("agTable"));
  $$("#agTable [data-ag]").forEach(tr => tr.onclick = (e) => {
    if (e.target.closest("a")) return;
    agEdit(agState.list.find(x => x.id === Number(tr.dataset.ag)));
  });
}
function agEdit(a) {
  const card = openForm({ title: `Agent „${a.name}“`, narrow: true, fields: [
    { k: "name", label: "Name", max: 100 },
    { k: "disabled", label: "gesperrt (Berichte werden abgelehnt)", type: "check" }],
    values: { name: a.name, disabled: a.disabled },
    extra: '<p class="small" style="margin:0"><button class="mini" data-renew>Neuen Schlüssel erzeugen</button> <span class="muted">– der alte wird sofort ungültig</span></p>',
    save: async (v) => { await api(`agents/${a.id}`, { method: "PATCH", body: v }); loadAgents(); },
    del: { confirm: `Agent „${a.name}“ löschen? Das Gerät und seine Doku bleiben, nur der letzte Bericht verschwindet. Auf dem Server den Agenten danach mit --uninstall bzw. -Uninstall entfernen.`,
           run: async () => { await api(`agents/${a.id}`, { method: "DELETE" }); loadAgents(); } } });
  card.querySelector("[data-renew]").onclick = () => { closeSheet(); agRenew(a, loadAgents); };
}
window.loadAgents = loadAgents;

async function agNew() {
  const devs = (await api("devices?status=all")).filter(d => !agState.list.some(a => a.device_id === d.id));
  openForm({ title: "Neuer Agent", narrow: true, fields: [
    { k: "name", label: "Name", ph: "z. B. web01 oder Server Praxis", max: 100 },
    { k: "platform", label: "System", type: "select", options: Object.entries(AG_PLAT) },
    { k: "device_id", label: "Gerät", type: "select", int: true,
      options: [["", "automatisch (Seriennummer/Rechnername, sonst neu anlegen)"]].concat(devs.map(d => [d.id, `${d.type_icon} ${d.name}`])) }],
    hint: "Der Agent findet sein Gerät beim ersten Bericht selbst über Seriennummer oder Rechnername – oder legt es neu an.",
    save: async (v) => {
      if (!v.name) throw new Error("Bitte einen Namen angeben");
      const r = await api("agents", { method: "POST", body: { name: v.name, platform: v.platform, device_id: v.device_id || null } });
      setTimeout(() => agSetup(v.name, r.token, r.urls, v.platform), 0);
      loadAgents();
    } });
}
$("agNew").onclick = () => agNew().catch(e => { $("agErr").textContent = e.message; });
$("agSave").onclick = async () => {
  $("agSetErr").textContent = "";
  try {
    await api("agents-settings", { method: "PATCH", body: { agent_url: $("agUrl").value.trim(), agent_url_lan: $("agUrlLan").value.trim(),
      stale_days: Number($("agStale").value) } });
    await loadAgents(); okMsg($("agSetErr"), "Gespeichert.");
  } catch (e) { $("agSetErr").textContent = e.message; }
};

// ---------- Übersicht: stille Agenten ----------
function agentHome(list) {
  const el = $("homeAgents");
  el.classList.toggle("hidden", !list.length);
  if (!list.length) return;
  el.innerHTML = `<span>🛰️ ${list.length === 1 ? "Ein Agent meldet" : `${list.length} Agenten melden`} sich nicht mehr:
    <b>${list.map(a => esc(a.device_name || a.name) + " (" + agAgo(a.last_report_at) + ")").join(", ")}</b></span><button>Ansehen</button>`;
  el.querySelector("button").onclick = () => {
    if (list.length === 1 && list[0].device_id) return go("devices", list[0].device_id);
    store.set("asec", "agenten"); showTab("admin");
  };
}
window.agentHome = agentHome;

// ---------- Gerät: „Vom Agent gemeldet“ ----------
async function agentPanel(d, reload) {
  let r;
  try { r = await api(`devices/${d.id}/agent`); } catch (e) { return; }
  const box = $("devAgent"), side = $("devAgentSide");
  if (!box || !r.agent) return;
  const a = r.agent, p = r.report;
  const adm = isAdmin();
  const tagRow = document.querySelector("#devDetail .dhead .row");
  if (tagRow) tagRow.insertAdjacentHTML("beforeend", `<span class="tag ${a.stale ? "bad" : a.disabled ? "off" : ""}" title="Letzter Bericht ${esc(a.last_report_local ? fmtDT(a.last_report_local) : "–")}">🛰️ Agent · ${a.disabled ? "gesperrt" : agAgo(a.last_report_at)}</span>`);
  side.classList.remove("hidden");
  side.innerHTML = `<h3>Agent</h3><dl class="kv"><dt>Name</dt><dd>${esc(a.name)}</dd><dt>System</dt><dd>${esc(a.platform_label || "–")}</dd>
    <dt>Letzter Bericht</dt><dd>${a.last_report_at ? (a.stale ? `<span class="tag bad">${agAgo(a.last_report_at)}</span>` : agAgo(a.last_report_at)) : "wartet"}</dd>
    ${a.last_contact_at ? `<dt>Nachgefragt</dt><dd title="Ab Agent 1.1 fragt der Agent stündlich nach; einen Bericht schickt er einmal am Tag, bei Änderungen oder auf Anforderung.">${agAgo(a.last_contact_at)}</dd>` : ""}
    ${a.agent_version ? `<dt>Version</dt><dd>${esc(a.agent_version)}</dd>` : ""}${adm && a.last_ip ? `<dt>Von Adresse</dt><dd class="mono">${esc(a.last_ip)}</dd>` : ""}</dl>
    ${a.stale ? `<p class="small err" style="margin:6px 0">Seit über ${agState.settings.stale_days || 3} Tagen kein Bericht – Gerät aus, Agent entfernt oder keine Verbindung?</p>` : ""}
    ${adm ? `<div class="row" style="gap:6px;margin-top:10px">${a.report_requested ? '<span class="tag warn" title="Kommt beim nächsten Nachfragen, spätestens in einer Stunde">Bericht angefordert</span>'
      : '<button class="mini" data-reqrep title="Der Agent schickt beim nächsten Nachfragen (spätestens in einer Stunde) einen frischen Bericht">↻ Bericht anfordern</button>'}
      <button class="mini" data-renew>Neuen Schlüssel erzeugen</button><button class="mini danger" data-toggle>${a.disabled ? "Entsperren" : "Agent sperren"}</button></div>` : ""}`;
  if (adm) {
    side.querySelector("[data-renew]").onclick = () => agRenew(a, reload);
    const rq = side.querySelector("[data-reqrep]");
    if (rq) rq.onclick = async () => { try { await api(`agents/${a.id}/request-report`, { method: "POST" }); reload(); } catch (e) { alert(e.message); } };
    side.querySelector("[data-toggle]").onclick = () => agToggle(a, reload);
  }
  if (!p) return;
  const kv = (pairs) => `<dl class="kv">${pairs.filter(([, v]) => v).map(([k, v, cls]) => `<dt>${k}</dt><dd${cls ? ` class="${cls}"` : ""}>${v}</dd>`).join("")}</dl>`;
  const hw = p.hardware || {}, u = p.updates || {}, os = p.os || {};
  const ips = (p.network.interfaces || []).flatMap(i => i.ipv4.concat(i.ipv6));
  // Windows-Schnellstart: eingeschaltet (power_on_time) ist später als der letzte echte Neustart (boot_time)
  const powerOn = p.power_on_time && p.boot_time && new Date(p.power_on_time) > new Date(p.boot_time) ? p.power_on_time : "";
  const since = powerOn || p.boot_time;
  const bootDays = since ? Math.floor((Date.now() - new Date(since).getTime()) / 86400000) : null;
  const sinceText = (ts) => { const h = Math.round((Date.now() - new Date(ts).getTime()) / 3600000);
    return h < 1 ? "weniger als 1 Stunde" : h < 24 ? `${h} Stunde${h === 1 ? "" : "n"}` : bootDays === 1 ? "1 Tag" : bootDays + " Tagen"; };
  const svc = p.services || [];
  const stopped = svc.filter(s => s.start === "auto" && (s.state === "stopped" || s.state === "failed"));
  const sub = (t) => `<span class="small" style="text-transform:none;letter-spacing:0;font-weight:400">${t}</span>`;
  box.innerHTML = `<div class="sect">🛰️ Vom Agent gemeldet ${sub(`${esc(fmtDT(a.last_report_local))}${adm && a.last_ip ? " · von " + esc(a.last_ip) : ""}${a.agent_version ? " · Agent " + esc(a.agent_version) : ""}`)}</div>
    <div class="fgrid">
      ${kv([["Rechnername", esc(p.hostname + (p.domain ? "." + p.domain : "")), "mono"], ["System", esc([os.name, os.build ? "Build " + os.build : "", os.arch].filter(Boolean).join(" · "))],
            ["CPU", esc([hw.cpu, hw.cores ? hw.cores + " Kerne" : ""].filter(Boolean).join(" · "))], ["Arbeitsspeicher", esc(ramText(hw.ram_mb))],
            ["Hardware", esc([hw.manufacturer, hw.model, hw.virtual ? "(virtuell)" : ""].filter(Boolean).join(" "))],
            ["Läuft seit", since ? (powerOn
              ? `${sinceText(powerOn)} (eingeschaltet ${esc(fmtDT(powerOn))}) <span class="muted small" title="Bei aktivem Windows-Schnellstart ist Herunterfahren eigentlich Ruhezustand – Updates, die einen Neustart brauchen, greifen erst nach „Neu starten“.">· letzter echter Neustart ${esc(fmtDT(p.boot_time))} (Schnellstart)</span>`
              : `${sinceText(since)} (Start ${esc(fmtDT(p.boot_time))})${p.fast_startup ? ' <span class="muted small">· Schnellstart an</span>' : ""}`) : ""],
            ["Angemeldet", esc(p.logged_in_user)]])}
      ${kv([["Updates", u.pending == null ? (u.error ? `<span class="muted">${esc(u.error)}</span>` : "") :
              (u.pending ? `<span class="tag warn">${u.pending} ausstehend</span>${u.security ? ` <span class="tag bad">${u.security} Sicherheit</span>` : ""}` : '<span class="tag okk">aktuell</span>')
              + (u.last_installed ? ` · zuletzt ${esc(deDate(u.last_installed.slice(0, 10)))}` : "")],
            ["Neustart nötig", u.reboot_required ? '<span class="tag warn">ja</span>' : ""],
            ["IP-Adressen", esc(ips.join(" · ")), "mono"],
            ["Gateway / DNS", esc([(p.network.gateway || []).join(", "), (p.network.dns || []).join(", ")].filter(Boolean).join(" · ")), "mono"]])}
    </div>
    ${u.items && u.items.length ? `<details class="more"><summary>${u.items.length === 1 ? "1 ausstehendes Update" : u.items.length + " ausstehende Updates"}</summary><ul class="small">${u.items.map(x => `<li>${esc(x)}</li>`).join("")}</ul></details>` : ""}
    <div class="sect">Datenträger</div>
    ${(p.disks || []).map(dk => {
      const used = dk.free_gb == null ? 0 : Math.round(100 * (1 - dk.free_gb / dk.total_gb));
      const free = dk.free_gb == null ? 1 : dk.free_gb / dk.total_gb;
      return `<div class="disk"><b class="mono" title="${esc([dk.label, dk.fs].filter(Boolean).join(" · "))}">${esc(dk.mount)}</b>
        <div class="prog ${free < 0.05 ? "bad" : free < 0.15 ? "warn" : ""}"><i style="width:${used}%"></i></div><span class="small">${gb(dk.free_gb)} frei von ${gb(dk.total_gb)}</span></div>`;
    }).join("") || '<p class="muted small" style="margin:0">–</p>'}
    <div class="sect">Dienste ${sub(svc.length ? `· ${svc.length} gemeldet${stopped.length ? `, <b class="err">${stopped.length} mit Autostart gestoppt</b>` : ""}` : "")}
      ${svc.length ? '<button class="mini" data-allsvc>alle anzeigen</button>' : ""}</div>
    <div data-svc></div>
    <div class="sect">Installierte Software ${sub(`· ${p.software.length} Einträge`)}
      ${p.software.length ? `<input data-swq placeholder="Suchen …" style="width:170px;text-transform:none;margin-left:auto"> <button class="mini" data-swcsv title="Als CSV">⤓ CSV</button>` : ""}</div>
    <div data-sw></div>`;
  let allSvc = false;
  const svcHtml = () => {
    const rows = allSvc ? svc : stopped;
    box.querySelector("[data-svc]").innerHTML = rows.length ? rows.map(s => `<div class="sv"><span>${esc(s.display || s.name)}${s.display && s.display !== s.name ? ` <small class="muted mono">${esc(s.name)}</small>` : ""}</span>
      <span>${s.start === "auto" ? "" : `<small class="muted">${s.start === "disabled" ? "deaktiviert" : s.start === "manual" ? "manuell" : ""}</small> `}<span class="tag ${s.state === "running" ? "okk" : s.state === "idle" ? "" : s.start === "auto" ? "bad" : ""}" ${s.state === "idle" ? 'title="Einmal-Dienst fertig, Bedingung trifft nicht zu oder wird bei Bedarf gestartet – kein Fehler"' : ""}>${s.state === "running" ? "läuft" : s.state === "idle" ? "beendet" : s.state === "failed" ? "Fehler" : s.state === "stopped" ? "gestoppt" : "?"}</span></span></div>`).join("")
      : `<p class="muted small" style="margin:0">${svc.length ? "Alle Dienste mit Autostart laufen." : "Keine Dienste gemeldet."}</p>`;
  };
  svcHtml();
  const allBtn = box.querySelector("[data-allsvc]");
  if (allBtn) allBtn.onclick = () => { allSvc = !allSvc; allBtn.textContent = allSvc ? "nur Auffälliges" : "alle anzeigen"; svcHtml(); };
  const swHtml = () => {
    const q = (box.querySelector("[data-swq]") || {}).value || "";
    const ql = q.toLowerCase();
    const rows = p.software.filter(s => !ql || (s.name + " " + s.publisher).toLowerCase().includes(ql));
    const shown = rows.slice(0, ql ? 300 : 15);
    box.querySelector("[data-sw]").innerHTML = rows.length ? `<div class="scroll"><table><thead><tr><th>Name</th><th>Version</th><th>Hersteller</th></tr></thead><tbody>
      ${shown.map(s => `<tr><td>${esc(s.name)}</td><td class="mono">${esc(s.version)}</td><td>${esc(s.publisher)}</td></tr>`).join("")}</tbody></table></div>
      ${rows.length > shown.length ? `<p class="muted small">… ${rows.length - shown.length} weitere – über die Suche finden oder als CSV laden.</p>` : ""}`
      : `<p class="muted small" style="margin:0">${q ? "Nichts gefunden." : "Keine Software gemeldet."}</p>`;
  };
  swHtml();
  const swq = box.querySelector("[data-swq]");
  if (swq) swq.oninput = debounce(swHtml, 150);
  const csvBtn = box.querySelector("[data-swcsv]");
  if (csvBtn) csvBtn.onclick = () => downloadFile(`api/v1/devices/${d.id}/agent/software.csv`, "software.csv");
}
window.agentPanel = agentPanel;
