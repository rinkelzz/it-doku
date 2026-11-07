"use strict";
// IT-Dokumentation: Übersicht, Geräte, Netzwerk, Lizenzen, Kontakte, Stammdaten, Suche.
// Baut auf app.js auf ($, api, esc, state, isAdmin, store, okMsg, deDate, fmtDT, initials, downloadFile, url, authHeaders).

const doc = { sites: [], types: [], site: 0, dev: { type: 0, status: "", q: "" }, net: 0, lic: { filter: "", q: "" },
              ct: { filter: "", q: "" }, suggest: null };
const go = (tab, sub) => { location.hash = tab + (sub ? "/" + sub : ""); };
const multiSite = () => doc.sites.length > 1;
const siteName = (id) => (doc.sites.find(s => s.id === id) || {}).name || "";
const typeOf = (id) => doc.types.find(t => t.id === id) || { icon: "📦", name: "?" };
const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const tel = (n) => n ? `<a class="tel" href="tel:${esc(n.replace(/[^\d+]/g, ""))}">${esc(n)}</a>` : "";
const fmtSize2 = (b) => b > 1048576 ? (b / 1048576).toFixed(1).replace(".", ",") + " MB" : Math.max(1, Math.round(b / 1024)) + " KB";
// „192.168.10.100 – .199“, wenn die ersten drei Teile gleich sind
const dhcpRange = (a, b) => {
  if (!a) return "–";
  const pa = a.split("."), pb = (b || "").split(".");
  return pa.length === 4 && pb.length === 4 && pa.slice(0, 3).join(".") === pb.slice(0, 3).join(".") ? `${a} – .${pb[3]}` : `${a} – ${b}`;
};
const monthYear = (iso) => iso ? `${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "";

function dueTag(iso, days, short) {
  if (!iso) return '<span class="muted">unbefristet</span>';
  if (days < 0) return `<span class="tag bad">${short ? deDate(iso) + " · " : ""}abgelaufen${short ? "" : ` seit ${-days} Tag${days === -1 ? "" : "en"}`}</span>`;
  const txt = days === 0 ? "heute" : `in ${days} Tag${days === 1 ? "" : "en"}`;
  return `<span class="tag ${days <= 60 ? "warn" : ""}">${short ? deDate(iso) + (days <= 90 ? " · " + txt : "") : txt}</span>`;
}

async function loadRef(force) {
  if (force || !doc.sites.length) [doc.sites, doc.types] = await Promise.all([api("sites"), api("device-types")]);
  const stored = Number(store.get("site") || 0);
  doc.site = doc.sites.some(s => s.id === stored) ? stored : 0;
  $$(".siteSel").forEach(sel => {
    sel.classList.toggle("hidden", !multiSite());
    const all = sel.id === "netSite" ? "" : `<option value="0">Alle Standorte (${doc.sites.length})</option>`;
    sel.innerHTML = all + doc.sites.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
    sel.value = String(sel.id === "netSite" ? (doc.site || (doc.sites[0] || {}).id || "") : doc.site);
  });
}
function setSite(id) { doc.site = Number(id) || 0; store.set("site", String(doc.site)); }

async function docShow(tab, sub) {
  await loadRef(false);
  $$(".admin").forEach(el => el.classList.toggle("hidden", !isAdmin()));
  if (tab === "home") return loadHomeDoc();
  if (tab === "devices") return sub ? showDevice(Number(sub)) : loadDevices();
  if (tab === "network") return sub === "scan" && isAdmin() ? loadScan() : loadNetwork();
  if (tab === "licenses") return sub ? showLicense(Number(sub)) : loadLicenses();
  if (tab === "contacts") return loadContacts(sub ? Number(sub) : 0);
  if (tab === "vault" && window.loadCredentials) return loadCredentials();
}
window.docShow = docShow;

// ---------- Dialog und Formulare ----------
function closeSheet() { $("sheet").classList.add("hidden"); $("sheet").innerHTML = ""; }
$("sheet").addEventListener("mousedown", (e) => { if (e.target === $("sheet")) closeSheet(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { if (!$("sheet").classList.contains("hidden")) closeSheet(); $$(".lightbox").forEach(l => l.remove()); }
});

function fieldHtml(f, v) {
  const val = v == null ? "" : v;
  const cls = f.span2 ? ' class="span2"' : "";
  const ph = f.ph ? ` placeholder="${esc(f.ph)}"` : "";
  const list = f.list ? ` list="dl_${f.list}"` : "";
  const mono = f.mono ? ' class="mono"' : "";
  if (f.type === "check") return `<label class="inline${f.span2 ? " span2" : ""}"><input type="checkbox" data-k="${f.k}" ${val ? "checked" : ""}> ${esc(f.label)}</label>`;
  if (f.type === "select") return `<label${cls}>${esc(f.label)} <select data-k="${f.k}">${f.options.map(([k, l]) =>
    `<option value="${esc(k)}" ${String(k) === String(val) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
  if (f.type === "textarea") return `<label${cls}>${esc(f.label)} <textarea data-k="${f.k}" rows="${f.rows || 3}"${ph}>${esc(val)}</textarea></label>`;
  const type = f.type || "text";
  return `<label${cls}>${esc(f.label)} <input data-k="${f.k}" type="${type}"${mono}${ph}${list} value="${esc(val)}"${f.max ? ` maxlength="${f.max}"` : ""}></label>`;
}
function readForm(root, fields) {
  const out = {};
  fields.forEach(f => {
    const el = root.querySelector(`[data-k="${f.k}"]`);
    if (!el) return;
    if (f.type === "check") out[f.k] = el.checked;
    else if (f.type === "number" || f.int) out[f.k] = el.value.trim() === "" ? null : Number(el.value);
    else if (f.type === "date") out[f.k] = el.value || null;
    else out[f.k] = el.value.trim();
  });
  return out;
}
// Öffnet ein Formular. save(values) → Promise; Rückgabe true = offen lassen (z. B. „Speichern & nächstes“)
function openForm({ title, fields, values = {}, save, del, extra = "", hint = "", next = false, narrow = false }) {
  $("sheet").innerHTML = `<div class="card ${narrow ? "narrow" : ""}">
    <div class="toolbar"><h2>${esc(title)}</h2><button data-x title="Schließen">✕</button></div>
    <div class="formgrid">${fields.map(f => fieldHtml(f, values[f.k])).join("")}</div>
    ${hint ? `<p class="muted small" style="margin:0">${hint}</p>` : ""}${extra}
    <div class="row"><button class="primary" data-save>Speichern</button>${next ? "<button data-next>Speichern &amp; nächstes</button>" : ""}
      <button data-x>Abbrechen</button>${del ? '<button class="danger" data-del style="margin-left:auto">Löschen</button>' : ""}</div>
    <div class="err" data-err></div></div>`;
  $("sheet").classList.remove("hidden");
  const card = $("sheet").firstElementChild;
  const err = card.querySelector("[data-err]");
  const first = card.querySelector("input:not([type=checkbox]), select, textarea");
  if (first) setTimeout(() => first.focus(), 0);
  $$("[data-x]", card).forEach(b => b.onclick = closeSheet);
  const run = async (keepOpen) => {
    err.textContent = "";
    $$("button", card).forEach(b => { b.disabled = true; });
    try {
      await save(readForm(card, fields), keepOpen);
      if (keepOpen) { fields.forEach(f => { if (f.clearNext) { const el = card.querySelector(`[data-k="${f.k}"]`); if (el) el.value = ""; } }); okMsg(err, "Gespeichert."); if (first) first.focus(); }
      else closeSheet();
    } catch (e) { err.textContent = e.message; }
    finally { $$("button", card).forEach(b => { b.disabled = false; }); }
  };
  card.querySelector("[data-save]").onclick = () => run(false);
  if (next) card.querySelector("[data-next]").onclick = () => run(true);
  card.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT" && e.target.type !== "checkbox") { e.preventDefault(); run(false); } });
  if (del) card.querySelector("[data-del]").onclick = async () => {
    if (!confirm(typeof del.confirm === "string" ? del.confirm : "Wirklich löschen?")) return;
    try { await del.run(); closeSheet(); } catch (e) { err.textContent = e.message; }
  };
  return card;
}
function datalists(sug) {
  return Object.entries(sug || {}).map(([k, vals]) => `<datalist id="dl_${k}">${vals.map(v => `<option value="${esc(v)}">`).join("")}</datalist>`).join("");
}
const siteOptions = (withNone) => (withNone ? [["", "–"]] : []).concat(doc.sites.map(s => [s.id, s.name]));

// ---------- Anhänge ----------
async function fetchBlob(id, inline) {
  const res = await fetch(url(`api/v1/attachments/${id}${inline ? "?inline=1" : ""}`), { credentials: "same-origin", headers: authHeaders() });
  if (!res.ok) throw new Error("Datei konnte nicht geladen werden");
  return res.blob();
}
async function uploadFile(file, ownerType, ownerId, role = "file") {
  if (file.size > 10 * 1024 * 1024) throw new Error("Die Datei ist zu groß (höchstens 10 MB)");
  const q = `owner_type=${ownerType}&owner_id=${ownerId}&role=${role}&name=${encodeURIComponent(file.name)}`;
  const res = await fetch(url("api/v1/attachments?" + q), { method: "POST", credentials: "same-origin",
    headers: authHeaders({ "Content-Type": "application/octet-stream" }), body: file });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error((data && typeof data.detail === "string") ? data.detail : "Hochladen fehlgeschlagen");
  return data;
}
function filesHtml(files) {
  if (!files.length) return '<p class="muted small" style="margin:0">Keine Anhänge.</p>';
  return `<div class="files">${files.map(f => `<span class="file" data-fid="${f.id}" data-fname="${esc(f.name)}" data-mime="${esc(f.mime)}">
    <span class="th ${f.mime === "application/pdf" ? "pdf" : ""}">${f.mime === "application/pdf" ? "PDF" : "🖼️"}</span>
    <span>${esc(f.name)}<small>${fmtSize2(f.size)} · ${fmtDT(f.created_at)}</small></span>
    ${isAdmin() ? `<button data-fdel="${f.id}" title="Anhang löschen">✕</button>` : ""}</span>`).join("")}</div>`;
}
function bindFiles(root, reload) {
  $$("[data-fid]", root).forEach(el => el.onclick = async (e) => {
    if (e.target.closest("[data-fdel]")) return;
    try {
      if (el.dataset.mime.startsWith("image/")) showImage(await fetchBlob(el.dataset.fid, true));
      else await downloadFile(`api/v1/attachments/${el.dataset.fid}`, el.dataset.fname);
    } catch (err) { alert(err.message); }
  });
  $$("[data-fdel]", root).forEach(b => b.onclick = async () => {
    if (!confirm("Anhang löschen?")) return;
    try { await api(`attachments/${b.dataset.fdel}`, { method: "DELETE" }); await reload(); } catch (e) { alert(e.message); }
  });
}
function showImage(blob) {
  const u = URL.createObjectURL(blob);
  const lb = document.createElement("div");
  lb.className = "lightbox"; lb.innerHTML = `<img src="${u}" alt="">`;
  lb.onclick = () => { lb.remove(); URL.revokeObjectURL(u); };
  document.body.appendChild(lb);
}
function uploadButton(id) {
  return isAdmin() ? `<label class="btn mini" style="display:inline-block">＋ Datei <input type="file" id="${id}" accept="image/png,image/jpeg,application/pdf" hidden multiple></label>` : "";
}
function bindUpload(id, ownerType, ownerId, errEl, reload) {
  const inp = $(id);
  if (!inp) return;
  inp.onchange = async () => {
    errEl.textContent = "";
    try { for (const f of inp.files) await uploadFile(f, ownerType, ownerId); await reload(); }
    catch (e) { errEl.textContent = e.message; }
  };
}
function historyHtml(h) {
  if (!h || !h.length) return '<p class="muted small" style="margin:0">Noch keine Einträge.</p>';
  return h.slice(0, 12).map(x => `<div class="hist"><div>${esc(x.label)}${x.label && x.text ? ": " : ""}${esc(x.text)}</div>
    <small>${fmtDT(x.ts_local)} · ${esc(x.actor)}</small></div>`).join("");
}

// ---------- Übersicht ----------
async function loadHomeDoc() {
  $("homeErr").textContent = "";
  const company = (state.branding && state.branding.company_name) || "";
  $("homeTitle").textContent = company || "Übersicht";
  let o;
  try { o = await api("overview" + (doc.site ? "?site_id=" + doc.site : "")); } catch (e) { $("homeErr").textContent = e.message; return; }
  $("homeStats").innerHTML = [
    ["devices", "Geräte", o.devices, o.devices_stock ? `davon ${o.devices_stock} im Lager` : "aktiv und im Lager"],
    ["licenses", "Lizenzen", o.licenses, o.licenses_due ? `<span class="warn">${o.licenses_due} ${o.licenses_due === 1 ? "läuft bald ab" : "laufen bald ab"} oder abgelaufen</span>` : "nichts fällig"],
    ["network", "Netze", o.networks, `${o.ips_used} IP-Adressen erfasst`],
    ["contacts", "Ansprechpartner", o.contacts, `${o.contacts_external} externe Dienstleister`],
  ].map(([t, l, n, s]) => `<div class="stat link" data-go="${t}"><small>${l}</small><b>${n}</b><small>${s}</small></div>`).join("");
  $$("#homeStats [data-go]").forEach(el => el.onclick = () => go(el.dataset.go));
  if (window.agentHome) agentHome(o.agents_stale || []);
  $("homeScan").classList.toggle("hidden", !o.scan_new);
  if (o.scan_new) {
    $("homeScan").innerHTML = `<span>🔍 Der Netzwerk-Scan hat <b>${o.scan_new} unbekannte${o.scan_new === 1 ? "s Gerät" : " Geräte"}</b> gefunden.</span><button class="primary">Ansehen</button>`;
    $("homeScan").querySelector("button").onclick = () => go("network", "scan");
  }
  $("homeDue").innerHTML = o.due.length ? o.due.map(d => `<div class="due click" data-kind="${d.kind}" data-id="${d.id}">
      <span class="ti">${d.kind === "license" ? "🔑" : esc(d.icon || "🖥️")}</span>
      <div>${esc(d.name)}<small>${esc(d.what)}${d.info ? " · " + esc(d.info) : ""}</small></div>${dueTag(d.date, d.days)}</div>`).join("")
    : '<p class="muted small">Nichts fällig – keine Lizenz und keine Garantie läuft in den nächsten 90 Tagen ab.</p>';
  $$("#homeDue [data-kind]").forEach(el => el.onclick = () => go(el.dataset.kind === "license" ? "licenses" : "devices", el.dataset.id));
  $("homeSos").innerHTML = o.emergency.length ? o.emergency.map(c => `<div class="mini-ct"><span class="av ${c.external ? "ext" : ""}">${esc(initials(c.name))}</span>
      <div>${esc(c.name)}<small>${esc([c.company, c.role].filter(Boolean).join(" · "))}</small></div>${tel(c.mobile || c.phone)}</div>`).join("")
    : `<p class="muted small">Noch niemand markiert. Unter <a href="#contacts">Kontakte</a> bei wichtigen Ansprechpartnern „Notfall“ anhaken.</p>`;
  $("homeSites").innerHTML = o.sites.map(s => `<div class="due click" data-site="${s.id}"><span class="ti">📍</span>
      <div>${esc(s.name)}<small>${esc([s.address, `${s.devices} Geräte`, `${s.networks} ${s.networks === 1 ? "Netz" : "Netze"}`].filter(Boolean).join(" · "))}</small></div>
      <button class="mini">Öffnen</button></div>`).join("");
  $$("#homeSites [data-site]").forEach(el => el.onclick = () => { setSite(el.dataset.site); go("network"); });
  $("homeRecent").innerHTML = o.recent.length ? o.recent.map(r => `<div class="chg"><span class="t">${r.icon}
      ${r.exists ? `<a data-kind="${r.kind}" data-id="${r.id}">${esc(r.name)}</a>` : `<b>${esc(r.name)}</b>`}
      <span class="muted">– ${esc(r.text || r.label.toLowerCase())}</span></span><span>${fmtDT(r.ts_local)} · ${esc(r.actor)}</span></div>`).join("")
    : '<p class="muted small">Noch keine Änderungen.</p>';
  $$("#homeRecent [data-kind]").forEach(a => a.onclick = () => openItem(a.dataset.kind, Number(a.dataset.id)));
}
function openItem(kind, id) {
  if (kind === "device") go("devices", id);
  else if (kind === "license") go("licenses", id);
  else if (kind === "contact") go("contacts", id);
  else if (kind === "network") { doc.net = id; go("network"); }
  else if (kind === "site") { setSite(id); go("network"); }
}
$("homeSite").onchange = () => { setSite($("homeSite").value); loadRef(false).then(loadHomeDoc); };

// ---------- Geräte ----------
const STATUS = { active: "aktiv", stock: "im Lager", retired: "ausgemustert" };
async function loadDevices() {
  $("devListView").classList.remove("hidden"); $("devDetail").classList.add("hidden");
  $("devErr").textContent = "";
  const p = new URLSearchParams();
  if (doc.site) p.set("site_id", doc.site);
  if (doc.dev.type) p.set("type_id", doc.dev.type);
  if (doc.dev.status) p.set("status", doc.dev.status);
  if (doc.dev.q) p.set("q", doc.dev.q);
  let rows, counts;
  try { [rows, counts] = await Promise.all([api("devices?" + p), api("devices/counts" + (doc.site ? "?site_id=" + doc.site : ""))]); }
  catch (e) { $("devErr").textContent = e.message; return; }
  const n = (o, k) => o[k] || 0;
  const activeCount = Object.entries(counts.status).filter(([k]) => k !== "retired").reduce((a, [, v]) => a + v, 0);
  const typeName = doc.dev.type ? typeOf(doc.dev.type).name : "";
  let side = "";
  if (multiSite()) side += `<h4>Standort</h4><a data-site="0" class="${doc.site ? "" : "on"}">Alle<span class="n">${Object.values(counts.site).reduce((a, b) => a + b, 0)}</span></a>` +
    doc.sites.map(s => `<a data-site="${s.id}" class="${doc.site === s.id ? "on" : ""}">${esc(s.name)}<span class="n">${n(counts.site, s.id)}</span></a>`).join("");
  side += `<h4>Typ</h4><a data-type="0" class="${doc.dev.type ? "" : "on"}">Alle Typen<span class="n">${activeCount}</span></a>` +
    doc.types.filter(t => n(counts.type, t.id) || doc.dev.type === t.id).map(t => `<a data-type="${t.id}" class="${doc.dev.type === t.id ? "on" : ""}">
      <span class="ti sm">${esc(t.icon)}</span>${esc(t.name)}<span class="n">${n(counts.type, t.id)}</span></a>`).join("");
  side += `<h4>Status</h4><a data-status="" class="${doc.dev.status ? "" : "on"}">aktiv + Lager<span class="n">${activeCount}</span></a>` +
    Object.entries(STATUS).map(([k, l]) => `<a data-status="${k}" class="${doc.dev.status === k ? "on" : ""}">${l}<span class="n">${n(counts.status, k)}</span></a>`).join("");
  $("devSide").innerHTML = side;
  $$("#devSide [data-site]").forEach(a => a.onclick = () => { setSite(a.dataset.site); loadRef(false).then(loadDevices); });
  $$("#devSide [data-type]").forEach(a => a.onclick = () => { doc.dev.type = Number(a.dataset.type); loadDevices(); });
  $$("#devSide [data-status]").forEach(a => a.onclick = () => { doc.dev.status = a.dataset.status; loadDevices(); });
  $("devMobileSel").innerHTML = `<option value="0">Alle Typen · ${activeCount}</option>` +
    doc.types.filter(t => n(counts.type, t.id)).map(t => `<option value="${t.id}">${esc(t.icon)} ${esc(t.name)} · ${n(counts.type, t.id)}</option>`).join("");
  $("devMobileSel").value = String(doc.dev.type);
  $("devTitle").innerHTML = `${esc(typeName || "Geräte")} <span class="muted small" style="font-weight:400">· ${rows.length}${doc.dev.status ? " " + STATUS[doc.dev.status] : ""}</span>`;
  const warr = (d) => d.warranty_until ? `<span class="tag ${d.warranty_days < 0 ? "" : d.warranty_days <= 90 ? "warn" : ""}">${monthYear(d.warranty_until)}</span>` : '<span class="muted">–</span>';
  $("devTable").innerHTML = `<thead><tr><th>Gerät</th><th>IP-Adresse</th><th>Raum</th><th>Benutzt von</th><th>Seriennummer</th><th>Garantie</th></tr></thead><tbody>` +
    (rows.map(d => `<tr data-id="${d.id}"><td data-sort="${esc(d.name)}"><div class="nm"><span class="ti">${esc(d.type_icon)}</span><div><b class="${isPlaceholder(d.name) ? "unnamed" : ""}">${esc(d.name)}</b>${(d.urls || []).slice(0, 3).map(u => webLink(u.url, "↗", "weblnk", u.label || u.url)).join("")}
      <small>${esc([[d.manufacturer, d.model].filter(Boolean).join(" "), d.os].filter(Boolean).join(" · "))}${d.status !== "active" ? ` · <i>${esc(d.status_label)}</i>` : ""}</small></div></div></td>
      <td class="mono">${esc(d.ips || "–")}</td><td>${esc(d.room || "–")}${multiSite() && !doc.site && d.site_name ? `<small class="muted" style="display:block">${esc(d.site_name)}</small>` : ""}</td><td>${esc(d.used_by || "–")}</td>
      <td class="mono">${esc(d.serial || "–")}</td><td data-sort="${esc(d.warranty_until || "")}">${warr(d)}</td></tr>`).join("") ||
      `<tr><td colspan="7" class="emptyrow">${doc.dev.q || doc.dev.type ? "Keine Geräte für diese Auswahl." : "Noch keine Geräte erfasst." + (isAdmin() ? " Mit „＋ Gerät“ geht es los." : "")}</td></tr>`) + "</tbody>";
  sortTable($("devTable"));
  $$("#devTable [data-id]").forEach(tr => tr.onclick = () => go("devices", tr.dataset.id));
  $("devCards").innerHTML = rows.map(d => `<div class="mcard" data-id="${d.id}"><span class="ti">${esc(d.type_icon)}</span>
    <div><b>${esc(d.name)}</b><small>${esc([d.ips, d.room].filter(Boolean).join(" · ") || d.model || "")}</small></div>
    ${d.warranty_until && d.warranty_days >= 0 && d.warranty_days <= 90 ? `<span class="tag warn">Garantie ${monthYear(d.warranty_until)}</span>` : `<span class="tag">${esc(d.type_name)}</span>`}</div>`).join("") ||
    '<p class="muted">Keine Geräte.</p>';
  $$("#devCards [data-id]").forEach(el => el.onclick = () => go("devices", el.dataset.id));
}
$("devMobileSel").onchange = () => { doc.dev.type = Number($("devMobileSel").value); loadDevices(); };
$("devQ").oninput = debounce(() => { doc.dev.q = $("devQ").value.trim(); loadDevices(); });
$("devCsv").onclick = () => downloadFile("api/v1/devices/export.csv?" + new URLSearchParams({ ...(doc.site ? { site_id: doc.site } : {}),
  ...(doc.dev.status ? { status: doc.dev.status } : {}) }), "geraete.csv").catch(e => { $("devErr").textContent = e.message; });
$("devNew").onclick = () => deviceForm(null);

async function deviceForm(d) {
  if (!doc.suggest) doc.suggest = await api("devices/suggest").catch(() => ({}));
  const fields = [
    { k: "name", label: "Name", max: 100, clearNext: true },
    { k: "type_id", label: "Typ", type: "select", int: true, options: doc.types.map(t => [t.id, `${t.icon} ${t.name}`]) },
    ...(multiSite() ? [{ k: "site_id", label: "Standort", type: "select", int: true, options: siteOptions(true) }] : []),
    { k: "room", label: "Raum", list: "room" },
    { k: "manufacturer", label: "Hersteller", list: "manufacturer" },
    { k: "model", label: "Modell", list: "model" },
    { k: "serial", label: "Seriennummer", mono: true, clearNext: true },
    { k: "inventory_no", label: "Inventar-Nr.", clearNext: true },
    { k: "os", label: "Betriebssystem", list: "os" },
    { k: "used_by", label: "Benutzt von", list: "used_by", ph: "Person oder Rolle" },
    { k: "purchased_on", label: "Gekauft am", type: "date" },
    { k: "purchased_from", label: "Gekauft bei", list: "purchased_from" },
    { k: "warranty_until", label: "Garantie bis", type: "date" },
    { k: "status", label: "Status", type: "select", options: Object.entries(STATUS) },
    ...(d ? [] : [{ k: "ip", label: "IP-Adresse (optional)", mono: true, ph: "z. B. 192.168.10.33", clearNext: true }]),
    { k: "notes", label: "Notizen", type: "textarea", span2: true, rows: 4 },
  ];
  const values = d ? { ...d } : { type_id: doc.dev.type || (doc.types[0] || {}).id, site_id: doc.site || "", status: "active" };
  openForm({
    title: d ? `${d.name} bearbeiten` : "Neues Gerät", fields, values, next: !d,
    extra: datalists(doc.suggest),
    hint: d ? "" : "Hersteller, Modell usw. schlagen schon erfasste Werte vor. Weitere IP-Adressen, Lizenzen und Anhänge nach dem Speichern.",
    save: async (v, keepOpen) => {
      if (v.ip === "") delete v.ip;
      const r = d ? await api(`devices/${d.id}`, { method: "PATCH", body: v }) : await api("devices", { method: "POST", body: v });
      doc.suggest = null; await loadRef(true);
      if (d) await showDevice(d.id);
      else if (keepOpen) loadDevices();
      else go("devices", r.id);
    },
    del: d && { confirm: `„${d.name}“ endgültig löschen – mit IP-Adressen und Anhängen?\n\nFür Altgeräte besser Status „ausgemustert“ wählen, dann bleibt die Doku erhalten.`,
      run: async () => { await api(`devices/${d.id}`, { method: "DELETE" }); await loadRef(true); go("devices"); } },
  });
}

async function showDevice(id) {
  $("devListView").classList.add("hidden");
  const box = $("devDetail");
  box.classList.remove("hidden");
  let d;
  try { d = await api(`devices/${id}`); } catch (e) { box.innerHTML = `<div class="card err">${esc(e.message)}</div>`; return; }
  const kv = (pairs) => `<dl class="kv">${pairs.filter(([, v]) => v).map(([k, v, cls]) => `<dt>${k}</dt><dd${cls ? ` class="${cls}"` : ""}>${v}</dd>`).join("")}</dl>`;
  const adm = isAdmin();
  box.innerHTML = `<div class="crumbs"><a data-back>Geräte</a> › ${esc(d.type_name)} › ${esc(d.name)}</div>
  <div class="httpwarn hidden" id="devDup" style="margin:12px 0 0;display:flex;gap:12px;align-items:center;justify-content:space-between"></div>
  <div class="tgrid" style="margin-top:12px">
    <section class="card">
      <div class="dhead"><span class="ti">${esc(d.type_icon)}</span><div><h2>${esc(d.name)}</h2>
        <div class="row"><span class="tag ${d.status === "active" ? "okk" : ""}">${esc(d.status_label)}</span><span class="tag">${esc(d.type_name)}</span>
          ${d.site_name || d.room ? `<span class="tag">📍 ${esc([multiSite() ? d.site_name : "", d.room].filter(Boolean).join(" · "))}</span>` : ""}</div></div>
        <div class="row">${d.urls.slice(0, 3).map(u => webLink(u.url, `↗ ${esc(u.label || urlHost(u.url))}`, "linkbtn")).join("")}${adm ? '<button data-merge title="Doppelten Eintrag in dieses Gerät übernehmen">⇄</button><button data-edit>Bearbeiten</button>' : ""}</div></div>
      <div class="fgrid">
        ${kv([["Hersteller", esc(d.manufacturer)], ["Modell", esc(d.model)], ["Seriennummer", esc(d.serial), "mono"], ["Inventar-Nr.", esc(d.inventory_no), "mono"]])}
        ${kv([["Betriebssystem", esc(d.os)], ["Benutzt von", esc(d.used_by)],
              ["Gekauft", esc([deDate(d.purchased_on), d.purchased_from].filter(Boolean).join(" · "))],
              ["Garantie bis", d.warranty_until ? deDate(d.warranty_until) + (d.warranty_days != null && d.warranty_days <= 90 ? " " + dueTag(d.warranty_until, d.warranty_days) : "") : ""]])}
      </div>
      <div class="sect">Netzwerk ${adm ? "<button class=\"mini\" data-addip>＋ IP-Adresse</button>" : ""}</div>
      ${d.ip_list.length ? `<div class="scroll"><table class="${adm ? "list" : ""}"><thead><tr><th>IP-Adresse</th><th>Netz</th><th>MAC</th><th>Hostname</th><th>Art</th></tr></thead><tbody>
        ${d.ip_list.map(i => `<tr data-ip="${i.id}"><td class="mono">${esc(i.ip)}</td><td>${esc(i.network_name || "–")}</td><td class="mono">${esc(i.mac || "–")}</td>
          <td class="mono">${esc(i.hostname || "–")}</td><td>${esc(i.kind_label)}</td></tr>`).join("")}</tbody></table></div>`
        : '<p class="muted small" style="margin:0">Keine IP-Adresse erfasst.</p>'}
      <div class="sect">Web-Oberflächen ${adm ? '<button class="mini" data-addurl>＋ Web-Adresse</button>' : ""}</div>
      ${d.urls.map(u => `<div class="weburl"><span>${webLink(u.url, esc(u.label || urlHost(u.url)))}<small class="mono muted">${esc(u.url)}</small></span>
        ${adm ? `<span class="row" style="gap:4px"><button class="mini" data-editurl="${u.id}" title="Bearbeiten">✎</button><button class="mini" data-delurl="${u.id}" title="Entfernen">✕</button></span>` : ""}</div>`).join("") ||
        (d.url_suggestions.length || !adm ? "" : '<p class="muted small" style="margin:0">Keine Web-Adresse – z. B. Admin-Oberfläche oder ein Dienst im Container.</p>')}
      ${adm && d.url_suggestions.length ? `<p class="small" style="margin:6px 0 0"><span class="muted">Gefunden:</span> ${d.url_suggestions.map((u, i) =>
        `<button class="mini" data-suggurl="${i}" title="Als Web-Adresse übernehmen">＋ ${esc(u)}</button>`).join(" ")}</p>` : ""}
      ${!adm && !d.urls.length ? '<p class="muted small" style="margin:0">–</p>' : ""}
      <div class="sect">Notizen</div>
      ${d.notes ? `<div class="note">${esc(d.notes)}</div>` : '<p class="muted small" style="margin:0">–</p>'}
      <div class="sect">Anhänge ${uploadButton("devFile")}</div>
      <div id="devFiles">${filesHtml(d.files)}</div><div class="err" id="devFileErr"></div>
      <div id="devAgent"></div>
    </section>
    <aside class="panel">
      ${adm ? '<div class="card" id="devCreds"></div>' : ""}
      <div class="card hidden" id="devAgentSide"></div>
      <div class="card"><h3>Lizenzen</h3>
        ${d.licenses.map(l => `<div class="due"><span class="ti">🔑</span><div><a href="#licenses/${l.id}" style="color:var(--text);text-decoration:none">${esc(l.name)}</a>
          <small>${esc([l.term || l.kind_label, l.seats != null ? `${l.used} von ${l.seats}` : ""].filter(Boolean).join(" · "))}</small></div>
          <span class="row" style="gap:4px;flex-wrap:nowrap">${l.days != null && l.days < 0 ? '<span class="tag bad">abgelaufen</span>' : l.days != null && l.days <= 60 ? dueTag(l.expires_on, l.days) : ""}
          ${adm ? `<button class="x" data-unlic="${l.id}" title="Zuordnung entfernen">✕</button>` : ""}</span></div>`).join("") || '<p class="muted small" style="margin:0">Keine zugeordnet.</p>'}
        ${adm ? '<button class="mini" data-addlic style="margin-top:8px">＋ Lizenz zuordnen</button>' : ""}</div>
      <div class="card"><h3>Verbunden mit</h3>
        ${d.links.map(k => `<div class="due"><span class="ti">${esc(k.icon)}</span><div><a href="#devices/${k.device_id}" style="color:var(--text);text-decoration:none">${esc(k.name)}</a>
          ${k.note ? `<small>${esc(k.note)}</small>` : ""}</div>${adm ? `<button class="x" data-unlink="${k.id}" title="Verbindung entfernen">✕</button>` : ""}</div>`).join("") ||
          '<p class="muted small" style="margin:0">Keine Verbindungen.</p>'}
        ${adm ? '<button class="mini" data-addlink style="margin-top:8px">＋ Verbindung</button>' : ""}</div>
      <div class="card"><h3>Verlauf</h3>${historyHtml(d.history)}</div>
    </aside>
  </div>`;
  const reload = () => showDevice(id);
  box.querySelector("[data-back]").onclick = () => go("devices");
  if (window.agentPanel) agentPanel(d, reload);
  if (adm) {
    box.querySelector("[data-merge]").onclick = () => mergeForm(d, [], reload);
    api(`devices/${id}/duplicates`).then(dups => {
      const el = $("devDup");
      if (!el || !dups.length) return;
      el.classList.remove("hidden");
      el.innerHTML = `<span>Möglicherweise doppelt erfasst: ${dups.map(x => `<b>${esc(x.icon)} ${esc(x.name)}</b> <span class="muted">(${esc(x.reason)})</span>`).join(", ")}</span>
        <button>Zusammenführen …</button>`;
      el.querySelector("button").onclick = () => mergeForm(d, dups, reload);
    }).catch(() => {});
  }
  if (!adm) { bindFiles(box, reload); return; }
  if (window.credPanel) credPanel($("devCreds"), "device", d.id);
  box.querySelector("[data-edit]").onclick = () => deviceForm(d);
  box.querySelector("[data-addip]").onclick = () => ipForm(null, { device_id: d.id }, reload);
  $$("[data-ip]", box).forEach(tr => tr.onclick = () => ipForm(d.ip_list.find(i => i.id === Number(tr.dataset.ip)), {}, reload));
  bindFiles(box, reload);
  bindUpload("devFile", "device", d.id, $("devFileErr"), reload);
  $$("[data-unlic]", box).forEach(b => b.onclick = async () => {
    try { await api(`licenses/${b.dataset.unlic}/devices/${d.id}`, { method: "DELETE" }); reload(); } catch (e) { alert(e.message); }
  });
  $$("[data-unlink]", box).forEach(b => b.onclick = async () => {
    if (!confirm("Verbindung entfernen?")) return;
    try { await api(`device-links/${b.dataset.unlink}`, { method: "DELETE" }); reload(); } catch (e) { alert(e.message); }
  });
  box.querySelector("[data-addlic]").onclick = async () => {
    const lics = (await api("licenses")).filter(l => !d.licenses.some(x => x.id === l.id));
    if (!lics.length) { alert("Es gibt keine (weitere) Lizenz. Lege sie zuerst unter „Lizenzen“ an."); return; }
    openForm({ title: "Lizenz zuordnen", narrow: true, fields: [{ k: "license_id", label: "Lizenz", type: "select", int: true,
      options: lics.map(l => [l.id, `${l.name}${l.seats != null ? ` (${l.used}/${l.seats})` : ""}`]) }],
      save: async (v) => { await api(`licenses/${v.license_id}/devices`, { method: "POST", body: { device_id: d.id } }); reload(); } });
  };
  const urlForm = (u) => openForm({ title: u ? "Web-Adresse bearbeiten" : "Neue Web-Adresse", narrow: true, fields: [
      { k: "label", label: "Bezeichnung", ph: "z. B. Vaultwarden, Admin-Oberfläche", max: 100 },
      { k: "url", label: "Adresse", mono: true, ph: "https://vault.kunde.de", max: 500 }],
    values: u ? { ...u } : { url: d.url_suggestions[0] || "" },
    hint: "http:// oder https://; ohne Angabe wird https:// ergänzt.",
    save: async (v) => {
      await api(u ? `device-urls/${u.id}` : `devices/${id}/urls`, { method: u ? "PATCH" : "POST", body: { label: v.label, url: v.url } });
      reload();
    } });
  if (adm) {
    box.querySelector("[data-addurl]").onclick = () => urlForm(null);
    $$("[data-editurl]", box).forEach(b => b.onclick = () => urlForm(d.urls.find(u => u.id === Number(b.dataset.editurl))));
    $$("[data-delurl]", box).forEach(b => b.onclick = async () => {
      const u = d.urls.find(x => x.id === Number(b.dataset.delurl));
      if (!confirm(`Web-Adresse „${u.label || u.url}“ entfernen?`)) return;
      try { await api(`device-urls/${u.id}`, { method: "DELETE" }); reload(); } catch (e) { alert(e.message); }
    });
    $$("[data-suggurl]", box).forEach(b => b.onclick = async () => {
      const url = d.url_suggestions[Number(b.dataset.suggurl)];
      try { await api(`devices/${id}/urls`, { method: "POST", body: { label: "", url } }); reload(); } catch (e) { alert(e.message); }
    });
  }
  box.querySelector("[data-addlink]").onclick = async () => {
    const devs = (await api("devices?status=all")).filter(x => x.id !== d.id && !d.links.some(k => k.device_id === x.id));
    if (!devs.length) { alert("Es gibt kein weiteres Gerät."); return; }
    openForm({ title: `${d.name} verbinden mit …`, narrow: true, fields: [
      { k: "device_id", label: "Gerät", type: "select", int: true, options: devs.map(x => [x.id, `${x.type_icon} ${x.name}`]) },
      { k: "note", label: "Hinweis (optional)", ph: "z. B. Port 7, Standarddrucker", max: 100 }],
      save: async (v) => { await api(`devices/${d.id}/links`, { method: "POST", body: v }); reload(); } });
  };
}

// ---------- IP-Formular (Gerät und Netzwerk) ----------
async function ipForm(ip, preset, reload) {
  const [nets, devs] = await Promise.all([api("networks"), api("devices?status=all")]);
  const fields = [
    { k: "ip", label: "IP-Adresse", mono: true, ph: "192.168.10.33" },
    { k: "network_id", label: "Netz", type: "select", int: true, options: [["", "automatisch (passendes Netz)"]].concat(nets.map(n => [n.id, `${n.name}${n.cidr ? " · " + n.cidr : ""}`])) },
    { k: "device_id", label: "Gerät", type: "select", int: true, options: [["", "– kein Gerät –"]].concat(devs.map(x => [x.id, `${x.type_icon} ${x.name}`])) },
    { k: "kind", label: "Art", type: "select", options: [["static", "fest"], ["reservation", "DHCP-Reservierung"], ["dhcp", "DHCP"]] },
    { k: "mac", label: "MAC-Adresse", mono: true, ph: "8C:04:BA:3E:11:F2" },
    { k: "hostname", label: "Hostname", mono: true },
    { k: "notes", label: "Hinweis", span2: true, max: 500 },
  ];
  openForm({ title: ip ? `IP ${ip.ip} bearbeiten` : "Neue IP-Adresse", fields, narrow: false,
    values: ip ? { ...ip } : { kind: "static", ...preset },
    save: async (v) => {
      if (v.network_id === null) delete v.network_id;
      if (ip) await api(`ips/${ip.id}`, { method: "PATCH", body: { ...v, network_id: v.network_id || null } });
      else await api("ips", { method: "POST", body: v });
      await reload();
    },
    del: ip && { confirm: `IP ${ip.ip} löschen?`, run: async () => { await api(`ips/${ip.id}`, { method: "DELETE" }); await reload(); } } });
}

// ---------- Netzwerk ----------
async function loadNetwork() {
  $("netView").classList.remove("hidden"); $("scanView").classList.add("hidden");
  $("netErr").textContent = "";
  const siteId = doc.site || (doc.sites[0] || {}).id;
  const site = doc.sites.find(s => s.id === siteId) || {};
  $("netSite").value = String(siteId || "");
  $("netTitle").textContent = "Netze" + (multiSite() ? " · " + (site.name || "") : "");
  let nets;
  try { nets = await api("networks" + (multiSite() ? "?site_id=" + siteId : "")); } catch (e) { $("netErr").textContent = e.message; return; }
  if (!nets.some(n => n.id === doc.net)) doc.net = (nets[0] || {}).id || 0;
  $("netGrid").innerHTML = nets.map(n => `<div class="net ${n.id === doc.net ? "on" : ""}" data-net="${n.id}">
      <h3><span>${esc(n.name)}</span><span class="row" style="gap:6px">${n.scan ? `<span class="tag" title="${n.scan_agent_name ? `wird vor Ort vom Agent „${esc(n.scan_agent_name)}“ gescannt` : "wird beim Netzwerk-Scan geprüft"}">🔍${n.scan_agent_name ? " 🛰️ " + esc(n.scan_agent_name) : ""}</span>` : ""}${n.vlan != null ? `<span class="tag">VLAN ${n.vlan}</span>` : ""}
        ${isAdmin() ? `<button class="mini" data-netedit="${n.id}" title="Netz bearbeiten">✎</button>` : ""}</span></h3>
      <dl class="kv"><dt>Netz</dt><dd class="mono">${esc(n.cidr || "–")}</dd><dt>Gateway</dt><dd class="mono">${esc(n.gateway || "–")}</dd>
        <dt>DHCP</dt><dd class="mono">${esc(dhcpRange(n.dhcp_from, n.dhcp_to))}</dd><dt>DNS</dt><dd class="mono">${esc(n.dns || "–")}</dd></dl>
      ${n.size ? `<div class="bar"><i style="width:${Math.min(100, Math.max(1, Math.round(n.used / n.size * 100)))}%"></i></div><small class="muted">${n.used} von ${n.size} erfasst</small>` : `<small class="muted">${n.used} IP-Adressen</small>`}
      ${n.notes ? `<p class="muted small" style="margin:6px 0 0;white-space:pre-wrap">${esc(n.notes)}</p>` : ""}</div>`).join("") ||
    `<p class="muted">Noch kein Netz erfasst.${isAdmin() ? " Mit „＋ Netz“ z. B. das Praxis-LAN anlegen (192.168.10.0/24)." : ""}</p>`;
  $$("#netGrid [data-net]").forEach(el => el.onclick = (e) => {
    if (e.target.closest("[data-netedit]")) return;
    doc.net = Number(el.dataset.net); loadNetwork();
  });
  $$("#netGrid [data-netedit]").forEach(b => b.onclick = () => networkForm(nets.find(n => n.id === Number(b.dataset.netedit))));
  await Promise.all([loadIps(nets.find(n => n.id === doc.net)), showDiagram(site), showIsp(site),
    isAdmin() && window.credPanel && site.id ? credPanel($("siteCreds"), "site", site.id) : null]);
}
async function loadIps(net) {
  $("ipErr").textContent = "";
  $("ipTitle").textContent = net ? `IP-Adressen · ${net.name}` : "IP-Adressen";
  $("ipNew").disabled = !net;
  if (!net) { $("ipTable").innerHTML = ""; return; }
  let rows;
  try { rows = await api(`ips?network_id=${net.id}${$("ipFree").checked ? "&free=1" : ""}`); } catch (e) { $("ipErr").textContent = e.message; return; }
  const q = $("ipQ").value.trim().toLowerCase();
  if (q) rows = rows.filter(r => [r.ip, r.device_name, r.hostname, r.mac, r.notes].some(x => (x || "").toLowerCase().includes(q)));
  const scanned = !!net.first_scan_at;
  $("ipTable").innerHTML = `<thead><tr><th>IP</th><th>Gerät</th><th>Hostname</th><th>MAC</th><th>Hinweis</th>${scanned ? "<th>zuletzt online</th>" : ""}</tr></thead><tbody>` +
    (rows.map(r => r.free ? `<tr class="free" data-free="${esc(r.ip)}"><td class="mono">${esc(r.ip)}</td><td colspan="${scanned ? 5 : 4}">frei</td></tr>`
      : `<tr data-ip="${r.id}"><td class="mono">${scanned ? seenDot(r.last_seen) : ""}${esc(r.ip)}</td><td data-sort="${esc(r.device_name || "")}">${r.device_id ? `${esc(r.device_icon)} <span class="${isPlaceholder(r.device_name) ? "unnamed" : ""}">${esc(r.device_name)}</span>${isAdmin()
          ? `<button class="mini renm${isPlaceholder(r.device_name) ? " show" : ""}" data-ren="${r.device_id}" title="Gerät umbenennen">✎</button>` : ""}` : '<span class="muted">–</span>'}</td>
        <td class="mono" data-sort="${esc(r.hostname || "")}">${ipWebCell(r)}</td><td class="mono">${esc(r.mac || "–")}</td><td class="wrap small">${esc([r.kind !== "static" ? r.kind_label : "", r.notes].filter(Boolean).join(" · "))}</td>${scanned ? `<td class="small" data-sort="${esc(r.last_seen || "")}">${seenText(r.last_seen)}</td>` : ""}</tr>`).join("") +
     (net.dhcp_from && !q ? `<tr class="free"><td class="mono">${esc(dhcpRange(net.dhcp_from, net.dhcp_to))}</td><td colspan="4">DHCP-Bereich</td></tr>` : "") ||
     '<tr><td colspan="5" class="emptyrow">Keine IP-Adressen.</td></tr>') + "</tbody>";
  sortTable($("ipTable"));
  const reload = () => loadNetwork();
  $$("#ipTable [data-ren]").forEach(b => b.onclick = (e) => {
    e.stopPropagation();
    const r = rows.find(x => x.device_id === Number(b.dataset.ren));
    renameDevice(r.device_id, r.device_name, r.hostname, reload).catch(err => { $("ipErr").textContent = err.message; });
  });
  $$("#ipTable [data-ip]").forEach(tr => tr.onclick = () => {
    const r = rows.find(x => x.id === Number(tr.dataset.ip));
    if (isAdmin()) ipForm(r, {}, reload); else if (r.device_id) go("devices", r.device_id);
  });
  $$("#ipTable [data-free]").forEach(tr => tr.onclick = () => { if (isAdmin()) ipForm(null, { ip: tr.dataset.free, network_id: net.id }, reload); });
  $("ipNew").onclick = () => ipForm(null, { network_id: net.id }, reload);
}
$("ipFree").onchange = () => loadNetwork();
$("ipQ").oninput = debounce(() => loadNetwork());
$("netSite").onchange = () => { setSite($("netSite").value); doc.net = 0; loadRef(false).then(loadNetwork); };
$("netNew").onclick = () => networkForm(null);

async function networkForm(n) {
  const scanAgents = isAdmin() ? await api("agents").then(r => r.agents.filter(a => a.platform !== "windows")).catch(() => []) : [];
  const siteId = doc.site || (doc.sites[0] || {}).id;
  const fields = [
    { k: "name", label: "Name", ph: "z. B. Praxis-LAN", max: 100 },
    { k: "vlan", label: "VLAN", type: "number" },
    { k: "cidr", label: "Netz (CIDR)", mono: true, ph: "192.168.10.0/24" },
    { k: "gateway", label: "Gateway", mono: true, ph: "192.168.10.1" },
    { k: "dhcp_from", label: "DHCP von", mono: true, ph: "192.168.10.100" },
    { k: "dhcp_to", label: "DHCP bis", mono: true, ph: "192.168.10.199" },
    { k: "dns", label: "DNS", mono: true, ph: "192.168.10.1" },
    ...(multiSite() ? [{ k: "site_id", label: "Standort", type: "select", int: true, options: siteOptions(false) }] : []),
    { k: "notes", label: "Notizen", type: "textarea", span2: true, ph: "z. B. Gäste-WLAN isoliert, WLAN-Name, Firewall-Regeln" },
    { k: "scan", label: "beim Netzwerk-Scan berücksichtigen (IPv4, höchstens /22)", type: "check", span2: true },
    { k: "scan_agent_id", label: "Gescannt von", type: "select", int: true, span2: true,
      options: [["", "dieser NAS (Netz ist von hier erreichbar)"]].concat(scanAgents.map(a => [a.id, `🛰️ Agent „${a.name}“ vor Ort${a.os_name ? " · " + a.os_name : ""}`])) },
  ];
  openForm({ title: n ? `${n.name} bearbeiten` : "Neues Netz", fields, values: n ? { ...n } : { site_id: siteId },
    hint: "Bereits erfasste IP-Adressen, die ins Netz passen, werden beim Anlegen automatisch zugeordnet.",
    save: async (v) => {
      if (!multiSite()) v.site_id = siteId;
      const r = n ? await api(`networks/${n.id}`, { method: "PATCH", body: v }) : await api("networks", { method: "POST", body: v });
      doc.net = r.id; await loadRef(true); await loadNetwork();
    },
    del: n && { confirm: `Netz „${n.name}“ löschen – mit allen ${n.used} IP-Adressen darin?`,
      run: async () => { await api(`networks/${n.id}`, { method: "DELETE" }); doc.net = 0; await loadRef(true); await loadNetwork(); } } });
}

let diagUrl = "";
async function showDiagram(site) {
  $("diagErr").textContent = "";
  if (diagUrl) { URL.revokeObjectURL(diagUrl); diagUrl = ""; }
  const dg = site.diagram;
  $("diagDel").classList.toggle("hidden", !dg || !isAdmin());
  if (!dg) { $("diagBox").innerHTML = '<p class="muted small" style="margin:0">Noch kein Netzwerkplan. PNG, JPG oder PDF hochladen – z. B. aus draw.io exportiert.</p>'; return; }
  const meta = `<p class="muted small" style="margin:8px 0 0">${esc(dg.name)} · ${fmtDT(dg.created_at)}${dg.mime.startsWith("image/") ? " · Klick = groß" : ""}</p>`;
  if (!dg.mime.startsWith("image/")) {
    $("diagBox").innerHTML = `<div class="files"><span class="file" data-fid="${dg.id}" data-fname="${esc(dg.name)}" data-mime="${esc(dg.mime)}"><span class="th pdf">PDF</span><span>${esc(dg.name)}<small>${fmtSize2(dg.size)}</small></span></span></div>`;
    bindFiles($("diagBox"), () => loadNetwork());
    return;
  }
  try {
    const blob = await fetchBlob(dg.id, true);
    diagUrl = URL.createObjectURL(blob);
    $("diagBox").innerHTML = `<div class="diag"><img src="${diagUrl}" alt="Netzwerkplan"></div>${meta}`;
    $("diagBox").querySelector(".diag").onclick = () => showImage(blob);
  } catch (e) { $("diagErr").textContent = e.message; }
}
$("diagFile").onchange = async () => {
  const f = $("diagFile").files[0]; $("diagErr").textContent = "";
  if (!f) return;
  const siteId = doc.site || (doc.sites[0] || {}).id;
  try { await uploadFile(f, "site", siteId, "diagram"); await loadRef(true); await loadNetwork(); }
  catch (e) { $("diagErr").textContent = e.message; }
  $("diagFile").value = "";
};
$("diagDel").onclick = async () => {
  const site = doc.sites.find(s => s.id === (doc.site || (doc.sites[0] || {}).id));
  if (!site || !site.diagram || !confirm("Netzwerkplan entfernen?")) return;
  try { await api(`attachments/${site.diagram.id}`, { method: "DELETE" }); await loadRef(true); await loadNetwork(); } catch (e) { $("diagErr").textContent = e.message; }
};
function showIsp(site) {
  const rows = [["Anbieter", site.isp_provider], ["Tarif", site.isp_tariff], ["Öffentl. IP", site.isp_public_ip, "mono"], ["Kunden-Nr.", site.isp_customer_no, "mono"]]
    .filter(([, v]) => v);
  $("ispBox").innerHTML = (rows.length ? `<dl class="kv">${rows.map(([k, v, c]) => `<dt>${k}</dt><dd${c ? ` class="${c}"` : ""}>${esc(v)}</dd>`).join("")}</dl>`
    : '<p class="muted small" style="margin:0">Noch nichts eingetragen.</p>') +
    (site.isp_notes ? `<p class="small" style="margin:8px 0 0;white-space:pre-wrap">${esc(site.isp_notes)}</p>` : "");
  $("ispEdit").onclick = () => openForm({ title: "Internetanschluss" + (multiSite() ? " · " + site.name : ""), narrow: true, values: site, fields: [
    { k: "isp_provider", label: "Anbieter", ph: "z. B. Telekom" }, { k: "isp_tariff", label: "Tarif", ph: "z. B. Business Premium 250" },
    { k: "isp_public_ip", label: "Öffentliche IP", ph: "fest · 203.0.113.17 oder dynamisch" }, { k: "isp_customer_no", label: "Kundennummer" },
    { k: "isp_notes", label: "Notizen", type: "textarea", span2: true, ph: "z. B. Störungshotline, Router-Zugang beim Anbieter, Vertragsende" }],
    save: async (v) => { await api(`sites/${site.id}`, { method: "PATCH", body: v }); await loadRef(true); await loadNetwork(); } });
}

// ---------- Lizenzen ----------
const LIC_KINDS = [["software", "Software"], ["subscription", "Abo"], ["maintenance", "Wartungsvertrag"], ["domain", "Domain"],
                   ["certificate", "Zertifikat"], ["other", "Sonstiges"]];
const LIC_ICON = { domain: "🌐", certificate: "📜", maintenance: "🛠️" };
async function loadLicenses() {
  $("licListView").classList.remove("hidden"); $("licDetail").classList.add("hidden");
  $("licErr").textContent = "";
  const p = new URLSearchParams();
  if (doc.lic.filter) p.set("filter", doc.lic.filter);
  if (doc.lic.q) p.set("q", doc.lic.q);
  let rows, c;
  try { [rows, c] = await Promise.all([api("licenses?" + p), api("licenses/counts")]); } catch (e) { $("licErr").textContent = e.message; return; }
  $("licSeg").innerHTML = [["", `Alle ${c.all}`], ["due", `Läuft ab (${c.due})`], ["expired", `Abgelaufen (${c.expired})`]]
    .map(([k, l]) => `<button data-f="${k}" class="${doc.lic.filter === k ? "on" : ""}">${l}</button>`).join("");
  $$("#licSeg [data-f]").forEach(b => b.onclick = () => { doc.lic.filter = b.dataset.f; loadLicenses(); });
  $("licTable").innerHTML = `<thead><tr><th>Name</th><th>Art / Laufzeit</th><th class="num">Genutzt</th><th>Läuft ab</th><th>Vertrag / Kd.-Nr.</th></tr></thead><tbody>` +
    (rows.map(l => `<tr data-id="${l.id}"><td data-sort="${esc(l.name)}"><div class="nm"><span class="ti">${LIC_ICON[l.kind] || "🔑"}</span><div><b>${esc(l.name)}</b><small>${esc(l.vendor)}</small></div></div></td>
      <td>${esc(l.kind_label)}${l.term && l.term !== l.kind_label ? `<small class="muted" style="display:block">${esc(l.term)}</small>` : ""}</td>
      <td class="num" data-sort="${l.used || 0}">${l.seats != null ? `<span class="${l.used > l.seats ? "tag bad" : ""}">${l.used} / ${l.seats}</span>` : l.used ? `${l.used} / ∞` : "–"}</td>
      <td data-sort="${esc(l.expires_on || "")}">${dueTag(l.expires_on, l.days, true)}</td><td class="mono">${esc(l.contract_ref || "–")}</td></tr>`).join("") ||
     `<tr><td colspan="5" class="emptyrow">${doc.lic.filter || doc.lic.q ? "Keine Lizenzen für diese Auswahl." : "Noch keine Lizenzen erfasst."}</td></tr>`) + "</tbody>";
  sortTable($("licTable"));
  $$("#licTable [data-id]").forEach(tr => tr.onclick = () => go("licenses", tr.dataset.id));
}
$("licQ").oninput = debounce(() => { doc.lic.q = $("licQ").value.trim(); loadLicenses(); });
$("licNew").onclick = () => licenseForm(null);

function licenseForm(l) {
  const fields = [
    { k: "name", label: "Name", ph: "z. B. Microsoft 365 Business Standard", max: 150 },
    { k: "kind", label: "Art", type: "select", options: LIC_KINDS },
    { k: "vendor", label: "Hersteller / Anbieter" },
    { k: "term", label: "Laufzeit", ph: "z. B. Abo, jährlich · Kauf · OEM" },
    { k: "seats", label: "Plätze (leer = unbegrenzt)", type: "number" },
    { k: "seats_used", label: "Genutzt (leer = Geräte zählen)", type: "number" },
    { k: "expires_on", label: "Läuft ab am (leer = unbefristet)", type: "date" },
    { k: "contract_ref", label: "Vertrag / Kundennummer / Tenant" },
    { k: "notes", label: "Notizen", type: "textarea", span2: true, ph: "Kündigungsfrist, Ansprechpartner beim Händler … (Lizenzschlüssel ab 0.3 in den Tresor)" },
  ];
  openForm({ title: l ? `${l.name} bearbeiten` : "Neue Lizenz", fields, values: l ? { ...l } : { kind: "software" },
    save: async (v) => {
      const r = l ? await api(`licenses/${l.id}`, { method: "PATCH", body: v }) : await api("licenses", { method: "POST", body: v });
      if (l) await showLicense(l.id); else go("licenses", r.id);
    },
    del: l && { confirm: `„${l.name}“ löschen?`, run: async () => { await api(`licenses/${l.id}`, { method: "DELETE" }); go("licenses"); } } });
}

async function showLicense(id) {
  $("licListView").classList.add("hidden");
  const box = $("licDetail"); box.classList.remove("hidden");
  let l;
  try { l = await api(`licenses/${id}`); } catch (e) { box.innerHTML = `<div class="card err">${esc(e.message)}</div>`; return; }
  const adm = isAdmin();
  box.innerHTML = `<div class="crumbs"><a data-back>Lizenzen</a> › ${esc(l.name)}</div>
  <div class="tgrid" style="margin-top:12px">
    <section class="card">
      <div class="dhead"><span class="ti">${LIC_ICON[l.kind] || "🔑"}</span><div><h2>${esc(l.name)}</h2>
        <div class="row"><span class="tag">${esc(l.kind_label)}</span>${l.expires_on ? dueTag(l.expires_on, l.days, true) : '<span class="tag">unbefristet</span>'}${l.from_agent ? '<span class="tag" title="Wird vom Agent auf dem Gerät gepflegt">🛰️ vom Agent</span>' : ""}</div></div>
        ${adm ? '<div class="row"><button data-edit>Bearbeiten</button></div>' : ""}</div>
      <dl class="kv" style="grid-template-columns:150px 1fr">
        <dt>Hersteller</dt><dd>${esc(l.vendor || "–")}</dd><dt>Laufzeit</dt><dd>${esc(l.term || "–")}</dd>
        <dt>Plätze</dt><dd>${l.seats != null ? `${l.used} von ${l.seats} genutzt${l.seats_used == null ? " (zugeordnete Geräte)" : ""}` : "unbegrenzt / nicht gezählt"}</dd>
        <dt>Läuft ab</dt><dd>${l.expires_on ? deDate(l.expires_on) : "unbefristet"}</dd>
        <dt>Vertrag / Kd.-Nr.</dt><dd class="mono">${esc(l.contract_ref || "–")}</dd>
        <dt>Lizenzschlüssel</dt><dd id="licKey"><span class="tag lock">🔒 nur mit Vollzugriff</span></dd></dl>
      <div class="sect">Notizen</div>${l.notes ? `<div class="note">${esc(l.notes)}</div>` : '<p class="muted small" style="margin:0">–</p>'}
      <div class="sect">Anhänge ${uploadButton("licFile")}</div><div>${filesHtml(l.files)}</div><div class="err" id="licFileErr"></div>
    </section>
    <aside class="panel">
      <div class="card"><h3>Geräte (${l.devices.length})</h3>
        ${l.devices.map(x => `<div class="due"><span class="ti">${esc(x.icon)}</span><div><a href="#devices/${x.id}" style="color:var(--text);text-decoration:none">${esc(x.name)}</a>
          ${x.status !== "active" ? `<small>${esc(STATUS[x.status])}</small>` : ""}</div>${adm ? `<button class="x" data-undev="${x.id}" title="Zuordnung entfernen">✕</button>` : ""}</div>`).join("") ||
          '<p class="muted small" style="margin:0">Keinem Gerät zugeordnet.</p>'}
        ${adm ? '<button class="mini" data-adddev style="margin-top:8px">＋ Gerät zuordnen</button>' : ""}</div>
      ${adm ? '<div class="card" id="licCreds"></div>' : ""}
      <div class="card"><h3>Verlauf</h3>${historyHtml(l.history)}</div>
    </aside>
  </div>`;
  const reload = () => showLicense(id);
  if (adm && window.licenseKeyRow) { licenseKeyRow($("licKey"), l); credPanel($("licCreds"), "license", l.id); }
  box.querySelector("[data-back]").onclick = () => go("licenses");
  bindFiles(box, reload);
  if (!adm) return;
  bindUpload("licFile", "license", l.id, $("licFileErr"), reload);
  box.querySelector("[data-edit]").onclick = () => licenseForm(l);
  $$("[data-undev]", box).forEach(b => b.onclick = async () => {
    try { await api(`licenses/${l.id}/devices/${b.dataset.undev}`, { method: "DELETE" }); reload(); } catch (e) { alert(e.message); }
  });
  box.querySelector("[data-adddev]").onclick = async () => {
    const devs = (await api("devices")).filter(x => !l.devices.some(y => y.id === x.id));
    if (!devs.length) { alert("Kein (weiteres) Gerät vorhanden."); return; }
    openForm({ title: `${l.name} zuordnen`, narrow: true, fields: [{ k: "device_id", label: "Gerät", type: "select", int: true,
      options: devs.map(x => [x.id, `${x.type_icon} ${x.name}`]) }],
      save: async (v) => { await api(`licenses/${l.id}/devices`, { method: "POST", body: v }); reload(); } });
  };
}

// ---------- Kontakte ----------
async function loadContacts(openId) {
  $("ctErr").textContent = "";
  const p = new URLSearchParams();
  if (doc.ct.filter) p.set("filter", doc.ct.filter);
  if (doc.ct.q) p.set("q", doc.ct.q);
  let rows, all;
  try { [rows, all] = await Promise.all([api("contacts?" + p), api("contacts")]); } catch (e) { $("ctErr").textContent = e.message; return; }
  const cnt = { "": all.length, internal: all.filter(c => !c.external).length, external: all.filter(c => c.external).length, emergency: all.filter(c => c.emergency).length };
  $("ctSeg").innerHTML = [["", "Alle"], ["internal", "Intern"], ["external", "Extern"], ["emergency", "Notfall"]]
    .map(([k, l]) => `<button data-f="${k}" class="${doc.ct.filter === k ? "on" : ""}">${l} ${k ? `(${cnt[k]})` : cnt[k]}</button>`).join("");
  $$("#ctSeg [data-f]").forEach(b => b.onclick = () => { doc.ct.filter = b.dataset.f; loadContacts(); });
  const ln = (icon, v, href) => v ? `<div class="ln"><span>${icon}</span><span>${href ? `<a href="${href}">${esc(v)}</a>` : esc(v)}</span></div>` : "";
  $("ctGrid").innerHTML = rows.map(c => `<div class="ct" data-id="${c.id}">
      <div class="top"><span class="av ${c.external ? "ext" : ""}">${esc(initials(c.name))}</span><div><b>${esc(c.name)}</b>
        <small>${esc([c.company, c.role].filter(Boolean).join(" · "))}</small></div></div>
      ${ln("☎", c.phone, "tel:" + c.phone.replace(/[^\d+]/g, ""))}${ln("📱", c.mobile, "tel:" + c.mobile.replace(/[^\d+]/g, ""))}
      ${ln("✉", c.email, "mailto:" + c.email)}${ln("🌐", c.website)}${ln("#", c.customer_no ? "Kundennr. " + c.customer_no : "")}
      <div class="tags">${c.emergency ? '<span class="tag sos">Notfall</span>' : ""}${c.external ? '<span class="tag ext">extern</span>' : ""}
        ${multiSite() && c.site_id ? `<span class="tag">📍 ${esc(siteName(c.site_id))}</span>` : ""}</div></div>`).join("") ||
    `<p class="muted">${doc.ct.filter || doc.ct.q ? "Keine Kontakte für diese Auswahl." : "Noch keine Ansprechpartner erfasst."}</p>`;
  $$("#ctGrid [data-id]").forEach(el => el.onclick = (e) => { if (!e.target.closest("a")) contactForm(rows.find(c => c.id === Number(el.dataset.id))); });
  if (openId) { const c = all.find(x => x.id === openId); if (c) contactForm(c); history.replaceState(null, "", "#contacts"); state.sub = ""; }
}
$("ctQ").oninput = debounce(() => { doc.ct.q = $("ctQ").value.trim(); loadContacts(); });
$("ctNew").onclick = () => contactForm(null);

async function contactForm(c) {
  const fields = [
    { k: "name", label: "Name", max: 120 }, { k: "company", label: "Firma" }, { k: "role", label: "Rolle / Aufgabe", ph: "z. B. Praxisinhaberin, Praxissoftware" },
    { k: "phone", label: "Telefon" }, { k: "mobile", label: "Mobil" }, { k: "email", label: "E-Mail", type: "email" },
    { k: "website", label: "Webseite / Support-Portal" }, { k: "customer_no", label: "Kundennummer (bei Dienstleistern)" },
    ...(multiSite() ? [{ k: "site_id", label: "Standort", type: "select", int: true, options: siteOptions(true) }] : []),
    { k: "external", label: "externer Dienstleister", type: "check" }, { k: "emergency", label: "im Notfall anrufen (Übersicht)", type: "check" },
    { k: "notes", label: "Notizen", type: "textarea", span2: true, ph: "z. B. erreichbar Mo–Fr 8–17 Uhr, Fernwartung per TeamViewer" },
  ];
  if (!isAdmin()) {
    if (!c) return;
    const full = await api(`contacts/${c.id}`);
    $("sheet").innerHTML = `<div class="card narrow"><div class="toolbar"><h2>${esc(c.name)}</h2><button data-x>✕</button></div>
      <dl class="kv" style="grid-template-columns:130px 1fr">${fields.filter(f => f.type !== "check" && f.type !== "select" && full[f.k]).map(f =>
        `<dt>${esc(f.label)}</dt><dd style="white-space:pre-wrap">${esc(full[f.k])}</dd>`).join("")}</dl></div>`;
    $("sheet").classList.remove("hidden");
    $("sheet").querySelector("[data-x]").onclick = closeSheet;
    return;
  }
  const full = c ? await api(`contacts/${c.id}`) : null;
  openForm({ title: c ? `${c.name} bearbeiten` : "Neuer Ansprechpartner", fields, values: full || { site_id: "", external: doc.ct.filter === "external", emergency: doc.ct.filter === "emergency" },
    extra: full && full.history.length ? `<details class="small"><summary>Verlauf</summary>${historyHtml(full.history)}</details>` : "",
    save: async (v) => { if (c) await api(`contacts/${c.id}`, { method: "PATCH", body: v }); else await api("contacts", { method: "POST", body: v }); await loadContacts(); },
    del: c && { confirm: `„${c.name}“ löschen?`, run: async () => { await api(`contacts/${c.id}`, { method: "DELETE" }); await loadContacts(); } } });
}

// ---------- Verwaltung: Stammdaten ----------
async function loadStammdaten() {
  await loadRef(true);
  $("siteTable").innerHTML = `<thead><tr><th>Name</th><th>Adresse</th><th class="num">Geräte</th><th></th></tr></thead><tbody>` +
    doc.sites.map(s => `<tr><td><b>${esc(s.name)}</b></td><td class="wrap">${esc(s.address || "–")}</td><td class="num">${s.devices}</td>
      <td class="num"><button class="mini" data-site="${s.id}">Bearbeiten</button></td></tr>`).join("") + "</tbody>";
  $$("#siteTable [data-site]").forEach(b => b.onclick = () => siteForm(doc.sites.find(s => s.id === Number(b.dataset.site))));
  $("typeTable").innerHTML = `<thead><tr><th>Symbol</th><th>Name</th><th class="num">Geräte</th><th></th></tr></thead><tbody>` +
    doc.types.map((t, i) => `<tr><td style="font-size:18px">${esc(t.icon)}</td><td>${esc(t.name)}</td><td class="num">${t.devices}</td>
      <td class="num nowrap"><button class="mini" data-up="${t.id}" ${i ? "" : "disabled"} title="nach oben">↑</button>
        <button class="mini" data-down="${t.id}" ${i < doc.types.length - 1 ? "" : "disabled"} title="nach unten">↓</button>
        <button class="mini" data-type="${t.id}">Bearbeiten</button></td></tr>`).join("") + "</tbody>";
  const move = async (id, up) => { try { doc.types = await api(`device-types/${id}/move?up=${up}`, { method: "POST" }); loadStammdaten(); } catch (e) { $("typeErr").textContent = e.message; } };
  $$("#typeTable [data-up]").forEach(b => b.onclick = () => move(b.dataset.up, true));
  $$("#typeTable [data-down]").forEach(b => b.onclick = () => move(b.dataset.down, false));
  $$("#typeTable [data-type]").forEach(b => b.onclick = () => typeForm(doc.types.find(t => t.id === Number(b.dataset.type))));
}
window.loadStammdaten = loadStammdaten;
$("siteNew").onclick = () => siteForm(null);
$("typeNew").onclick = () => typeForm(null);
function siteForm(s) {
  openForm({ title: s ? `${s.name} bearbeiten` : "Neuer Standort", narrow: true, values: s || {}, fields: [
    { k: "name", label: "Name", ph: "z. B. Praxis Hauptstraße", max: 100 }, { k: "address", label: "Adresse", span2: true },
    { k: "notes", label: "Notizen", type: "textarea", span2: true, ph: "z. B. Schlüssel beim Hausmeister, Serverraum im Keller" }],
    save: async (v) => { if (s) await api(`sites/${s.id}`, { method: "PATCH", body: v }); else await api("sites", { method: "POST", body: v }); await loadStammdaten(); },
    del: s && { confirm: `Standort „${s.name}“ löschen?`, run: async () => { await api(`sites/${s.id}`, { method: "DELETE" }); await loadStammdaten(); } } });
}
function typeForm(t) {
  const others = t ? doc.types.filter(x => x.id !== t.id) : [];
  const extra = t && t.devices_all ? `<label>Zum Löschen: Geräte zusammenlegen mit <select id="typeInto">${others.map(x => `<option value="${x.id}">${esc(x.icon)} ${esc(x.name)}</option>`).join("")}</select></label>` : "";
  openForm({ title: t ? `Typ „${t.name}“` : "Neuer Gerätetyp", narrow: true, values: t || { icon: "📦" }, extra, fields: [
    { k: "icon", label: "Symbol (Emoji)", max: 8 }, { k: "name", label: "Name", max: 40, ph: "z. B. Waage, Kamera, USV" }],
    save: async (v) => { if (t) await api(`device-types/${t.id}`, { method: "PATCH", body: v }); else await api("device-types", { method: "POST", body: v }); await loadStammdaten(); },
    del: t && { confirm: t.devices_all ? `Typ „${t.name}“ löschen und seine ${t.devices_all} Geräte dem gewählten Typ zuordnen?` : `Typ „${t.name}“ löschen?`,
      run: async () => { const into = $("typeInto"); await api(`device-types/${t.id}${into ? "?into=" + into.value : ""}`, { method: "DELETE" }); await loadStammdaten(); } } });
}

// ---------- Suche ----------
const searchState = { items: [], idx: 0 };
const mark = (text, q) => {
  const s = String(text || ""); const i = s.toLowerCase().indexOf(q.toLowerCase());
  return i < 0 || !q ? esc(s) : esc(s.slice(0, i)) + "<mark>" + esc(s.slice(i, i + q.length)) + "</mark>" + esc(s.slice(i + q.length));
};
const runSearch = debounce(async () => {
  const q = $("gq").value.trim();
  if (!q) { $("gres").classList.add("hidden"); return; }
  let r;
  try { r = await api("search?q=" + encodeURIComponent(q)); } catch (e) { return; }
  if ($("gq").value.trim() !== q) return;
  const items = [];
  const group = (title, list, fn) => { if (list.length) { items.push({ h: title }); list.forEach(x => items.push(fn(x))); } };
  group("Geräte", r.devices, d => ({ icon: d.icon, main: mark(d.name, q), sub: [d.ip, d.room, d.serial && d.serial.toLowerCase().includes(q.toLowerCase()) ? "SN " + d.serial : d.model].filter(Boolean).map(x => mark(x, q)).join(" · "),
    right: d.status === "retired" ? "ausgemustert" : "Gerät", go: () => go("devices", d.id) }));
  group("IP-Adressen", r.ips, i => ({ icon: "🔢", main: `<span class="mono">${mark(i.ip, q)}</span>`, sub: [i.device_name, i.hostname, i.mac].filter(Boolean).map(x => mark(x, q)).join(" · "),
    right: i.network_name || "", go: () => i.device_id ? go("devices", i.device_id) : (doc.net = i.network_id || 0, go("network")) }));
  group("Ansprechpartner", r.contacts, c => ({ icon: "👤", main: mark(c.name, q), sub: [c.company, c.phone || c.mobile, c.email].filter(Boolean).map(x => mark(x, q)).join(" · "),
    right: c.external ? "extern" : "", go: () => go("contacts", c.id) }));
  group("Lizenzen", r.licenses, l => ({ icon: LIC_ICON[l.kind] || "🔑", main: mark(l.name, q), sub: mark(l.vendor, q), right: l.expires_on ? deDate(l.expires_on) : "", go: () => go("licenses", l.id) }));
  group("Netze", r.networks, n => ({ icon: "🌐", main: mark(n.name, q), sub: `<span class="mono">${mark(n.cidr, q)}</span>`, right: n.vlan != null ? "VLAN " + n.vlan : "",
    go: () => { if (n.site_id) setSite(n.site_id); doc.net = n.id; go("network"); } }));
  group("Standorte", r.sites, s => ({ icon: "📍", main: mark(s.name, q), sub: mark(s.address, q), right: "", go: () => { setSite(s.id); go("network"); } }));
  searchState.items = items.filter(x => !x.h); searchState.idx = 0;
  let n = 0;
  $("gres").innerHTML = items.length ? items.map(x => x.h ? `<h5>${x.h}</h5>` : `<a data-i="${n}" class="${n++ === 0 ? "on" : ""}"><span class="ti">${esc(x.icon)}</span>
      <span>${x.main}${x.sub ? `<small style="display:block">${x.sub}</small>` : ""}</span><small>${esc(x.right)}</small></a>`).join("")
    : `<div class="none">Nichts gefunden für „${esc(q)}“.</div>`;
  $("gres").classList.remove("hidden");
  $$("#gres [data-i]").forEach(a => a.onmousedown = (e) => { e.preventDefault(); pick(Number(a.dataset.i)); });
}, 180);
function pick(i) {
  const it = searchState.items[i];
  if (!it) return;
  $("gres").classList.add("hidden"); $("gq").value = ""; $("gq").blur();
  it.go();
}
$("gq").oninput = runSearch;
$("gq").onfocus = () => { if ($("gq").value.trim()) runSearch(); };
$("gq").onblur = () => setTimeout(() => $("gres").classList.add("hidden"), 150);
$("gq").onkeydown = (e) => {
  const n = searchState.items.length;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); if (!n) return;
    searchState.idx = (searchState.idx + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
    $$("#gres [data-i]").forEach(a => a.classList.toggle("on", Number(a.dataset.i) === searchState.idx));
  } else if (e.key === "Enter") { e.preventDefault(); pick(searchState.idx); }
  else if (e.key === "Escape") { $("gq").value = ""; $("gres").classList.add("hidden"); $("gq").blur(); }
};
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) && state.me) { e.preventDefault(); $("gq").focus(); }
});

// ---------- Notfall-Handbuch ----------
$("homeHandbook").onclick = async () => {
  const b = $("homeHandbook"); b.disabled = true;
  try { await downloadFile("api/v1/handbook.pdf" + (doc.site ? "?site_id=" + doc.site : ""), "notfall-handbuch.pdf"); }
  catch (e) { $("homeErr").textContent = e.message; }
  finally { b.disabled = false; }
};

// ---------- CSV-Import ----------
const imp = { b64: "", mapping: null, res: null };
$("devImport").onclick = () => {
  imp.b64 = ""; imp.mapping = null; imp.res = null;
  $("sheet").innerHTML = `<div class="card wide">
    <div class="toolbar"><h2>Geräte aus CSV importieren</h2><button data-x>✕</button></div>
    <p class="muted small" style="margin:0">Zum Beispiel ein Excel-Export oder eine Inventarliste (CSV mit ; , oder Tab). Im nächsten Schritt ordnest du die
      Spalten zu und siehst vor dem Import, was passiert. Geräte mit schon vorhandener Seriennummer werden übersprungen.</p>
    <label class="btn" style="justify-self:start">CSV-Datei auswählen <input type="file" id="impFile" accept=".csv,.txt,text/csv" hidden></label>
    <div id="impBody"></div><div class="err" id="impErr"></div></div>`;
  $("sheet").classList.remove("hidden");
  $("sheet").querySelector("[data-x]").onclick = closeSheet;
  $("impFile").onchange = () => {
    const f = $("impFile").files[0]; $("impErr").textContent = "";
    if (!f) return;
    if (f.size > 2 * 1024 * 1024) { $("impErr").textContent = "Die Datei ist zu groß (höchstens 2 MB)"; return; }
    const rd = new FileReader();
    rd.onload = () => { imp.b64 = String(rd.result).split(",")[1] || ""; imp.mapping = null; impPreview(); };
    rd.readAsDataURL(f);
  };
};
function impOptions() {
  const el = (id) => $(id);
  return { data_b64: imp.b64, mapping: imp.mapping, create_types: el("impTypes") ? el("impTypes").checked : true,
           create_sites: el("impSites") ? el("impSites").checked : true,
           default_site_id: el("impSite") && el("impSite").value ? Number(el("impSite").value) : null };
}
async function impPreview() {
  $("impErr").textContent = "";
  let r;
  try { r = await api("devices/import/preview", { method: "POST", body: impOptions() }); } catch (e) { $("impErr").textContent = e.message; return; }
  imp.res = r; imp.mapping = r.mapping;
  const byCol = {}; Object.entries(r.mapping).forEach(([f, i]) => { byCol[i] = f; });
  const fieldOpts = (col) => `<option value="">– nicht übernehmen –</option>` + Object.entries(r.fields).map(([k, l]) =>
    `<option value="${k}" ${byCol[col] === k ? "selected" : ""}>${esc(l)}${k === "name" ? " *" : ""}</option>`).join("");
  const sample = (i) => r.sample.map(row => row[i] || "").filter(Boolean).slice(0, 2).join(" · ");
  const icon = { create: "✅", skip: "⏭️", error: "❌" };
  const rows = r.rows.map(x => `<tr class="${x.action === "error" ? "inactive" : ""}"><td class="num">${x.line}</td><td>${icon[x.action]}</td>
    <td>${esc(x.values.name || x.show.name || "–")}</td><td>${esc(x.show.type || "")}</td>${multiSite() ? `<td>${esc(x.show.site || "")}</td>` : ""}
    <td class="mono">${esc(x.show.serial || "")}</td><td class="mono">${esc(x.show.ip || "")}</td>
    <td class="wrap small">${esc(x.errors.concat(x.warnings).join(" · "))}</td></tr>`).join("");
  $("impBody").innerHTML = `
    <h3 style="margin:6px 0">1. Spalten zuordnen <span class="muted small" style="font-weight:400">(${r.total} Zeilen erkannt)</span></h3>
    <div class="scroll"><table><thead><tr><th>Spalte in der Datei</th><th>Beispiel</th><th>wird zu</th></tr></thead><tbody>
      ${r.headers.map((h, i) => `<tr><td><b>${esc(h || "(ohne Titel)")}</b></td><td class="small muted wrap">${esc(sample(i))}</td>
        <td><select data-col="${i}">${fieldOpts(i)}</select></td></tr>`).join("")}</tbody></table></div>
    <div class="row" style="margin-top:8px"><label class="inline"><input type="checkbox" id="impTypes" checked> unbekannte Gerätetypen anlegen</label>
      <label class="inline"><input type="checkbox" id="impSites" checked> unbekannte Standorte anlegen</label>
      ${multiSite() ? `<label>Standort, wenn leer <select id="impSite"><option value="">–</option>${doc.sites.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select></label>` : ""}</div>
    <h3 style="margin:14px 0 6px">2. Vorschau ${r.needs_name ? "" : `<span class="muted small" style="font-weight:400">· ✅ ${r.counts.create} anlegen · ⏭️ ${r.counts.skip} überspringen · ❌ ${r.counts.error} fehlerhaft</span>`}</h3>
    ${r.needs_name ? '<p class="httpwarn" style="margin:0">Bitte die Spalte für den <b>Namen</b> zuordnen.</p>' :
      `<div class="scroll" style="max-height:340px"><table><thead><tr><th class="num">Zeile</th><th></th><th>Name</th><th>Typ</th>${multiSite() ? "<th>Standort</th>" : ""}<th>Seriennr.</th><th>IP</th><th>Hinweise</th></tr></thead>
       <tbody>${rows}</tbody></table></div>${r.total > r.rows.length ? `<p class="muted small">Vorschau zeigt die ersten ${r.rows.length} Zeilen.</p>` : ""}`}
    <div class="row" style="margin-top:12px"><button class="primary" id="impGo" ${r.needs_name || !r.counts.create ? "disabled" : ""}>${r.counts.create || 0} Geräte importieren</button>
      <button data-x2>Abbrechen</button></div>`;
  $("impBody").querySelector("[data-x2]").onclick = closeSheet;
  const opts = impOptions();
  if ($("impTypes")) $("impTypes").checked = opts.create_types;
  $$("#impBody [data-col]").forEach(sel => sel.onchange = () => {
    $$("#impBody [data-col]").forEach(s => { if (s !== sel && sel.value && s.value === sel.value) s.value = ""; });
    imp.mapping = {}; $$("#impBody [data-col]").forEach(s => { if (s.value) imp.mapping[s.value] = Number(s.dataset.col); });
    impPreview();
  });
  ["impTypes", "impSites", "impSite"].forEach(id => { if ($(id)) $(id).onchange = impPreview; });
  $("impGo").onclick = async () => {
    $("impGo").disabled = true;
    try {
      const res = await api("devices/import", { method: "POST", body: impOptions() });
      closeSheet(); await loadRef(true); doc.suggest = null; await loadDevices();
      okMsg($("devErr"), `${res.created} Geräte importiert` + (res.skipped ? `, ${res.skipped} übersprungen` : "") + (res.errors ? `, ${res.errors} fehlerhaft` : "") +
        (res.new_types.length ? ` · neue Typen: ${res.new_types.join(", ")}` : "") + (res.new_sites.length ? ` · neue Standorte: ${res.new_sites.join(", ")}` : ""));
    } catch (e) { $("impErr").textContent = e.message; $("impGo").disabled = false; }
  };
}

// ---------- Verwaltung → Mail: Fristen-Mail ----------
async function loadDeadlines() {
  const d = await api("deadlines");
  if (!$("dlDay").options.length) {
    $("dlDay").innerHTML = d.weekdays.map((w, i) => `<option value="${i}">${w}</option>`).join("");
    $("dlHour").innerHTML = Array.from({ length: 24 }, (_, h) => `<option value="${h}">${String(h).padStart(2, "0")}:00 Uhr</option>`).join("");
  }
  $("dlOn").checked = d.enabled; $("dlTo").value = d.recipients_raw || ""; $("dlDay").value = String(d.weekday);
  $("dlHour").value = String(d.hour); $("dlDays").value = String(d.days);
  if (![...$("dlDays").options].some(o => o.value === String(d.days))) $("dlDays").insertAdjacentHTML("beforeend", `<option value="${d.days}" selected>${d.days} Tage</option>`);
  $("dlSmtp").classList.toggle("hidden", d.smtp_ok);
  $("dlLast").textContent = d.last_result ? "Zuletzt: " + d.last_result : "";
  $("dlPreview").innerHTML = d.preview.length ? d.preview.map(x => `<div class="due"><span class="ti">${x.kind === "license" ? "🔑" : esc(x.icon || "🖥️")}</span>
      <div>${esc(x.name)}<small>${esc(x.what)}${x.info ? " · " + esc(x.info) : ""} · ${deDate(x.date)}</small></div>${dueTag(x.date, x.days)}</div>`).join("")
    : `<p class="muted small">Gerade ist in den nächsten ${d.days} Tagen nichts fällig – dann kommt auch keine Mail.</p>`;
}
window.loadDeadlines = loadDeadlines;
$("dlSave").onclick = async () => {
  $("dlErr").textContent = "";
  try {
    await api("deadlines", { method: "PATCH", body: { enabled: $("dlOn").checked, recipients: $("dlTo").value, weekday: Number($("dlDay").value),
      hour: Number($("dlHour").value), days: Number($("dlDays").value) } });
    await loadDeadlines(); okMsg($("dlErr"), "Gespeichert.");
  } catch (e) { $("dlErr").textContent = e.message; }
};
$("dlSend").onclick = async () => {
  $("dlErr").textContent = ""; $("dlSend").disabled = true;
  try { okMsg($("dlErr"), (await api("deadlines/send-now", { method: "POST" })).message); await loadDeadlines(); }
  catch (e) { $("dlErr").textContent = e.message; }
  finally { $("dlSend").disabled = false; }
};

// ---------- Netzwerk-Scan ----------
const DAY_MS = 86400000;
// ---------- Doppelte Geräte zusammenführen ----------
async function mergeForm(d, dups, reload) {
  const all = (await api("devices?status=all")).filter(x => x.id !== d.id);
  const first = dups.map(x => x.id);
  const opts = dups.map(x => [x.id, `${x.icon} ${x.name} – ${x.reason}`])
    .concat(all.filter(x => !first.includes(x.id)).map(x => [x.id, `${x.type_icon} ${x.name}`]));
  openForm({ title: `In „${d.name}“ zusammenführen`, narrow: true, fields: [
    { k: "other_id", label: "Doppelten Eintrag übernehmen", type: "select", int: true, options: opts }],
    values: { other_id: opts.length ? opts[0][0] : null },
    hint: `Das gewählte Gerät geht in „${d.name}“ auf und wird danach gelöscht: IP-Adressen, Lizenzen, Verbindungen, Zugangsdaten,
      Anhänge, Web-Adressen und ein Agent wandern mit; leere Felder (Hersteller, Seriennummer, Standort …) werden ergänzt, Notizen angehängt.
      Name und Typ von „${d.name}“ bleiben.`,
    save: async (v) => {
      if (!v.other_id) throw new Error("Bitte ein Gerät wählen");
      const other = opts.find(o => o[0] === v.other_id);
      if (!confirm(`„${other ? other[1] : "Gerät"}“ wirklich in „${d.name}“ zusammenführen? Das lässt sich nicht rückgängig machen (außer über die Datensicherung).`)) throw new Error("Abgebrochen.");
      await api(`devices/${d.id}/merge`, { method: "POST", body: { other_id: v.other_id } });
      reload();
    } });
}

// ---------- Web-Adressen ----------
const urlHost = (u) => { try { return new URL(u).host; } catch (e) { return u; } };
function webLink(url, html, cls = "", title = "") {
  if (!/^https?:\/\//i.test(url || "")) return "";
  return `<a class="${cls}" href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="${esc(title || url)}" data-web>${html}</a>`;
}
function ipWebCell(r) {
  const own = r.urls || [];
  const text = esc(r.hostname || (own.length || r.web_auto ? "" : "–"));
  if (own.length) return (r.hostname ? webLink(own[0].url, text, "", own[0].label ? `${own[0].label}: ${own[0].url}` : own[0].url) : "") +
    own.slice(0, 3).map(u => webLink(u.url, "↗", "weblnk", u.label ? `${u.label}: ${u.url}` : u.url)).join("");
  if (r.web_auto) return (r.hostname ? webLink(r.web_auto, text, "", r.web_auto + " (aus dem Netzwerk-Scan)") : "") +
    webLink(r.web_auto, "↗", "weblnk auto", r.web_auto + " (aus dem Netzwerk-Scan)");
  return text;
}

// Gerätename ist nur eine IP oder MAC (Netzwerk-Scan ohne Hostnamen)
function isPlaceholder(name) {
  const v = (name || "").trim();
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(v) || /^[0-9a-f]{2}([:-][0-9a-f]{2}){5}$/i.test(v) || (/^[0-9a-f:]+$/i.test(v) && v.includes("::"));
}
async function renameDevice(id, name, hostname, after) {
  const d = await api(`devices/${id}`);
  const sugg = hostname && !isPlaceholder(hostname) ? hostname.split(".")[0] : "";
  openForm({ title: "Gerät benennen", narrow: true, fields: [
    { k: "name", label: "Name", max: 100, ph: sugg || "z. B. Drucker Empfang" },
    { k: "type_id", label: "Typ", type: "select", int: true, options: doc.types.map(t => [t.id, `${t.icon} ${t.name}`]) }],
    values: { name: isPlaceholder(d.name) ? sugg : d.name, type_id: d.type_id },
    hint: isPlaceholder(d.name) ? `Bisher heißt das Gerät nur „${d.name}“.` : "",
    save: async (v) => {
      if (!v.name) throw new Error("Bitte einen Namen eintragen");
      await api(`devices/${id}`, { method: "PATCH", body: { name: v.name, type_id: v.type_id } }); after();
    } });
}

function seenDot(ts) {
  if (!ts) return '<span class="dot off" title="beim Scan nie gesehen"></span>';
  const age = Date.now() - new Date(ts).getTime();
  return `<span class="dot ${age < 2 * DAY_MS ? "on" : age > 30 * DAY_MS ? "old" : "off"}"></span>`;
}
function seenText(ts) {
  if (!ts) return '<span class="muted">nie</span>';
  const days = Math.floor((Date.now() - new Date(ts).getTime()) / DAY_MS);
  return days >= 2 ? `vor ${days} Tagen` : fmtDT(ts);
}
$("netScan").onclick = () => go("network", "scan");
let scanPoll = null;
async function loadScan() {
  $("netView").classList.add("hidden"); $("scanView").classList.remove("hidden");
  clearTimeout(scanPoll);
  let r;
  try { r = await api("scan"); } catch (e) { $("scanView").innerHTML = `<div class="card err">${esc(e.message)}</div>`; return; }
  const st = r.status, run = r.run, s = r.settings;
  const nets = r.networks;
  const on = nets.filter(n => n.scan && !n.problem);
  const off = nets.filter(n => !n.scan || n.problem);
  const types = doc.types.map(t => [t.id, `${t.icon} ${t.name}`]);
  const typeSel = (id) => `<select data-type>${types.map(([k, l]) => `<option value="${k}" ${k === id ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  const dur = run && run.finished_at ? Math.max(1, Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000)) : 0;
  const progress = st.running ? `<div class="scanbar"><span class="small">Scan läuft · ${esc(st.phase)} · ${st.done} von ${st.total} Adressen</span>
      <div class="prog"><i style="width:${st.total ? Math.round(st.done / st.total * 100) : 5}%"></i></div></div>` : "";
  $("scanView").innerHTML = `<section class="card">
    <div class="toolbar"><h2>🔍 Netzwerk-Scan</h2><div class="row"><button data-back>‹ Zurück zum Netzwerk</button>
      <button class="primary" data-start ${st.running || !on.length ? "disabled" : ""}>${st.running ? "Scan läuft …" : "Jetzt scannen"}</button></div></div>
    ${progress}
    <div class="scanbar"><span class="small">${run ? `Letzter Scan: ${fmtDT(run.finished_at_local)} (${run.trigger === "nightly" ? "nachts" : run.trigger === "agent" ? "vom Agent" : "von Hand"}) · ${esc(run.networks)} ·
        ${run.hosts_up} von ${run.addresses} Adressen online · Dauer ${dur} s${run.error ? ` · <span class="err">Fehler: ${esc(run.error)}</span>` : ""}` : "Noch kein Scan gelaufen."}</span>
      <label class="inline small" style="margin-left:auto"><input type="checkbox" data-nightly ${s.nightly ? "checked" : ""}> jede Nacht um
        <select data-hour>${Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${h === s.hour ? "selected" : ""}>${String(h).padStart(2, "0")}:00</option>`).join("")}</select> scannen</label></div>
    <p class="muted small" style="margin:8px 0 0">${on.length ? `Gescannt werden: ${on.map(n => `<b>${esc(n.name)}</b>${n.agent ? ` <span class="tag" title="scannt vor Ort und meldet per HTTPS">🛰️ ${esc(n.agent)}</span>` : ""}${
        n.requested ? ' <span class="tag warn" title="Der Agent fragt stündlich nach und scannt dann">angefordert</span>' : ""}${
        n.last_scan ? ` <span class="muted">(${fmtDT(n.last_scan)})</span>` : ""}`).join(", ")}` : "<b>Noch kein Netz zum Scannen markiert.</b>"}
      ${off.length ? ` · nicht gescannt: ${off.map(n => esc(n.name) + (n.problem && n.scan ? ` (${esc(n.problem)})` : "")).join(", ")}` : ""}.
      Den Haken „beim Netzwerk-Scan berücksichtigen“ setzt du am Netz (✎). Geprüft werden gängige Ports (Web, Windows-Freigaben, SSH, Drucker, RDP …);
      MAC-Adressen kommen aus der ARP-Tabelle der NAS (nur Netze, in denen die NAS selbst hängt), Namen aus DNS und NetBIOS.
      Entfernte Standorte ohne VPN scannt ein <b>Agent vor Ort</b> (am Netz unter „Gescannt von“ zuordnen) – er fragt stündlich nach,
      „Jetzt scannen“ fordert den Scan dort an.</p>
  </section>
  ${run ? `<section class="card grp">
    <h3>🆕 Neu gefunden <span class="tag ${r.new.length ? "warn" : ""}">${r.new.length}</span></h3>
    ${r.new.length ? `<div class="scroll"><table id="scNew"><thead><tr><th><input type="checkbox" data-all checked></th><th>IP</th><th>Name</th><th>MAC · Hersteller</th><th>Offene Ports</th><th>Name in der Doku</th><th>übernehmen als</th></tr></thead><tbody>
      ${r.new.map((h, i) => `<tr data-i="${i}"><td><input type="checkbox" data-pick ${h.vendor === "zufällige MAC" ? "" : "checked"}></td><td class="mono">${esc(h.ip)}${on.length > 1 && h.network_name ? `<small class="muted" style="display:block;font-family:inherit">${esc(h.network_name)}</small>` : ""}</td>
        <td class="mono">${esc(h.hostname || "–")}</td><td class="mono">${esc(h.mac || "–")}${h.vendor ? ` <span class="muted">· ${esc(h.vendor)}</span>` : ""}</td>
        <td class="ports">${esc(h.port_names.join(" · ") || "–")}</td><td><input data-name value="${esc(h.hostname || h.ip)}" style="width:150px"></td><td>${typeSel(h.type_id)}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="row" style="margin-top:8px"><button class="primary" data-adopt>Ausgewählte anlegen</button><button data-ignore-new>Ausgewählte ignorieren</button>
        <span class="muted small">Ignorierte tauchen bei späteren Scans nicht mehr als „neu“ auf.</span></div>` : '<p class="muted small">Keine unbekannten Geräte.</p>'}

    <h3>✏️ Ergänzen <span class="tag">${r.fill.length}</span></h3>
    ${r.fill.length ? `<div class="scroll"><table><thead><tr><th>Gerät</th><th>IP</th><th>wird ergänzt</th><th></th></tr></thead><tbody>
      ${r.fill.map((f, i) => `<tr><td>${f.device_id ? `${esc(f.device_icon)} <a href="#devices/${f.device_id}">${esc(f.device_name)}</a>` : '<span class="muted">ohne Gerät</span>'}</td><td class="mono">${esc(f.ip)}</td>
        <td class="mono small">${[f.mac ? "MAC " + esc(f.mac) : "", f.hostname ? "Hostname " + esc(f.hostname) : "", f.rename ? "Name → " + esc(f.rename) : ""].filter(Boolean).join(" · ")}</td>
        <td class="num"><button class="mini primary" data-fill="${i}">übernehmen</button></td></tr>`).join("")}</tbody></table></div>
      <div class="row" style="margin-top:8px"><button data-fill-all>Alle ${r.fill.length} übernehmen</button></div>` : '<p class="muted small">Nichts zu ergänzen.</p>'}

    <h3>⚠️ Abweichungen <span class="tag ${r.mismatch.length ? "bad" : ""}">${r.mismatch.length}</span></h3>
    ${r.mismatch.length ? `<div class="scroll"><table><thead><tr><th>Gerät</th><th>IP</th><th>MAC in der Doku</th><th>MAC jetzt</th><th></th></tr></thead><tbody>
      ${r.mismatch.map((m, i) => `<tr><td>${m.device_id ? `${esc(m.device_icon)} <a href="#devices/${m.device_id}">${esc(m.device_name)}</a>` : "–"}</td><td class="mono">${esc(m.ip)}</td>
        <td class="mono">${esc(m.mac_doc)}</td><td class="mono">${esc(m.mac_now)}${m.vendor ? ` <span class="muted">· ${esc(m.vendor)}</span>` : ""}</td>
        <td class="num nowrap"><button class="mini" data-mm="${i}">neue MAC übernehmen</button> <button class="mini" data-mmi="${i}">ignorieren</button></td></tr>`).join("")}</tbody></table></div>
      <p class="muted small">Typisch nach einem Gerätetausch – oder wenn eine IP doppelt vergeben ist.</p>` : '<p class="muted small">Keine Abweichungen.</p>'}

    <h3>💤 Länger nicht gesehen <span class="tag">${r.stale.length}</span> <span class="muted small" style="font-weight:400">· über ${s.stale_days} Tage</span></h3>
    ${r.stale.length ? `<div class="scroll"><table><thead><tr><th>Gerät</th><th>IP</th><th>zuletzt online</th><th></th></tr></thead><tbody>
      ${r.stale.map(x => `<tr><td>${esc(x.device_icon)} <a href="#devices/${x.device_id}">${esc(x.device_name)}</a></td><td class="mono">${esc(x.ip)}</td>
        <td>${seenText(x.last_seen)}</td><td class="num"><button class="mini" data-retire="${x.device_id}">als ausgemustert markieren</button></td></tr>`).join("")}</tbody></table></div>`
      : '<p class="muted small">Alle aktiven Geräte waren in letzter Zeit erreichbar (oder sind noch nicht lange genug erfasst).</p>'}
    <div class="err" id="scErr"></div>
  </section>` : ""}`;
  const v = $("scanView");
  v.querySelector("[data-back]").onclick = () => go("network");
  v.querySelector("[data-start]").onclick = async () => {
    try { await api("scan/start", { method: "POST" }); loadScan(); } catch (e) { alert(e.message); }
  };
  const saveSet = () => api("scan/settings", { method: "PATCH", body: { nightly: v.querySelector("[data-nightly]").checked, hour: Number(v.querySelector("[data-hour]").value) } }).catch(e => alert(e.message));
  v.querySelector("[data-nightly]").onchange = saveSet; v.querySelector("[data-hour]").onchange = saveSet;
  const err = (e) => { const el = $("scErr"); if (el) el.textContent = e.message; };
  const picked = () => $$("#scNew tbody tr", v).filter(tr => tr.querySelector("[data-pick]").checked);
  const all = v.querySelector("[data-all]");
  if (all) all.onchange = () => $$("#scNew [data-pick]", v).forEach(c => { c.checked = all.checked; });
  const ad = v.querySelector("[data-adopt]");
  if (ad) ad.onclick = async () => {
    const items = picked().map(tr => { const h = r.new[Number(tr.dataset.i)];
      return { ip: h.ip, network_id: h.network_id, name: tr.querySelector("[data-name]").value.trim() || h.ip, type_id: Number(tr.querySelector("[data-type]").value), mac: h.mac, hostname: h.hostname }; });
    if (!items.length) return;
    try { const res = await api("scan/adopt", { method: "POST", body: { items } }); await loadRef(true); await loadScan(); okMsg($("scErr"), `${res.created} Geräte angelegt.`); } catch (e) { err(e); }
  };
  const ig = v.querySelector("[data-ignore-new]");
  if (ig) ig.onclick = async () => {
    const keys = picked().map(tr => { const h = r.new[Number(tr.dataset.i)]; return h.mac && !h.vendor.startsWith("zufällig") ? `new:mac:${h.mac}` : `new:ip:${h.ip}`; });
    if (!keys.length) return;
    try { await api("scan/ignore", { method: "POST", body: { keys } }); loadScan(); } catch (e) { err(e); }
  };
  const fillItems = (list) => list.map(f => ({ ip_id: f.ip_id, mac: f.mac || null, hostname: f.hostname || null }));
  $$("[data-fill]", v).forEach(b => b.onclick = async () => { try { await api("scan/fill", { method: "POST", body: { items: fillItems([r.fill[Number(b.dataset.fill)]]) } }); loadScan(); } catch (e) { err(e); } });
  const fa = v.querySelector("[data-fill-all]");
  if (fa) fa.onclick = async () => { try { await api("scan/fill", { method: "POST", body: { items: fillItems(r.fill) } }); loadScan(); } catch (e) { err(e); } };
  $$("[data-mm]", v).forEach(b => b.onclick = async () => { const m = r.mismatch[Number(b.dataset.mm)];
    try { await api("scan/fill", { method: "POST", body: { items: [{ ip_id: m.ip_id, mac: m.mac_now }] } }); loadScan(); } catch (e) { err(e); } });
  $$("[data-mmi]", v).forEach(b => b.onclick = async () => { const m = r.mismatch[Number(b.dataset.mmi)];
    try { await api("scan/ignore", { method: "POST", body: { keys: [`mac:${m.ip_id}:${m.mac_now}`] } }); loadScan(); } catch (e) { err(e); } });
  $$("[data-retire]", v).forEach(b => b.onclick = async () => {
    if (!confirm("Gerät als ausgemustert markieren?")) return;
    try { await api(`devices/${b.dataset.retire}`, { method: "PATCH", body: { status: "retired" } }); loadScan(); } catch (e) { err(e); }
  });
  if (st.running) scanPoll = setTimeout(() => { if (state.tab === "network" && state.sub === "scan") loadScan(); }, 1500);
}
