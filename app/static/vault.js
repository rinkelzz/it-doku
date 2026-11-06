"use strict";
// Tresor: Anzeige in der Kopfzeile, Einrichten, Entsperren, Einladung, Notfall-Schlüssel, Zugangsdaten, Lizenzschlüssel.
// Baut auf app.js und doku.js auf (api, esc, $, $$, openForm, closeSheet, go, downloadFile, historyHtml …).

const vs = { status: null, remaining: 0, tick: null, after: [], filter: "", q: "", owners: null };
const VMIN_PW = 10;

// ---------- Zwischenablage ----------
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
    else throw new Error("kein Clipboard-API");
  } catch (e) {  // http im Heimnetz: alter Weg
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } finally { ta.remove(); }
  }
  clearTimeout(copyText.t);
  copyText.t = setTimeout(async () => {  // nach 30 s leeren, soweit erlaubt
    try { if (navigator.clipboard && window.isSecureContext && document.hasFocus()) await navigator.clipboard.writeText(""); } catch (e) { /* egal */ }
  }, 30000);
}
function flash(btn, text = "✓") {
  const old = btn.textContent; btn.textContent = text; btn.disabled = true;
  setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1200);
}

// ---------- Status und Kopfzeile ----------
const fmtMS = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
async function vaultRefresh() {
  if (!state.me || !isAdmin()) { $("vchip").classList.add("hidden"); return null; }
  try { vs.status = await api("vault/status"); } catch (e) { return null; }
  vs.remaining = vs.status.remaining;
  renderChip();
  return vs.status;
}
function renderChip() {
  const s = vs.status, chip = $("vchip");
  if (!s || !s.can_use) { chip.classList.add("hidden"); return; }
  chip.classList.remove("hidden");
  clearInterval(vs.tick);
  if (s.unlocked) {
    chip.className = "vchip open";
    chip.innerHTML = `<span title="Sperrt sich nach ${s.timeout_min} Minuten ohne Aktivität">🔓 <span class="vl">Tresor offen · </span><b id="vrem">${fmtMS(vs.remaining)}</b></span><button>Sperren</button>`;
    chip.querySelector("button").onclick = vaultLock;
    vs.tick = setInterval(() => {
      vs.remaining = Math.max(0, vs.remaining - 1);
      const el = $("vrem"); if (el) el.textContent = fmtMS(vs.remaining);
      if (vs.remaining <= 0) { clearInterval(vs.tick); vaultRefresh().then(rerender); }
    }, 1000);
  } else {
    chip.className = "vchip closed";
    const label = !s.initialized ? "einrichten" : s.invited && !s.member ? "Einladung annehmen" : "Entsperren";
    chip.innerHTML = `<span>🔒 <span class="vl">Tresor</span></span><button>${label}</button>`;
    chip.querySelector("button").onclick = () => vaultOpen();
  }
}
window.vaultTouch = () => { if (vs.status && vs.status.unlocked) vs.remaining = vs.status.timeout_min * 60; };
window.vaultLocked = () => { if (vs.status && vs.status.unlocked) { vs.status.unlocked = false; renderChip(); } };
function vaultInit() { vaultRefresh(); }
window.vaultInit = vaultInit;
async function vaultLock() {
  try { await api("vault/lock", { method: "POST" }); } catch (e) { /* egal */ }
  await vaultRefresh(); rerender();
}
// nach Öffnen/Sperren die aktuelle Ansicht neu zeichnen
function rerender() {
  if (state.tab === "vault") loadCredentials();
  else if (state.tab === "devices" && state.sub) docShow("devices", state.sub);
  else if (state.tab === "licenses" && state.sub) docShow("licenses", state.sub);
  else if (state.tab === "network") docShow("network", "");
  else if (state.tab === "admin" && window.loadVaultAdmin) loadVaultAdmin().catch(() => {});
}

// Tresor öffnen: je nach Zustand einrichten, Einladung annehmen oder entsperren. then() läuft danach (z. B. Passwort anzeigen).
async function vaultOpen(then) {
  const s = await vaultRefresh();
  if (!s) return;
  if (s.unlocked) { if (then) then(); return; }
  if (!s.initialized) return setupWizard(then);
  if (s.invited && !s.member) return joinDialog(then);
  if (!s.member) { alert("Du hast noch keinen Zugang zum Tresor. Bitte von jemandem mit Zugang freischalten lassen (Verwaltung → Tresor)."); return; }
  unlockDialog(then);
}
window.vaultOpen = vaultOpen;
async function withVault(fn) {
  try { return await fn(); }
  catch (e) { if (e.status === 423) { vaultOpen(() => fn().catch(err => alert(err.message))); return null; } throw e; }
}

function pwPair(newLabel = "Tresor-Passwort") {
  return [{ k: "pw1", label: `${newLabel} (mind. ${VMIN_PW} Zeichen)`, type: "password" }, { k: "pw2", label: "Wiederholen", type: "password" }];
}
function checkPair(v) {
  if ((v.pw1 || "").length < VMIN_PW) throw new Error(`Das Tresor-Passwort muss mindestens ${VMIN_PW} Zeichen haben`);
  if (v.pw1 !== v.pw2) throw new Error("Die beiden Passwörter sind nicht gleich");
  return v.pw1;
}
function after(then) { vaultRefresh().then(() => { rerender(); if (then) then(); }); }

function unlockDialog(then) {
  const card = openForm({ title: "🔒 Tresor entsperren", narrow: true, fields: [{ k: "pw", label: "Dein Tresor-Passwort", type: "password" }],
    hint: `Nicht dein Login-Passwort. Der Tresor bleibt offen, bis du ihn sperrst, dich abmeldest oder ${vs.status.timeout_min} Minuten nichts tust.`,
    extra: '<a class="small" data-forgot style="cursor:pointer">Passwort vergessen? → Notfall-Schlüssel</a>',
    save: async (v) => { await api("vault/unlock", { method: "POST", body: { password: v.pw } }); after(then); } });
  card.querySelector("[data-forgot]").onclick = () => recoverDialog(then);
}
function recoverDialog(then) {
  openForm({ title: "Mit Notfall-Schlüssel öffnen", narrow: true, fields: [
    { k: "rk", label: "Notfall-Schlüssel (vom ausgedruckten Blatt)", mono: true, ph: "XXXX-XXXX-…", span2: true }, ...pwPair("Neues Tresor-Passwort")],
    hint: "Du legst damit ein neues eigenes Tresor-Passwort fest. Das wird im Protokoll vermerkt.",
    save: async (v) => { const pw = checkPair(v); await api("vault/recover", { method: "POST", body: { recovery_key: v.rk, new_password: pw } }); after(then); } });
}
function joinDialog(then) {
  openForm({ title: "Einladung zum Tresor annehmen", narrow: true, fields: [
    { k: "code", label: "Einladungscode", mono: true, ph: "ABCD-EFGH-JKMN-PQRS", span2: true }, ...pwPair("Dein eigenes Tresor-Passwort")],
    hint: `Den Code hast du von der Person bekommen, die dich freigeschaltet hat (gültig bis ${fmtDT(vs.status.invite_expires)}).
      Das Tresor-Passwort kennst nur du – bitte gut merken oder im eigenen Passwort-Manager ablegen.`,
    save: async (v) => { const pw = checkPair(v); await api("vault/join", { method: "POST", body: { code: v.code, password: pw } }); after(then); } });
}
function setupWizard(then) {
  openForm({ title: "Tresor einrichten · Schritt 1 von 2", narrow: true, fields: pwPair("Tresor-Passwort"),
    hint: `Mit dem Tresor-Passwort öffnest du künftig die Zugangsdaten. Es ist <b>nicht</b> dein Login-Passwort und wird nirgends gespeichert.
      Im nächsten Schritt bekommst du einen Notfall-Schlüssel zum Ausdrucken.`,
    save: async (v) => {
      const pw = checkPair(v);
      const r = await api("vault/setup", { method: "POST", body: { password: pw } });
      setTimeout(() => showRecoveryKey(r.recovery_key, "Tresor einrichten · Schritt 2 von 2", then), 0);
    } });
}
function showRecoveryKey(key, title, then) {
  $("sheet").innerHTML = `<div class="card">
    <div class="toolbar"><h2>${esc(title)}</h2></div>
    <p style="margin:0">Das ist der <b>Notfall-Schlüssel</b> für diesen Tresor. Mit ihm lässt sich ein neues Tresor-Passwort setzen,
      wenn alle Tresor-Passwörter vergessen sind. <b>Er wird nur jetzt angezeigt</b> und nirgends gespeichert.</p>
    <div class="rkey">${esc(key)}</div>
    <div class="row"><button class="primary" data-pdf>📄 Als PDF herunterladen</button><button data-copy>⧉ Kopieren</button></div>
    <div class="warnbox">Ausdrucken und an einem sicheren Ort aufbewahren – z. B. im Tresor der Firma. Ohne Tresor-Passwort und ohne
      Notfall-Schlüssel sind die Zugangsdaten <b>nicht wiederherstellbar</b>, auch nicht durch den IT-Dienstleister.</div>
    <label class="inline"><input type="checkbox" data-ok> Ich habe den Notfall-Schlüssel ausgedruckt oder sicher notiert.</label>
    <div class="row"><button class="primary" data-done disabled>Fertig</button></div><div class="err" data-err></div></div>`;
  $("sheet").classList.remove("hidden");
  const card = $("sheet").firstElementChild;
  card.querySelector("[data-ok]").onchange = (e) => { card.querySelector("[data-done]").disabled = !e.target.checked; };
  card.querySelector("[data-copy]").onclick = (e) => copyText(key).then(() => flash(e.target, "✓ Kopiert"));
  card.querySelector("[data-pdf]").onclick = async () => {
    try {
      const res = await fetch(url("api/v1/vault/recovery-sheet"), { method: "POST", credentials: "same-origin",
        headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify({ recovery_key: key }) });
      if (!res.ok) throw new Error("PDF konnte nicht erstellt werden");
      const u = URL.createObjectURL(await res.blob());
      const a = document.createElement("a"); a.href = u; a.download = "notfall-schluessel.pdf"; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(u), 4000);
    } catch (e) { card.querySelector("[data-err]").textContent = e.message; }
  };
  card.querySelector("[data-done]").onclick = () => { closeSheet(); after(then); };
}

// ---------- Geheimnisse anzeigen und kopieren ----------
async function reveal(credId, field, purpose) {
  return api(`credentials/${credId}/reveal`, { method: "POST", body: { field, purpose } });
}
function secretRow(c, field, label) {
  const copy = field !== "notes";
  return `<dt>${label}</dt><dd data-val="${c.id}:${field}"><span class="mask">${field === "totp" ? "••• •••" : "••••••••"}</span></dd>
    <span class="acts"><button data-show="${c.id}:${field}" title="anzeigen">👁</button>${copy ? `<button data-copy="${c.id}:${field}" title="kopieren">⧉</button>` : ""}</span>`;
}
function credHtml(c, opts = {}) {
  const meta = [opts.hideOwner ? "" : c.owner_name ? `${esc(c.owner_name)}` : "allgemein",
    c.url ? (/^https?:\/\//i.test(c.url) ? `<a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.url)}</a>` : esc(c.url)) : "",
    c.username ? `Benutzer <span class="mono">${esc(c.username)}</span>` : ""].filter(Boolean).join(" · ");
  const age = c.old ? ` · <span class="tag warn">Passwort seit ${Math.floor(c.password_age_days / 365)} Jahr${c.password_age_days >= 730 ? "en" : ""} gleich</span>` : "";
  return `<div class="cred" data-cred="${c.id}"><span class="ti">${esc(c.owner_icon)}</span><div style="min-width:0"><b>${esc(c.title)}</b><small>${meta}${age}</small>
    <dl class="secret">${c.has_password ? secretRow(c, "password", "Passwort") : ""}${c.has_totp ? secretRow(c, "totp", "2FA-Code") : ""}${c.has_notes ? secretRow(c, "notes", "Notiz") : ""}</dl></div>
    <button class="mini" data-cedit="${c.id}">Bearbeiten</button></div>`;
}
function bindCreds(root, list, reload, preset) {
  $$("[data-show]", root).forEach(b => b.onclick = () => withVault(async () => {
    const [id, field] = b.dataset.show.split(":");
    const dd = root.querySelector(`[data-val="${id}:${field}"]`);
    if (b.dataset.on) { dd.innerHTML = `<span class="mask">${field === "totp" ? "••• •••" : "••••••••"}</span>`; b.textContent = "👁"; delete b.dataset.on; return; }
    const r = await reveal(id, field, "show");
    b.dataset.on = "1"; b.textContent = "🙈";
    if (field === "totp") {
      dd.innerHTML = `<span class="totp">${esc(r.code.replace(/^(\d{3})(\d+)$/, "$1 $2"))} <span class="ring" style="--p:${Math.round(r.remaining / r.period * 100)}%" title="noch ${r.remaining} s"></span></span>`;
      setTimeout(() => { if (b.dataset.on) b.click(); }, r.remaining * 1000);
    } else {
      dd.innerHTML = `<span style="white-space:pre-wrap">${esc(r.value)}</span>`;
      setTimeout(() => { if (b.dataset.on) b.click(); }, 30000);
    }
  }));
  $$("[data-copy]", root).forEach(b => b.onclick = () => withVault(async () => {
    const [id, field] = b.dataset.copy.split(":");
    const r = await reveal(id, field, "copy");
    await copyText(field === "totp" ? r.code : r.value); flash(b);
  }));
  $$("[data-cedit]", root).forEach(b => b.onclick = () => credForm(list.find(c => c.id === Number(b.dataset.cedit)), reload, preset));
}

// ---------- Passwort-Generator (im Browser) ----------
function genPassword(len, sets, noSimilar) {
  let chars = "";
  if (sets.upper) chars += "ABCDEFGHJKLMNPQRSTUVWXYZ" + (noSimilar ? "" : "IO");
  if (sets.lower) chars += "abcdefghijkmnopqrstuvwxyz" + (noSimilar ? "" : "l");
  if (sets.digits) chars += "23456789" + (noSimilar ? "" : "01");
  if (sets.symbols) chars += "!#%+-=?@_*$&";
  if (!chars) chars = "abcdefghijkmnopqrstuvwxyz";
  const out = [];
  const buf = new Uint32Array(len * 2);
  for (;;) {
    crypto.getRandomValues(buf);
    out.length = 0;
    for (let i = 0; i < buf.length && out.length < len; i++) {
      const lim = Math.floor(4294967296 / chars.length) * chars.length;  // ohne Verzerrung
      if (buf[i] < lim) out.push(chars[buf[i] % chars.length]);
    }
    const pw = out.join("");
    const ok = (!sets.upper || /[A-Z]/.test(pw)) && (!sets.lower || /[a-z]/.test(pw)) && (!sets.digits || /\d/.test(pw)) && (!sets.symbols || /[^A-Za-z0-9]/.test(pw));
    if (pw.length === len && (ok || len < 4)) return pw;
  }
}
function strength(pw) {
  let pool = 0;
  if (/[a-z]/.test(pw)) pool += 26; if (/[A-Z]/.test(pw)) pool += 26; if (/\d/.test(pw)) pool += 10; if (/[^A-Za-z0-9]/.test(pw)) pool += 15;
  const bits = pw.length * Math.log2(Math.max(pool, 1));
  return bits >= 100 ? [100, "sehr stark", "var(--ok)"] : bits >= 70 ? [75, "stark", "var(--ok)"] : bits >= 45 ? [45, "mittel", "var(--warn)"] : [Math.max(8, bits), "schwach", "var(--bad)"];
}

// ---------- Formular ----------
async function ownerOptions() {
  if (!vs.owners) {
    const [devs, lics, cts] = await Promise.all([api("devices?status=all"), api("licenses"), api("contacts")]);
    vs.owners = [["", "– allgemein –"]]
      .concat(devs.map(d => [`device:${d.id}`, `${d.type_icon} Gerät: ${d.name}`]))
      .concat(lics.map(l => [`license:${l.id}`, `🔑 Lizenz: ${l.name}`]))
      .concat(doc.sites.map(s => [`site:${s.id}`, `📍 Standort: ${s.name}`]))
      .concat(cts.map(c => [`contact:${c.id}`, `👤 Kontakt: ${c.name}`]));
  }
  return vs.owners;
}
async function credForm(c, reload, preset) {
  vs.owners = null;
  const owners = await ownerOptions();
  const own = c ? (c.owner_type ? `${c.owner_type}:${c.owner_id}` : "") : (preset ? `${preset.owner_type}:${preset.owner_id}` : "");
  const fields = [
    { k: "title", label: "Titel", ph: "z. B. FRITZ!Box – Oberfläche", max: 150 },
    { k: "owner", label: "Gehört zu", type: "select", options: owners },
    { k: "username", label: "Benutzername", mono: true },
    { k: "url", label: "Adresse / URL", mono: true, ph: "https://… oder 192.168.10.1" },
  ];
  const editHint = (has) => c && has ? "gespeichert – leer lassen = unverändert" : "";
  const extra = `
    <div class="span2" style="display:grid;gap:4px"><span class="small muted">Passwort 🔒</span>
      <div class="pwrow"><input data-x="password" type="password" autocomplete="new-password" placeholder="${editHint(c && c.has_password)}">
        <button type="button" data-eye title="anzeigen">👁</button><button type="button" data-gen>🎲 Erzeugen</button></div>
      <div class="gen hidden" data-genbox>
        <div class="row"><label class="inline">Länge <input type="range" data-len min="8" max="64" value="20"> <b data-lenv>20</b></label>
          <label class="inline"><input type="checkbox" data-set="upper" checked> A–Z</label><label class="inline"><input type="checkbox" data-set="lower" checked> a–z</label>
          <label class="inline"><input type="checkbox" data-set="digits" checked> 0–9</label><label class="inline"><input type="checkbox" data-set="symbols" checked> !#%…</label>
          <label class="inline"><input type="checkbox" data-sim> ohne ähnliche Zeichen (Il1O0)</label></div>
        <small class="muted">Erzeugt im Browser, nicht auf dem Server.</small></div>
      <div class="strength"><i data-str style="width:0"></i></div><small class="muted" data-strt></small>
      ${c && c.has_password ? '<label class="inline small"><input type="checkbox" data-del="password"> Passwort entfernen</label>' : ""}</div>
    <label class="span2" style="display:grid;gap:4px">2FA-Geheimnis (optional) 🔒 <input data-x="totp" class="mono" autocomplete="off"
      placeholder="${c && c.has_totp ? "gespeichert – leer lassen = unverändert" : "Base32-Code oder otpauth://… aus dem QR-Code"}"></label>
    ${c && c.has_totp ? '<label class="inline small span2"><input type="checkbox" data-del="totp"> 2FA entfernen</label>' : ""}
    <label class="span2" style="display:grid;gap:4px">Notiz 🔒 <textarea data-x="notes" rows="3" placeholder="${c && c.has_notes ? "gespeichert – leer lassen = unverändert (Inhalt über 👁 in der Liste)" : "z. B. Wiederherstellungscodes, Sicherheitsfragen"}"></textarea></label>
    ${c && c.has_notes ? '<label class="inline small span2"><input type="checkbox" data-del="notes"> Notiz entfernen</label>' : ""}
    ${c && c.history ? `<details class="small span2"><summary>Verlauf</summary>${historyHtml(c.history)}</details>` : ""}`;
  const card = openForm({ title: c ? `${c.title} bearbeiten` : "Neuer Zugang", fields,
    values: c ? { ...c, owner: own } : { owner: own },
    extra: `<div class="formgrid">${extra}</div><p class="muted small" style="margin:0">🔒 = verschlüsselt im Tresor. Titel, Benutzername und Adresse
      bleiben lesbar, damit Liste und Suche ohne offenen Tresor funktionieren.</p>`,
    save: async (v) => {
      const [ot, oid] = (v.owner || "").split(":");
      const body = { title: v.title, username: v.username, url: v.url, owner_type: ot || null, owner_id: oid ? Number(oid) : null };
      ["password", "totp", "notes"].forEach(f => {
        const val = card.querySelector(`[data-x="${f}"]`).value;
        const del = card.querySelector(`[data-del="${f}"]`);
        if (del && del.checked) body[f] = "";
        else if (val.trim() !== "" || (!c && val)) body[f] = f === "notes" ? val : val.trim();
      });
      const run = () => c ? api(`credentials/${c.id}`, { method: "PATCH", body }) : api("credentials", { method: "POST", body });
      try { await run(); }
      catch (e) {
        if (e.status === 423) throw new Error("Der Tresor ist gesperrt – bitte oben rechts entsperren und erneut speichern.");
        throw e;
      }
      await reload();
    },
    del: c && { confirm: `Zugang „${c.title}“ löschen?`, run: async () => { await api(`credentials/${c.id}`, { method: "DELETE" }); await reload(); } } });
  const pw = card.querySelector('[data-x="password"]');
  const upd = () => {
    const [p, t, col] = pw.value ? strength(pw.value) : [0, "", ""];
    card.querySelector("[data-str]").style.width = p + "%"; card.querySelector("[data-str]").style.background = col;
    card.querySelector("[data-strt]").textContent = t;
  };
  pw.oninput = upd;
  card.querySelector("[data-eye]").onclick = (e) => { pw.type = pw.type === "password" ? "text" : "password"; e.target.textContent = pw.type === "password" ? "👁" : "🙈"; };
  const gen = () => {
    const sets = {}; $$("[data-set]", card).forEach(x => { sets[x.dataset.set] = x.checked; });
    const len = Number(card.querySelector("[data-len]").value);
    card.querySelector("[data-lenv]").textContent = len;
    pw.value = genPassword(len, sets, card.querySelector("[data-sim]").checked); pw.type = "text";
    card.querySelector("[data-eye]").textContent = "🙈"; upd();
  };
  card.querySelector("[data-gen]").onclick = () => { card.querySelector("[data-genbox]").classList.remove("hidden"); gen(); };
  $$("[data-len], [data-set], [data-sim]", card).forEach(x => x.oninput = gen);
  if (!vs.status || !vs.status.unlocked) {
    const warn = document.createElement("div");
    warn.className = "httpwarn"; warn.style.margin = "0";
    warn.innerHTML = "Der Tresor ist gesperrt. Titel und Zuordnung lassen sich ändern – für Passwort, 2FA und Notiz bitte zuerst entsperren.";
    card.querySelector(".formgrid").before(warn);
  }
}

// ---------- Reiter „Zugangsdaten“ ----------
async function loadCredentials() {
  await vaultRefresh();
  $("crErr").textContent = "";
  const p = new URLSearchParams();
  if (vs.filter) p.set("filter", vs.filter);
  if (vs.q) p.set("q", vs.q);
  let rows, cnt;
  try { [rows, cnt] = await Promise.all([api("credentials?" + p), api("credentials/counts")]); } catch (e) { $("crErr").textContent = e.message; return; }
  const F = [["", "Alle", cnt.all, ""], ["device", "Geräte", cnt.device, "🖥️"], ["license", "Lizenzen & Portale", cnt.license, "🔑"],
             ["site", "Standorte", cnt.site, "📍"], ["contact", "Kontakte", cnt.contact, "👤"], ["general", "allgemein", cnt.general, "🔐"]];
  $("crSide").innerHTML = "<h4>Zuordnung</h4>" + F.map(([k, l, n, ic]) => `<a data-f="${k}" class="${vs.filter === k ? "on" : ""}">${ic ? `<span class="ti sm">${ic}</span>` : ""}${l}<span class="n">${n}</span></a>`).join("") +
    `<h4>Mit 2FA</h4><a data-f="totp" class="${vs.filter === "totp" ? "on" : ""}">2FA-Codes<span class="n">${cnt.totp}</span></a>` +
    `<h4>Hinweise</h4><a data-f="old" class="${vs.filter === "old" ? "on" : ""}">Passwort älter als 1 Jahr<span class="n ${cnt.old ? "warn" : ""}">${cnt.old}</span></a>`;
  $$("#crSide [data-f]").forEach(a => a.onclick = () => { vs.filter = a.dataset.f; loadCredentials(); });
  $("crMobileSel").innerHTML = F.concat([["totp", "2FA-Codes", cnt.totp], ["old", "Passwort älter als 1 Jahr", cnt.old]]).map(([k, l, n]) => `<option value="${k}">${l} · ${n}</option>`).join("");
  $("crMobileSel").value = vs.filter;
  $("crTitle").innerHTML = `Zugangsdaten <span class="muted small" style="font-weight:400">· ${rows.length}</span>`;
  const s = vs.status || {};
  $("crBanner").innerHTML = !s.initialized ? `<div class="lockbox" style="margin-bottom:12px"><div class="big">🔐</div><b>Der Tresor ist noch nicht eingerichtet.</b>
      <span class="muted small">Du legst ein Tresor-Passwort fest und bekommst einen Notfall-Schlüssel zum Ausdrucken.</span><button class="primary" data-vopen>Tresor einrichten</button></div>`
    : !s.unlocked ? `<div class="httpwarn" style="display:flex;gap:12px;align-items:center;justify-content:space-between">🔒 Der Tresor ist gesperrt – Passwörter, 2FA-Codes und Notizen
      sind verschlüsselt.<button class="primary" data-vopen>${s.invited && !s.member ? "Einladung annehmen" : "Entsperren"}</button></div>` : "";
  const ob = $("crBanner").querySelector("[data-vopen]"); if (ob) ob.onclick = () => vaultOpen();
  $("crList").innerHTML = rows.map(c => credHtml(c)).join("") ||
    `<p class="emptyrow">${vs.filter || vs.q ? "Keine Zugänge für diese Auswahl." : "Noch keine Zugangsdaten. Mit „＋ Zugang“ z. B. den Router-Admin anlegen."}</p>`;
  bindCreds($("crList"), rows, loadCredentials);
}
window.loadCredentials = loadCredentials;
$("crQ").oninput = debounce(() => { vs.q = $("crQ").value.trim(); loadCredentials(); });
$("crMobileSel").onchange = () => { vs.filter = $("crMobileSel").value; loadCredentials(); };
$("crNew").onclick = () => {
  if (vs.status && !vs.status.unlocked) return vaultOpen(() => credForm(null, loadCredentials));
  credForm(null, loadCredentials);
};

// ---------- Zugänge an Gerät, Lizenz, Standort ----------
async function credPanel(el, ownerType, ownerId) {
  if (!isAdmin() || !el) return;
  let rows;
  try { rows = await api(`credentials?owner_type=${ownerType}&owner_id=${ownerId}`); } catch (e) { el.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  await vaultRefresh();
  const s = vs.status || {};
  const reload = () => credPanel(el, ownerType, ownerId);
  el.innerHTML = `<div class="toolbar" style="margin-bottom:6px"><h3 style="margin:0 !important">Zugangsdaten (${rows.length})</h3><button class="mini" data-cadd title="Zugang hinzufügen">＋</button></div>
    ${rows.map(c => credHtml(c, { hideOwner: true })).join("") || '<p class="muted small" style="margin:0">Keine Zugangsdaten hinterlegt.</p>'}
    ${s.initialized && !s.unlocked && rows.length ? '<button class="primary" data-vopen style="width:100%;margin-top:10px">🔒 Tresor entsperren</button>' : ""}`;
  el.classList.add("credpanel");
  const ob = el.querySelector("[data-vopen]"); if (ob) ob.onclick = () => vaultOpen();
  el.querySelector("[data-cadd]").onclick = () => {
    const open = () => credForm(null, reload, { owner_type: ownerType, owner_id: ownerId });
    if (!s.unlocked) vaultOpen(open); else open();
  };
  bindCreds(el, rows, reload, { owner_type: ownerType, owner_id: ownerId });
}
window.credPanel = credPanel;

async function licenseKeyRow(el, lic) {
  if (!isAdmin() || !el) { if (el) el.innerHTML = '<span class="tag lock">🔒 nur mit Vollzugriff</span>'; return; }
  el.innerHTML = `${lic.has_key ? '<span class="mask" data-lk>••••-••••-••••</span>' : '<span class="muted">–</span>'}
    <span class="row" style="gap:4px;display:inline-flex;margin-left:8px">${lic.has_key ? '<button class="mini" data-lks title="anzeigen">👁</button><button class="mini" data-lkc title="kopieren">⧉</button>' : ""}
    <button class="mini" data-lke>${lic.has_key ? "ändern" : "＋ hinterlegen"}</button></span>`;
  const show = el.querySelector("[data-lks]"), cp = el.querySelector("[data-lkc]");
  if (show) show.onclick = () => withVault(async () => {
    const span = el.querySelector("[data-lk]");
    if (show.dataset.on) { span.textContent = "••••-••••-••••"; span.className = "mask"; show.textContent = "👁"; delete show.dataset.on; return; }
    const r = await api(`licenses/${lic.id}/key/reveal`, { method: "POST", body: { purpose: "show" } });
    span.textContent = r.value; span.className = "mono"; show.textContent = "🙈"; show.dataset.on = "1";
    setTimeout(() => { if (show.dataset.on) show.click(); }, 30000);
  });
  if (cp) cp.onclick = () => withVault(async () => {
    const r = await api(`licenses/${lic.id}/key/reveal`, { method: "POST", body: { purpose: "copy" } });
    await copyText(r.value); flash(cp);
  });
  el.querySelector("[data-lke]").onclick = () => {
    const form = () => openForm({ title: `Lizenzschlüssel · ${lic.name}`, narrow: true,
      fields: [{ k: "key", label: "Lizenzschlüssel 🔒", type: "textarea", mono: true, rows: 3, span2: true,
                 ph: lic.has_key ? "leer speichern = Schlüssel entfernen" : "z. B. XXXXX-XXXXX-XXXXX-XXXXX-XXXXX" }],
      save: async (v) => { await api(`licenses/${lic.id}/key`, { method: "PUT", body: { key: v.key } }); lic.has_key = !!v.key.trim(); licenseKeyRow(el, lic); } });
    if (!vs.status || !vs.status.unlocked) vaultOpen(form); else form();
  };
}
window.licenseKeyRow = licenseKeyRow;

// ---------- Verwaltung → Tresor ----------
async function loadVaultAdmin() {
  const s = await vaultRefresh();
  const m = await api("vault/members");
  const me = state.me.id;
  $("vaMembers").innerHTML = `<thead><tr><th>Benutzer</th><th>Seit</th><th>Zuletzt geöffnet</th><th></th></tr></thead><tbody>` +
    m.members.map(x => `<tr><td><b>${esc(x.name)}</b>${x.user_id === me ? ' <span class="tag boss">du</span>' : ""}</td><td>${fmtDT(x.since).slice(0, 8)}</td>
      <td>${x.last_used ? fmtDT(x.last_used) : "–"}</td><td class="num">${x.user_id === me ? '<button class="mini" data-vpw>Passwort ändern</button>'
        : `<button class="mini danger" data-vrm="${x.user_id}" data-name="${esc(x.name)}">Entziehen</button>`}</td></tr>`).join("") +
    m.invites.map(x => `<tr><td><b>${esc(x.name)}</b> <span class="tag ${x.expired ? "bad" : "warn"}">${x.expired ? "Einladung abgelaufen" : "Einladung offen"}</span></td>
      <td colspan="2" class="muted">${x.expired ? "" : "Code gültig bis " + fmtDT(x.expires)}</td><td class="num"><button class="mini danger" data-vinv="${x.user_id}">Zurückziehen</button></td></tr>`).join("") +
    (m.members.length || m.invites.length ? "" : '<tr><td colspan="4" class="emptyrow">Der Tresor ist noch nicht eingerichtet.</td></tr>') + "</tbody>";
  $("vaInvite").disabled = !s || !s.initialized || !m.candidates.length;
  $("vaInvite").title = !m.candidates.length ? "Alle Benutzer mit Vollzugriff haben schon Zugang oder eine Einladung" : "";
  $("vaTimeout").value = String(s ? s.timeout_min : 15);
  $("vaRecovery").textContent = m.recovery ? `Erzeugt am ${fmtDT(m.recovery.since)}${m.recovery.by ? " von " + m.recovery.by : ""}. ${m.recovery.last_used ? "Zuletzt benutzt am " + fmtDT(m.recovery.last_used) + "." : "Nie benutzt."}` : "–";
  $("vaRenew").disabled = !m.recovery;
  $("vaCounts").textContent = `${m.counts.credentials} Zugänge · ${m.counts.totp} mit 2FA · ${m.counts.license_keys} Lizenzschlüssel`;
  $$("#vaMembers [data-vrm]").forEach(b => b.onclick = async () => {
    if (!confirm(`${b.dataset.name} den Zugang zum Tresor entziehen?\n\nWichtig: Passwörter, die die Person schon kannte, bitte ändern.`)) return;
    try { await api(`vault/members/${b.dataset.vrm}`, { method: "DELETE" }); loadVaultAdmin(); } catch (e) { $("vaErr").textContent = e.message; }
  });
  $$("#vaMembers [data-vinv]").forEach(b => b.onclick = async () => {
    try { await api(`vault/invite/${b.dataset.vinv}`, { method: "DELETE" }); loadVaultAdmin(); } catch (e) { $("vaErr").textContent = e.message; }
  });
  const pwb = $("vaMembers").querySelector("[data-vpw]");
  if (pwb) pwb.onclick = () => openForm({ title: "Tresor-Passwort ändern", narrow: true,
    fields: [{ k: "old", label: "Bisheriges Tresor-Passwort", type: "password" }, ...pwPair("Neues Tresor-Passwort")],
    save: async (v) => { const pw = checkPair(v); await api("vault/password", { method: "POST", body: { old_password: v.old, new_password: pw } }); okMsg($("vaErr"), "Tresor-Passwort geändert."); } });
  $("vaInvite").onclick = () => vaultOpen(() => openForm({ title: "Für den Tresor freischalten", narrow: true,
    fields: [{ k: "user_id", label: "Benutzer (mit Vollzugriff)", type: "select", int: true, options: m.candidates.map(c => [c.id, c.name]) }],
    save: async (v) => {
      const r = await api("vault/invite", { method: "POST", body: v });
      setTimeout(() => {
        $("sheet").innerHTML = `<div class="card narrow"><div class="toolbar"><h2>Einladungscode für ${esc(r.name)}</h2></div>
          <div class="rkey">${esc(r.code)}</div>
          <p class="small" style="margin:0">Gib den Code ${esc(r.name)} am besten am Telefon oder persönlich – nicht in derselben Mail wie die Login-Daten.
            ${esc(r.name)} meldet sich an, klickt oben auf <b>🔒 Tresor → Einladung annehmen</b> und legt ein eigenes Tresor-Passwort fest.
            Gültig bis ${fmtDT(r.expires)}. Der Code wird nur jetzt angezeigt.</p>
          <div class="row"><button data-copy>⧉ Kopieren</button><button class="primary" data-x>Fertig</button></div></div>`;
        $("sheet").classList.remove("hidden");
        $("sheet").querySelector("[data-copy]").onclick = (e) => copyText(r.code).then(() => flash(e.target, "✓ Kopiert"));
        $("sheet").querySelector("[data-x]").onclick = () => { closeSheet(); loadVaultAdmin(); };
      }, 0);
    } }));
  $("vaRenew").onclick = () => vaultOpen(async () => {
    if (!confirm("Neuen Notfall-Schlüssel erzeugen?\n\nDer bisherige wird sofort ungültig – den neuen bitte gleich ausdrucken und den alten vernichten.")) return;
    try { const r = await api("vault/recovery/renew", { method: "POST" }); showRecoveryKey(r.recovery_key, "Neuer Notfall-Schlüssel", loadVaultAdmin); }
    catch (e) { $("vaErr").textContent = e.message; }
  });
}
window.loadVaultAdmin = loadVaultAdmin;
$("vaTimeout").onchange = async () => {
  try { await api("vault/settings", { method: "PATCH", body: { timeout_min: Number($("vaTimeout").value) } }); okMsg($("vaSetErr"), "Gespeichert."); vaultRefresh(); }
  catch (e) { $("vaSetErr").textContent = e.message; }
};
// Status ab und zu abgleichen (z. B. Auto-Sperre auf dem Server)
setInterval(() => { if (state.me && isAdmin() && !document.hidden) vaultRefresh(); }, 60000);
