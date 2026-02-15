import json
import os
import sqlite3
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, g, jsonify, render_template, request, send_from_directory

app = Flask(__name__)

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "backup_grabber.db")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")

for d in [DATA_DIR, BACKUPS_DIR]:
    os.makedirs(d, exist_ok=True)

scheduler = BackgroundScheduler()
scheduler.start()


# ── Database ──────────────────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS hosts (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            hostname     TEXT NOT NULL,
            port         INTEGER NOT NULL DEFAULT 22,
            username     TEXT NOT NULL,
            remote_paths TEXT NOT NULL,
            schedule     TEXT,
            keep_last    INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS backup_history (
            id          TEXT PRIMARY KEY,
            host_id     TEXT NOT NULL,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            status      TEXT NOT NULL DEFAULT 'running',
            size_bytes  INTEGER,
            message     TEXT,
            FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
        );
    """)
    db.close()


# ── Rsync engine ──────────────────────────────────────────────────────

def run_backup(host_id):
    """Pull files from a remote host via rsync (one run per path)."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    host = db.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()
    if not host:
        db.close()
        return

    backup_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO backup_history (id, host_id, started_at, status) VALUES (?, ?, ?, 'running')",
        (backup_id, host_id, now),
    )
    db.commit()

    paths = json.loads(host["remote_paths"])
    timestamp = now.replace(":", "-")
    host_backup_dir = os.path.join(BACKUPS_DIR, host["name"])
    dest_root = os.path.join(host_backup_dir, timestamp)
    os.makedirs(dest_root, exist_ok=True)

    errors = []
    total_size = 0

    for remote_path in paths:
        remote_path = remote_path.strip()
        if not remote_path:
            continue

        # Each path gets its own subdirectory under the timestamp
        path_label = remote_path.strip("/").replace("/", "_") or "root"
        dest_dir = os.path.join(dest_root, path_label)
        os.makedirs(dest_dir, exist_ok=True)

        # Find previous backup for hard-link-dest
        link_dest_args = []
        if os.path.isdir(host_backup_dir):
            prev_backups = sorted(
                [d for d in Path(host_backup_dir).iterdir()
                 if d.is_dir() and str(d) != dest_root and (d / path_label).is_dir()],
                key=lambda p: p.name,
                reverse=True,
            )
            if prev_backups:
                link_dest_args = ["--link-dest", str(prev_backups[0] / path_label)]

        ssh_args = f"-p {host['port']} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        remote = f"{host['username']}@{host['hostname']}:{remote_path}"
        cmd = ["rsync", "-az", "--delete", "-e", f"ssh {ssh_args}"] + link_dest_args + [remote, dest_dir + "/"]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                errors.append(f"{remote_path}: {result.stderr.strip()[:200]}")
        except subprocess.TimeoutExpired:
            errors.append(f"{remote_path}: timed out after 1 hour")
        except Exception as e:
            errors.append(f"{remote_path}: {str(e)[:200]}")

    # Calculate total size
    total_size = sum(f.stat().st_size for f in Path(dest_root).rglob("*") if f.is_file())

    if errors:
        db.execute(
            "UPDATE backup_history SET finished_at=?, status='failed', size_bytes=?, message=? WHERE id=?",
            (datetime.utcnow().isoformat(), total_size, "\n".join(errors)[:500], backup_id),
        )
    else:
        db.execute(
            "UPDATE backup_history SET finished_at=?, status='success', size_bytes=? WHERE id=?",
            (datetime.utcnow().isoformat(), total_size, backup_id),
        )
    db.commit()

    # Enforce retention policy
    keep_last = host["keep_last"]
    if keep_last and keep_last > 0 and os.path.isdir(host_backup_dir):
        _enforce_retention(host_backup_dir, keep_last, host_id, db)

    db.close()


def _enforce_retention(host_backup_dir, keep_last, host_id, db):
    """Delete oldest backup snapshots beyond the keep_last limit."""
    snapshots = sorted(
        [d for d in Path(host_backup_dir).iterdir() if d.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    to_delete = snapshots[keep_last:]
    for snap in to_delete:
        import shutil
        shutil.rmtree(snap, ignore_errors=True)
    # Also trim history records beyond the limit
    if to_delete:
        db.execute(
            "DELETE FROM backup_history WHERE host_id = ? AND id NOT IN "
            "(SELECT id FROM backup_history WHERE host_id = ? ORDER BY started_at DESC LIMIT ?)",
            (host_id, host_id, keep_last),
        )
        db.commit()


# ── Scheduler helpers ─────────────────────────────────────────────────

def load_schedules():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    hosts = db.execute("SELECT id, schedule FROM hosts WHERE schedule IS NOT NULL AND schedule != ''").fetchall()
    for host in hosts:
        _add_schedule(host["id"], host["schedule"])
    db.close()


def _add_schedule(host_id, cron_expr):
    job_id = f"backup_{host_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    try:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return
        scheduler.add_job(
            run_backup, "cron", args=[host_id], id=job_id,
            minute=parts[0], hour=parts[1], day=parts[2],
            month=parts[3], day_of_week=parts[4],
        )
    except Exception:
        pass


def _remove_schedule(host_id):
    job_id = f"backup_{host_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


# ── API: Hosts ────────────────────────────────────────────────────────

@app.route("/api/hosts", methods=["GET"])
def list_hosts():
    rows = get_db().execute("""
        SELECT h.*,
               bh.status     AS last_status,
               bh.started_at AS last_run,
               bh.size_bytes AS last_size
        FROM hosts h
        LEFT JOIN backup_history bh
               ON bh.id = (
                   SELECT id FROM backup_history
                   WHERE host_id = h.id
                   ORDER BY started_at DESC LIMIT 1
               )
        ORDER BY h.name
    """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/hosts", methods=["POST"])
def create_host():
    data = request.json
    host_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        "INSERT INTO hosts (id, name, hostname, port, username, remote_paths, schedule, keep_last, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (host_id, data["name"], data["hostname"], data.get("port", 22),
         data["username"], json.dumps(data["remote_paths"]),
         data.get("schedule") or None, data.get("keep_last", 0),
         datetime.utcnow().isoformat()),
    )
    db.commit()
    if data.get("schedule"):
        _add_schedule(host_id, data["schedule"])
    return jsonify({"id": host_id}), 201


@app.route("/api/hosts/<host_id>", methods=["PUT"])
def update_host(host_id):
    data = request.json
    db = get_db()
    db.execute(
        "UPDATE hosts SET name=?, hostname=?, port=?, username=?, remote_paths=?, schedule=?, keep_last=? WHERE id=?",
        (data["name"], data["hostname"], data.get("port", 22),
         data["username"], json.dumps(data["remote_paths"]),
         data.get("schedule") or None, data.get("keep_last", 0), host_id),
    )
    db.commit()
    _remove_schedule(host_id)
    if data.get("schedule"):
        _add_schedule(host_id, data["schedule"])
    return jsonify({"ok": True})


@app.route("/api/hosts/<host_id>", methods=["DELETE"])
def delete_host(host_id):
    db = get_db()
    db.execute("DELETE FROM hosts WHERE id = ?", (host_id,))
    db.commit()
    _remove_schedule(host_id)
    return jsonify({"ok": True})


# ── API: Backups ──────────────────────────────────────────────────────

@app.route("/api/test/<host_id>", methods=["POST"])
def test_connection(host_id):
    """Quick SSH connectivity check (no backup data transferred)."""
    host = get_db().execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()
    if not host:
        return jsonify({"ok": False, "message": "Host not found"}), 404
    cmd = [
        "ssh", "-q",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-p", str(host["port"]),
        f"{host['username']}@{host['hostname']}",
        "echo ok",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        if result.returncode == 0:
            return jsonify({"ok": True, "message": "Connection successful"})
        msg = result.stderr.strip()[:300] or "Connection refused or auth failed"
        return jsonify({"ok": False, "message": msg})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "message": "Connection timed out"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)[:300]})


@app.route("/api/backup/<host_id>", methods=["POST"])
def trigger_backup(host_id):
    import threading
    t = threading.Thread(target=run_backup, args=(host_id,), daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Backup started"})


@app.route("/api/history", methods=["GET"])
def backup_history():
    host_id = request.args.get("host_id")
    db = get_db()
    if host_id:
        rows = db.execute(
            "SELECT h.*, hosts.name as host_name FROM backup_history h "
            "JOIN hosts ON h.host_id = hosts.id "
            "WHERE host_id = ? ORDER BY started_at DESC LIMIT 50", (host_id,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT h.*, hosts.name as host_name FROM backup_history h "
            "JOIN hosts ON h.host_id = hosts.id "
            "ORDER BY started_at DESC LIMIT 100"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# ── API: Browse backups ───────────────────────────────────────────────

@app.route("/api/browse")
@app.route("/api/browse/<path:subpath>")
def browse_backups(subpath=""):
    """List contents of a backup directory. Returns folders and files."""
    target = Path(BACKUPS_DIR) / subpath
    # Prevent path traversal
    try:
        target.resolve().relative_to(Path(BACKUPS_DIR).resolve())
    except ValueError:
        return jsonify({"error": "Invalid path"}), 400

    if not target.exists():
        return jsonify({"error": "Path not found"}), 404

    if target.is_file():
        return send_from_directory(target.parent, target.name, as_attachment=True)

    items = []
    for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name)):
        if entry.is_dir():
            # Count files and total size inside
            file_count = sum(1 for _ in entry.rglob("*") if _.is_file())
            dir_size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            items.append({
                "name": entry.name,
                "type": "dir",
                "file_count": file_count,
                "size": dir_size,
            })
        else:
            items.append({
                "name": entry.name,
                "type": "file",
                "size": entry.stat().st_size,
                "modified": datetime.fromtimestamp(entry.stat().st_mtime).isoformat(),
            })

    # Build breadcrumb parts
    parts = [p for p in subpath.split("/") if p] if subpath else []
    return jsonify({"path": subpath, "breadcrumb": parts, "items": items})


# ── Frontend ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Startup ───────────────────────────────────────────────────────────

init_db()
load_schedules()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
