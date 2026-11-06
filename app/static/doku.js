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
  if (tab === "network") return loadNetwork();
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
    (rows.map(d => `<tr data-id="${d.id}"><td><div class="nm"><span class="ti">${esc(d.type_icon)}</span><div><b>${esc(d.name)}</b>
      <small>${esc([[d.manufacturer, d.model].filter(Boolean).join(" "), d.os].filter(Boolean).join(" · "))}${d.status !== "active" ? ` · <i>${esc(d.status_label)}</i>` : ""}</small></div></div></td>
      <td class="mono">${esc(d.ips || "–")}</td><td>${esc(d.room || "–")}${multiSite() && !doc.site && d.site_name ? `<small class="muted" style="display:block">${esc(d.site_name)}</small>` : ""}</td><td>${esc(d.used_by || "–")}</td>
      <td class="mono">${esc(d.serial || "–")}</td><td>${warr(d)}</td></tr>`).join("") ||
      `<tr><td colspan="7" class="emptyrow">${doc.dev.q || doc.dev.type ? "Keine Geräte für diese Auswahl." : "Noch keine Geräte erfasst." + (isAdmin() ? " Mit „＋ Gerät“ geht es los." : "")}</td></tr>`) + "</tbody>";
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
  <div class="tgrid" style="margin-top:12px">
    <section class="card">
      <div class="dhead"><span class="ti">${esc(d.type_icon)}</span><div><h2>${esc(d.name)}</h2>
        <div class="row"><span class="tag ${d.status === "active" ? "okk" : ""}">${esc(d.status_label)}</span><span class="tag">${esc(d.type_name)}</span>
          ${d.site_name || d.room ? `<span class="tag">📍 ${esc([multiSite() ? d.site_name : "", d.room].filter(Boolean).join(" · "))}</span>` : ""}</div></div>
        ${adm ? '<div class="row"><button data-edit>Bearbeiten</button></div>' : ""}</div>
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
      <div class="sect">Notizen</div>
      ${d.notes ? `<div class="note">${esc(d.notes)}</div>` : '<p class="muted small" style="margin:0">–</p>'}
      <div class="sect">Anhänge ${uploadButton("devFile")}</div>
      <div id="devFiles">${filesHtml(d.files)}</div><div class="err" id="devFileErr"></div>
    </section>
    <aside class="panel">
      ${adm ? '<div class="card" id="devCreds"></div>' : ""}
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
  $("netErr").textContent = "";
  const siteId = doc.site || (doc.sites[0] || {}).id;
  const site = doc.sites.find(s => s.id === siteId) || {};
  $("netSite").value = String(siteId || "");
  $("netTitle").textContent = "Netze" + (multiSite() ? " · " + (site.name || "") : "");
  let nets;
  try { nets = await api("networks" + (multiSite() ? "?site_id=" + siteId : "")); } catch (e) { $("netErr").textContent = e.message; return; }
  if (!nets.some(n => n.id === doc.net)) doc.net = (nets[0] || {}).id || 0;
  $("netGrid").innerHTML = nets.map(n => `<div class="net ${n.id === doc.net ? "on" : ""}" data-net="${n.id}">
      <h3><span>${esc(n.name)}</span><span class="row" style="gap:6px">${n.vlan != null ? `<span class="tag">VLAN ${n.vlan}</span>` : ""}
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
  $("ipTable").innerHTML = `<thead><tr><th>IP</th><th>Gerät</th><th>Hostname</th><th>MAC</th><th>Hinweis</th></tr></thead><tbody>` +
    (rows.map(r => r.free ? `<tr class="free" data-free="${esc(r.ip)}"><td class="mono">${esc(r.ip)}</td><td colspan="4">frei</td></tr>`
      : `<tr data-ip="${r.id}"><td class="mono">${esc(r.ip)}</td><td>${r.device_id ? `${esc(r.device_icon)} ${esc(r.device_name)}` : '<span class="muted">–</span>'}</td>
        <td class="mono">${esc(r.hostname || "–")}</td><td class="mono">${esc(r.mac || "–")}</td><td class="wrap small">${esc([r.kind !== "static" ? r.kind_label : "", r.notes].filter(Boolean).join(" · "))}</td></tr>`).join("") +
     (net.dhcp_from && !q ? `<tr class="free"><td class="mono">${esc(dhcpRange(net.dhcp_from, net.dhcp_to))}</td><td colspan="4">DHCP-Bereich</td></tr>` : "") ||
     '<tr><td colspan="5" class="emptyrow">Keine IP-Adressen.</td></tr>') + "</tbody>";
  const reload = () => loadNetwork();
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

function networkForm(n) {
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
    (rows.map(l => `<tr data-id="${l.id}"><td><div class="nm"><span class="ti">${LIC_ICON[l.kind] || "🔑"}</span><div><b>${esc(l.name)}</b><small>${esc(l.vendor)}</small></div></div></td>
      <td>${esc(l.kind_label)}${l.term && l.term !== l.kind_label ? `<small class="muted" style="display:block">${esc(l.term)}</small>` : ""}</td>
      <td class="num">${l.seats != null ? `<span class="${l.used > l.seats ? "tag bad" : ""}">${l.used} / ${l.seats}</span>` : l.used ? `${l.used} / ∞` : "–"}</td>
      <td>${dueTag(l.expires_on, l.days, true)}</td><td class="mono">${esc(l.contract_ref || "–")}</td></tr>`).join("") ||
     `<tr><td colspan="5" class="emptyrow">${doc.lic.filter || doc.lic.q ? "Keine Lizenzen für diese Auswahl." : "Noch keine Lizenzen erfasst."}</td></tr>`) + "</tbody>";
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
        <div class="row"><span class="tag">${esc(l.kind_label)}</span>${l.expires_on ? dueTag(l.expires_on, l.days, true) : '<span class="tag">unbefristet</span>'}</div></div>
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
