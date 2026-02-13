# Backup Grabber

A simple, Docker-based web app to pull backup archives from remote hosts via SSH and rsync.

## Features

- **Web UI** - Manage hosts and backups from your browser
- **Rsync + SSH** - Pull files from remote servers using the host's existing SSH key
- **Multiple paths per host** - Grab backups from several directories on the same server
- **Versioned backups** - Timestamped snapshots with hard-link dedup (no wasted space for unchanged files)
- **Easy scheduling** - Pick from presets (hourly, daily, weekly, monthly) or write custom cron
- **Backup history** - Track status, duration, size, and errors for every run

## Prerequisites

The machine running Backup Grabber must have its SSH key already authorized on the remote hosts (`~/.ssh/authorized_keys`).

## Quick Start

```bash
docker compose up --build
```

Open [http://localhost:5000](http://localhost:5000).

## Usage

1. **Add a host** - provide hostname, user, port, and one or more remote paths (one per line)
2. **Set a schedule** - pick a preset or leave it as manual-only
3. **Backup Now** - click the button to pull files immediately
4. **Check History** - view backup results, duration, and sizes

## Data

All data is stored in the `/data` Docker volume:

```
/data
├── backup_grabber.db   # SQLite database
└── backups/            # Downloaded backups
    └── <host-name>/
        └── <timestamp>/
            ├── var_backups/
            └── home_data/
```

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `/data` | Where to store the database and backups |

## Tech Stack

- Python / Flask
- SQLite
- APScheduler
- Plain HTML/CSS/JS
