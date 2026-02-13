Docker SSH Backup Manager
A simple, web-based backup solution that uses SSH and rsync to create versioned backups from remote hosts. Built with Docker for easy deployment.
Overview
This application provides a web interface to manage multiple remote hosts and automatically pull backups using SSH and rsync. It maintains multiple versions of files without full duplication by using hard links, similar to how tools like rsnapshot work.
Features

Web-based Interface - Manage all backup operations through a browser
SSH Key Management - Store and use SSH keys to authenticate with remote hosts
Versioned Backups - Keep multiple versions of files without full duplication
Multiple Hosts - Configure and backup multiple remote systems
Automated Scheduling - Set up automatic backup schedules
Backup History - View and track all backup operations
Docker-based - Easy deployment with volume mounting for backup storage

Architecture
Components

Web Application - Frontend UI for managing hosts and viewing status
API Backend - RESTful API for host management and backup operations
Database - Stores host configurations, SSH keys, and backup history
Rsync Engine - Executes backup operations with versioning
Scheduler - Handles automated backup scheduling

Technology Stack Options
Backend:

Python + Flask/FastAPI (recommended for simplicity)
Node.js + Express (alternative)

Frontend:

React/Vue/Svelte (for rich UI)
Plain HTML/CSS/JS (for simplicity)

Database:

SQLite (simpler, file-based)
PostgreSQL (more robust)

Scheduler:

APScheduler (Python)
node-cron (Node.js)
