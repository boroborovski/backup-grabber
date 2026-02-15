// ── Tab switching ────────────────────────────────────────────────────
document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".page").forEach(s => s.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "history") loadHistory();
    if (btn.dataset.tab === "explorer") browseBackups("");
  });
});

// ── Toast notifications ───────────────────────────────────────────────
function toast(msg, type = "info") {
  const container = document.getElementById("toast-container");
  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  t.textContent = msg;
  container.appendChild(t);
  requestAnimationFrame(() => t.classList.add("show"));
  setTimeout(() => {
    t.classList.remove("show");
    setTimeout(() => t.remove(), 300);
  }, 3500);
}

// ── Helpers ──────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  try {
    const res = await fetch(path, opts);
    const data = await res.json();
    if (!res.ok) {
      toast(data.error || data.message || `Error ${res.status}`, "error");
      return null;
    }
    return data;
  } catch (e) {
    toast("Network error – is the server running?", "error");
    return null;
  }
}

function formatSize(bytes) {
  if (!bytes) return "--";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB";
  return (bytes / 1073741824).toFixed(2) + " GB";
}

function formatDate(iso) {
  if (!iso) return "--";
  return new Date(iso + "Z").toLocaleString();
}

function formatRelative(iso) {
  if (!iso) return null;
  const diff = Date.now() - new Date(iso + "Z").getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function esc(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

const SCHEDULE_LABELS = {
  "0 * * * *":   "Every hour",
  "0 */6 * * *": "Every 6 hours",
  "0 0 * * *":   "Daily at midnight",
  "0 2 * * *":   "Daily at 2:00 AM",
  "0 3 * * 1":   "Weekly (Mon 3 AM)",
  "0 4 1 * *":   "Monthly (1st at 4 AM)",
};

function scheduleLabel(cron) {
  if (!cron) return "Manual";
  return SCHEDULE_LABELS[cron] || cron;
}

// ── Schedule preset toggle ───────────────────────────────────────────
function onScheduleChange() {
  const sel = document.getElementById("host-schedule-preset");
  const custom = document.getElementById("custom-cron-field");
  custom.style.display = sel.value === "custom" ? "block" : "none";
  if (sel.value !== "custom") {
    document.getElementById("host-schedule-custom").value = "";
  }
}

function getScheduleValue() {
  const preset = document.getElementById("host-schedule-preset").value;
  if (preset === "custom") return document.getElementById("host-schedule-custom").value.trim() || null;
  return preset || null;
}

// ── Live polling ─────────────────────────────────────────────────────
let pollingTimer = null;
let runningHostIds = new Set();

function startPolling() {
  if (pollingTimer) return;
  pollingTimer = setInterval(pollRunning, 3000);
}

function stopPolling() {
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

async function pollRunning() {
  let data;
  try {
    const res = await fetch("/api/history");
    data = await res.json();
  } catch (_) {
    return;
  }

  const stillRunning = new Set(
    data.filter(r => r.status === "running").map(r => r.host_id)
  );

  // Detect jobs that just finished
  let needsHostRefresh = false;
  for (const id of runningHostIds) {
    if (!stillRunning.has(id)) {
      needsHostRefresh = true;
      const row = data.find(r => r.host_id === id);
      const name = row?.host_name || id;
      const status = row?.status;
      if (status === "success") toast(`✓ Backup finished: ${name}`, "success");
      else if (status === "failed") toast(`✗ Backup failed: ${name}`, "error");
    }
  }

  runningHostIds = stillRunning;

  if (needsHostRefresh) {
    loadHosts();
  } else {
    // Update running badges in-place without a full re-render
    document.querySelectorAll("[data-running-hostid]").forEach(el => {
      if (!stillRunning.has(el.dataset.runningHostid)) {
        loadHosts();
      }
    });
  }

  // Keep history tab live while backups are running
  if (document.getElementById("history").classList.contains("active")) {
    loadHistory();
  }

  if (stillRunning.size === 0) stopPolling();
}

// ── Hosts ────────────────────────────────────────────────────────────
let hostsCache = [];

async function loadHosts() {
  const data = await api("/api/hosts");
  if (!data) return;
  hostsCache = data;
  renderHosts();

  const anyRunning = hostsCache.some(h => h.last_status === "running");
  if (anyRunning) {
    runningHostIds = new Set(hostsCache.filter(h => h.last_status === "running").map(h => h.id));
    startPolling();
  }
}

function hostCardHtml(h) {
  const paths = JSON.parse(h.remote_paths);
  const isRunning = h.last_status === "running";
  let lastBadge = "";
  if (isRunning) {
    lastBadge = `<span class="last-run-info" data-running-hostid="${h.id}">
      <span class="status status-running"><span class="spinner-inline"></span> running</span>
    </span>`;
  } else if (h.last_status) {
    const rel = formatRelative(h.last_run);
    lastBadge = `<span class="last-run-info">
      <span class="status status-${h.last_status}">${h.last_status}</span>
      ${rel ? `<span class="last-run-time">${rel}</span>` : ""}
    </span>`;
  } else {
    lastBadge = `<span class="last-run-info"><span class="never-run">Never backed up</span></span>`;
  }
  return `
  <div class="host-card${isRunning ? " host-card-running" : ""}">
    <div class="host-card-top">
      <div class="host-card-title">
        <h3>${esc(h.name)}</h3>
        ${lastBadge}
      </div>
      <div class="host-card-actions">
        <button class="btn btn-primary btn-sm" onclick="triggerBackup(event, '${h.id}')"${isRunning ? " disabled" : ""}>
          ${isRunning ? '<span class="spinner-inline"></span> Running…' : "Backup Now"}
        </button>
        <button class="btn btn-sm btn-test" onclick="testConnection('${h.id}', this)">Test SSH</button>
        <button class="btn btn-sm" onclick="editHost('${h.id}')">Edit</button>
        <button class="btn btn-sm btn-danger" onclick="deleteHost('${h.id}')">Delete</button>
      </div>
    </div>
    <div class="host-meta">
      <span>${esc(h.username)}@${esc(h.hostname)}:${h.port}</span>
      <span>${scheduleLabel(h.schedule)}</span>
      <span>Keep: ${h.keep_last ? "last " + h.keep_last : "all"}</span>
      ${h.last_size ? `<span>${formatSize(h.last_size)}</span>` : ""}
    </div>
    <div class="tag-paths">
      ${paths.map(p => `<span class="tag">${esc(p)}</span>`).join("")}
    </div>
  </div>`;
}

function renderHosts() {
  const el = document.getElementById("host-list");
  if (!hostsCache.length) {
    el.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/>
          <circle cx="6" cy="6" r="1"/><circle cx="6" cy="18" r="1"/>
        </svg>
        <p>No hosts configured yet. Add one to get started.</p>
      </div>`;
    return;
  }

  // Group hosts: named groups first (sorted), then ungrouped
  const groups = {};
  const ungrouped = [];
  for (const h of hostsCache) {
    const g = h.grp ? h.grp.trim() : "";
    if (g) {
      if (!groups[g]) groups[g] = [];
      groups[g].push(h);
    } else {
      ungrouped.push(h);
    }
  }

  const sortedGroupNames = Object.keys(groups).sort((a, b) => a.localeCompare(b));
  let html = "";

  for (const gname of sortedGroupNames) {
    html += `<div class="host-group">
      <div class="host-group-header"><span class="host-group-label">${esc(gname)}</span></div>
      <div class="card-grid">${groups[gname].map(hostCardHtml).join("")}</div>
    </div>`;
  }

  if (ungrouped.length) {
    const wrap = sortedGroupNames.length ? `<div class="host-group">
      <div class="host-group-header"><span class="host-group-label host-group-ungrouped">Ungrouped</span></div>
      <div class="card-grid">${ungrouped.map(hostCardHtml).join("")}</div>
    </div>` : `<div class="card-grid">${ungrouped.map(hostCardHtml).join("")}</div>`;
    html += wrap;
  }

  el.innerHTML = html;
}

// ── Test SSH connection ───────────────────────────────────────────────
async function testConnection(id, btn) {
  const orig = btn.textContent;
  btn.textContent = "Testing…";
  btn.disabled = true;
  const data = await api(`/api/test/${id}`, { method: "POST" });
  btn.textContent = orig;
  btn.disabled = false;
  if (!data) return;
  if (data.ok) {
    toast("SSH connection successful", "success");
  } else {
    toast("Connection failed: " + data.message, "error");
  }
}

function showHostForm(host) {
  document.getElementById("host-form-title").textContent = host ? "Edit Host" : "Add Host";
  document.getElementById("host-id").value = host ? host.id : "";
  document.getElementById("host-name").value = host ? host.name : "";
  document.getElementById("host-hostname").value = host ? host.hostname : "";
  document.getElementById("host-port").value = host ? host.port : 22;
  document.getElementById("host-username").value = host ? host.username : "";
  document.getElementById("host-ssh-key").value  = host ? (host.ssh_key || "/root/.ssh/id_ed25519") : "/root/.ssh/id_ed25519";
  document.getElementById("host-group").value    = host ? (host.grp || "") : "";
  document.getElementById("host-paths").value    = host ? JSON.parse(host.remote_paths).join("\n") : "";
  document.getElementById("host-keep-last").value = host ? (host.keep_last || 0) : 0;

  const preset = document.getElementById("host-schedule-preset");
  const customField = document.getElementById("custom-cron-field");
  const customInput = document.getElementById("host-schedule-custom");
  if (host && host.schedule) {
    const match = [...preset.options].find(o => o.value === host.schedule);
    if (match) {
      preset.value = host.schedule;
      customField.style.display = "none";
      customInput.value = "";
    } else {
      preset.value = "custom";
      customField.style.display = "block";
      customInput.value = host.schedule;
    }
  } else {
    preset.value = "";
    customField.style.display = "none";
    customInput.value = "";
  }

  document.getElementById("host-dialog").showModal();
}

function editHost(id) {
  const host = hostsCache.find(h => h.id === id);
  if (host) showHostForm(host);
}

async function saveHost(e) {
  e.preventDefault();
  const id = document.getElementById("host-id").value;
  const paths = document.getElementById("host-paths").value
    .split("\n").map(p => p.trim()).filter(Boolean);
  const data = {
    name: document.getElementById("host-name").value,
    hostname: document.getElementById("host-hostname").value,
    port: parseInt(document.getElementById("host-port").value),
    username: document.getElementById("host-username").value,
    ssh_key: document.getElementById("host-ssh-key").value.trim() || "/root/.ssh/id_ed25519",
    grp: document.getElementById("host-group").value.trim(),
    remote_paths: paths,
    schedule: getScheduleValue(),
    keep_last: parseInt(document.getElementById("host-keep-last").value) || 0,
  };
  const result = id
    ? await api(`/api/hosts/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
    : await api("/api/hosts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  if (!result) return;
  document.getElementById("host-dialog").close();
  toast(id ? "Host updated" : "Host added", "success");
  loadHosts();
}

async function deleteHost(id) {
  if (!confirm("Delete this host and its backup history?")) return;
  const result = await api(`/api/hosts/${id}`, { method: "DELETE" });
  if (!result) return;
  toast("Host deleted", "info");
  loadHosts();
}

async function triggerBackup(e, id) {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-inline"></span> Starting…';
  const result = await api(`/api/backup/${id}`, { method: "POST" });
  if (!result) {
    btn.disabled = false;
    btn.textContent = "Backup Now";
    return;
  }
  btn.innerHTML = '<span class="spinner-inline"></span> Running…';
  toast("Backup started", "info");
  runningHostIds.add(id);
  startPolling();
}

// ── History ──────────────────────────────────────────────────────────
async function loadHistory() {
  const data = await api("/api/history");
  if (!data) return;
  const el = document.getElementById("history-list");
  if (!data.length) {
    el.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
        </svg>
        <p>No backups yet. Trigger one from the Hosts tab.</p>
      </div>`;
    return;
  }
  el.innerHTML = `
    <table class="history-table">
      <thead><tr><th>Host</th><th>Started</th><th>Duration</th><th>Size</th><th>Status</th></tr></thead>
      <tbody>
        ${data.map(r => {
          let duration = "--";
          if (r.started_at && r.finished_at) {
            const sec = Math.round((new Date(r.finished_at + "Z") - new Date(r.started_at + "Z")) / 1000);
            duration = sec < 60 ? sec + "s" : Math.floor(sec / 60) + "m " + (sec % 60) + "s";
          } else if (r.status === "running") {
            const sec = Math.round((Date.now() - new Date(r.started_at + "Z").getTime()) / 1000);
            duration = `${sec < 60 ? sec + "s" : Math.floor(sec / 60) + "m " + (sec % 60) + "s"} …`;
          }
          return `
          <tr>
            <td style="color:var(--text);font-weight:500">${esc(r.host_name)}</td>
            <td>${formatDate(r.started_at)}</td>
            <td>${duration}</td>
            <td>${formatSize(r.size_bytes)}</td>
            <td><span class="status status-${r.status}">${r.status}</span></td>
          </tr>
          ${r.message ? `<tr><td colspan="5" class="error-msg">${esc(r.message)}</td></tr>` : ""}`;
        }).join("")}
      </tbody>
    </table>`;
}

// ── Explorer ─────────────────────────────────────────────────────────
const ICON_DIR  = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>';
const ICON_FILE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';

async function browseBackups(path) {
  const data = await api("/api/browse" + (path ? "/" + path : ""));
  if (!data || data.error) return;

  const bc = document.getElementById("breadcrumb");
  let bcHtml = `<a onclick="browseBackups('')">backups</a>`;
  let accumulated = "";
  for (const part of data.breadcrumb) {
    accumulated += (accumulated ? "/" : "") + part;
    const p = accumulated;
    bcHtml += `<span class="sep">/</span><a onclick="browseBackups('${esc(p)}')">${esc(part)}</a>`;
  }
  bc.innerHTML = bcHtml;

  const el = document.getElementById("explorer-list");
  if (!data.items.length) {
    el.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
        </svg>
        <p>This folder is empty.</p>
      </div>`;
    return;
  }

  el.innerHTML = `<div class="file-list">
    ${data.items.map(item => {
      const fullPath = data.path ? data.path + "/" + item.name : item.name;
      if (item.type === "dir") {
        return `<div class="file-row dir" onclick="browseBackups('${esc(fullPath)}')">
          ${ICON_DIR}
          <span class="file-name">${esc(item.name)}</span>
          <span class="file-detail">${item.file_count} files</span>
          <span class="file-detail">${formatSize(item.size)}</span>
        </div>`;
      } else {
        return `<a class="file-row" href="/api/browse/${esc(fullPath)}" download>
          ${ICON_FILE}
          <span class="file-name">${esc(item.name)}</span>
          <span class="file-detail">${formatSize(item.size)}</span>
        </a>`;
      }
    }).join("")}
  </div>`;
}

// ── Init ─────────────────────────────────────────────────────────────
loadHosts();
