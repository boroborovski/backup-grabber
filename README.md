# Backup Grabber

A simple, Docker-based web app to pull backup archives from remote hosts via SSH and rsync.

## Features

- **Web UI** - Manage hosts, SSH keys, and backups from your browser
- **Rsync + SSH** - Pull files from remote servers securely
- **Versioned backups** - Each run creates a timestamped snapshot with hard-link dedup (no wasted space for unchanged files)
- **Scheduling** - Optional cron-like schedules per host (e.g. `0 2 * * *` for daily at 2am)
- **Backup history** - Track status, size, and errors for every run

## Quick Start

```bash
docker compose up --build
```

Open [http://localhost:5000](http://localhost:5000).

## Usage

1. **Upload an SSH key** (SSH Keys tab) - upload the private key used to connect to your remote hosts
2. **Add a host** (Hosts tab) - provide hostname, user, port, remote path, and optionally assign an SSH key and a cron schedule
3. **Backup Now** - click the button to pull files immediately, or let the schedule handle it
4. **Check History** - view backup results in the History tab

## Data

All data is stored in the `/data` Docker volume:

```
/data
├── backup_grabber.db   # SQLite database
├── keys/               # SSH private keys
└── backups/            # Downloaded backups
    └── <host-name>/
        └── <timestamp>/
```

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `/data` | Where to store the database, keys, and backups |

## Tech Stack

- Python / Flask
- SQLite
- APScheduler
- Plain HTML/CSS/JS
