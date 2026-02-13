import os
import sqlite3
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, g, jsonify, render_template, request

app = Flask(__name__)

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "backup_grabber.db")
KEYS_DIR = os.path.join(DATA_DIR, "keys")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")

for d in [DATA_DIR, KEYS_DIR, BACKUPS_DIR]:
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
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            hostname    TEXT NOT NULL,
            port        INTEGER NOT NULL DEFAULT 22,
            username    TEXT NOT NULL,
            remote_path TEXT NOT NULL,
            ssh_key_id  TEXT,
            schedule    TEXT,
            created_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ssh_keys (
            id         TEXT PRIMARY KEY,
            label      TEXT NOT NULL,
            filename   TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS backup_history (
            id         TEXT PRIMARY KEY,
            host_id    TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status     TEXT NOT NULL DEFAULT 'running',
            size_bytes INTEGER,
            message    TEXT,
            FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
        );
    """)
    db.close()


# ── Rsync engine ──────────────────────────────────────────────────────

def run_backup(host_id):
    """Pull files from a remote host via rsync."""
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

    dest_dir = os.path.join(BACKUPS_DIR, host["name"], now.replace(":", "-"))
    os.makedirs(dest_dir, exist_ok=True)

    # Find the latest previous backup for hard-link-dest
    host_backup_dir = os.path.join(BACKUPS_DIR, host["name"])
    prev_backups = sorted(
        [d for d in Path(host_backup_dir).iterdir() if d.is_dir() and str(d) != dest_dir],
        key=lambda p: p.name,
        reverse=True,
    )

    ssh_args = f"-p {host['port']} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
    if host["ssh_key_id"]:
        key = db.execute("SELECT * FROM ssh_keys WHERE id = ?", (host["ssh_key_id"],)).fetchone()
        if key:
            key_path = os.path.join(KEYS_DIR, key["filename"])
            ssh_args += f" -i {key_path}"

    remote = f"{host['username']}@{host['hostname']}:{host['remote_path']}"
    cmd = [
        "rsync", "-az", "--delete",
        "-e", f"ssh {ssh_args}",
    ]

    if prev_backups:
        cmd += ["--link-dest", str(prev_backups[0])]

    cmd += [remote, dest_dir + "/"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        # Calculate size
        size = sum(f.stat().st_size for f in Path(dest_dir).rglob("*") if f.is_file())
        if result.returncode == 0:
            db.execute(
                "UPDATE backup_history SET finished_at=?, status='success', size_bytes=? WHERE id=?",
                (datetime.utcnow().isoformat(), size, backup_id),
            )
        else:
            db.execute(
                "UPDATE backup_history SET finished_at=?, status='failed', size_bytes=?, message=? WHERE id=?",
                (datetime.utcnow().isoformat(), size, result.stderr[:500], backup_id),
            )
    except subprocess.TimeoutExpired:
        db.execute(
            "UPDATE backup_history SET finished_at=?, status='failed', message='Timed out after 1 hour' WHERE id=?",
            (datetime.utcnow().isoformat(), backup_id),
        )
    except Exception as e:
        db.execute(
            "UPDATE backup_history SET finished_at=?, status='failed', message=? WHERE id=?",
            (datetime.utcnow().isoformat(), str(e)[:500], backup_id),
        )
    finally:
        db.commit()
        db.close()


# ── Scheduler helpers ─────────────────────────────────────────────────

def load_schedules():
    """Load all host schedules into APScheduler on startup."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    hosts = db.execute("SELECT id, schedule FROM hosts WHERE schedule IS NOT NULL AND schedule != ''").fetchall()
    for host in hosts:
        _add_schedule(host["id"], host["schedule"])
    db.close()


def _add_schedule(host_id, cron_expr):
    """Add a cron job for a host. cron_expr format: 'minute hour day month day_of_week'"""
    job_id = f"backup_{host_id}"
    # Remove existing job if any
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    try:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return
        scheduler.add_job(
            run_backup,
            "cron",
            args=[host_id],
            id=job_id,
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
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
    rows = get_db().execute("SELECT * FROM hosts ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/hosts", methods=["POST"])
def create_host():
    data = request.json
    host_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO hosts (id, name, hostname, port, username, remote_path, ssh_key_id, schedule, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            host_id,
            data["name"],
            data["hostname"],
            data.get("port", 22),
            data["username"],
            data["remote_path"],
            data.get("ssh_key_id") or None,
            data.get("schedule") or None,
            now,
        ),
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
        "UPDATE hosts SET name=?, hostname=?, port=?, username=?, remote_path=?, ssh_key_id=?, schedule=? WHERE id=?",
        (
            data["name"],
            data["hostname"],
            data.get("port", 22),
            data["username"],
            data["remote_path"],
            data.get("ssh_key_id") or None,
            data.get("schedule") or None,
            host_id,
        ),
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


# ── API: SSH Keys ─────────────────────────────────────────────────────

@app.route("/api/keys", methods=["GET"])
def list_keys():
    rows = get_db().execute("SELECT id, label, created_at FROM ssh_keys ORDER BY label").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/keys", methods=["POST"])
def upload_key():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    label = request.form.get("label", f.filename)
    key_id = str(uuid.uuid4())
    filename = f"{key_id}.pem"
    path = os.path.join(KEYS_DIR, filename)
    f.save(path)
    os.chmod(path, 0o600)
    db = get_db()
    db.execute(
        "INSERT INTO ssh_keys (id, label, filename, created_at) VALUES (?, ?, ?, ?)",
        (key_id, label, filename, datetime.utcnow().isoformat()),
    )
    db.commit()
    return jsonify({"id": key_id}), 201


@app.route("/api/keys/<key_id>", methods=["DELETE"])
def delete_key(key_id):
    db = get_db()
    key = db.execute("SELECT filename FROM ssh_keys WHERE id = ?", (key_id,)).fetchone()
    if key:
        path = os.path.join(KEYS_DIR, key["filename"])
        if os.path.exists(path):
            os.remove(path)
    db.execute("DELETE FROM ssh_keys WHERE id = ?", (key_id,))
    db.commit()
    return jsonify({"ok": True})


# ── API: Backups ──────────────────────────────────────────────────────

@app.route("/api/backup/<host_id>", methods=["POST"])
def trigger_backup(host_id):
    """Trigger an immediate backup for a host (runs in background thread)."""
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
            "WHERE host_id = ? ORDER BY started_at DESC LIMIT 50",
            (host_id,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT h.*, hosts.name as host_name FROM backup_history h "
            "JOIN hosts ON h.host_id = hosts.id "
            "ORDER BY started_at DESC LIMIT 100"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# ── Frontend ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Startup ───────────────────────────────────────────────────────────

init_db()
load_schedules()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
