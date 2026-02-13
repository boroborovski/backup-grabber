// ── Tab switching ────────────────────────────────────────────────────
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(s => s.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "history") loadHistory();
  });
});

// ── Helpers ──────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  return res.json();
}

function formatSize(bytes) {
  if (!bytes) return "-";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB";
  return (bytes / 1073741824).toFixed(2) + " GB";
}

function formatDate(iso) {
  if (!iso) return "-";
  return new Date(iso + "Z").toLocaleString();
}

// ── SSH Keys ─────────────────────────────────────────────────────────
let keysCache = [];

async function loadKeys() {
  keysCache = await api("/api/keys");
  renderKeys();
  populateKeySelect();
}

function renderKeys() {
  const el = document.getElementById("key-list");
  if (!keysCache.length) {
    el.innerHTML = '<div class="empty">No SSH keys uploaded yet.</div>';
    return;
  }
  el.innerHTML = keysCache.map(k => `
    <div class="card">
      <div class="card-info">
        <h3>${esc(k.label)}</h3>
        <p>Added ${formatDate(k.created_at)}</p>
      </div>
      <div class="card-actions">
        <button class="btn btn-danger btn-sm" onclick="deleteKey('${k.id}')">Delete</button>
      </div>
    </div>
  `).join("");
}

function populateKeySelect() {
  const sel = document.getElementById("host-key");
  sel.innerHTML = '<option value="">None (use agent/password)</option>' +
    keysCache.map(k => `<option value="${k.id}">${esc(k.label)}</option>`).join("");
}

async function uploadKey(e) {
  e.preventDefault();
  const fd = new FormData();
  fd.append("label", document.getElementById("key-label").value);
  fd.append("file", document.getElementById("key-file").files[0]);
  await api("/api/keys", { method: "POST", body: fd });
  document.getElementById("key-dialog").close();
  document.getElementById("key-form").reset();
  loadKeys();
}

async function deleteKey(id) {
  if (!confirm("Delete this SSH key?")) return;
  await api(`/api/keys/${id}`, { method: "DELETE" });
  loadKeys();
}

// ── Hosts ────────────────────────────────────────────────────────────
let hostsCache = [];

async function loadHosts() {
  hostsCache = await api("/api/hosts");
  renderHosts();
}

function renderHosts() {
  const el = document.getElementById("host-list");
  if (!hostsCache.length) {
    el.innerHTML = '<div class="empty">No hosts configured. Add one to get started.</div>';
    return;
  }
  el.innerHTML = hostsCache.map(h => {
    const keyLabel = keysCache.find(k => k.id === h.ssh_key_id)?.label || "none";
    return `
    <div class="card">
      <div class="card-info">
        <h3>${esc(h.name)}</h3>
        <p>${esc(h.username)}@${esc(h.hostname)}:${h.port} &mdash; ${esc(h.remote_path)}</p>
        <p>Key: ${esc(keyLabel)} ${h.schedule ? ' | Schedule: ' + esc(h.schedule) : ''}</p>
      </div>
      <div class="card-actions">
        <button class="btn btn-primary btn-sm" onclick="triggerBackup('${h.id}')">Backup Now</button>
        <button class="btn btn-sm" onclick="editHost('${h.id}')">Edit</button>
        <button class="btn btn-danger btn-sm" onclick="deleteHost('${h.id}')">Delete</button>
      </div>
    </div>`;
  }).join("");
}

function showHostForm(host) {
  document.getElementById("host-form-title").textContent = host ? "Edit Host" : "Add Host";
  document.getElementById("host-id").value = host ? host.id : "";
  document.getElementById("host-name").value = host ? host.name : "";
  document.getElementById("host-hostname").value = host ? host.hostname : "";
  document.getElementById("host-port").value = host ? host.port : 22;
  document.getElementById("host-username").value = host ? host.username : "";
  document.getElementById("host-remote-path").value = host ? host.remote_path : "";
  document.getElementById("host-key").value = host ? (host.ssh_key_id || "") : "";
  document.getElementById("host-schedule").value = host ? (host.schedule || "") : "";
  document.getElementById("host-dialog").showModal();
}

function editHost(id) {
  const host = hostsCache.find(h => h.id === id);
  if (host) showHostForm(host);
}

async function saveHost(e) {
  e.preventDefault();
  const id = document.getElementById("host-id").value;
  const data = {
    name: document.getElementById("host-name").value,
    hostname: document.getElementById("host-hostname").value,
    port: parseInt(document.getElementById("host-port").value),
    username: document.getElementById("host-username").value,
    remote_path: document.getElementById("host-remote-path").value,
    ssh_key_id: document.getElementById("host-key").value || null,
    schedule: document.getElementById("host-schedule").value || null,
  };
  if (id) {
    await api(`/api/hosts/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  } else {
    await api("/api/hosts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
  }
  document.getElementById("host-dialog").close();
  loadHosts();
}

async function deleteHost(id) {
  if (!confirm("Delete this host and its backup history?")) return;
  await api(`/api/hosts/${id}`, { method: "DELETE" });
  loadHosts();
}

async function triggerBackup(id) {
  await api(`/api/backup/${id}`, { method: "POST" });
  alert("Backup started! Check the History tab for progress.");
}

// ── History ──────────────────────────────────────────────────────────
async function loadHistory() {
  const rows = await api("/api/history");
  const el = document.getElementById("history-list");
  if (!rows.length) {
    el.innerHTML = '<div class="empty">No backups yet.</div>';
    return;
  }
  el.innerHTML = rows.map(r => `
    <div class="history-row">
      <div>
        <strong>${esc(r.host_name)}</strong>
        <span style="color:#8b949e;margin-left:.5rem">${formatDate(r.started_at)}</span>
      </div>
      <div style="display:flex;align-items:center;gap:.75rem">
        <span style="color:#8b949e">${formatSize(r.size_bytes)}</span>
        <span class="status-badge status-${r.status}">${r.status}</span>
      </div>
    </div>
    ${r.message ? `<div style="color:#f85149;font-size:.8rem;padding:0 1rem .5rem">${esc(r.message)}</div>` : ''}
  `).join("");
}

// ── XSS protection ──────────────────────────────────────────────────
function esc(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// ── Init ─────────────────────────────────────────────────────────────
loadKeys().then(loadHosts);
