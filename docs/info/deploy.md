---
title: Deploying to Your Own VPS
parent: Guide
nav_order: 6
---

This walks through a manual deployment from a clean server to a running system.

### Prerequisites

- A VPS with Docker Engine and the Docker Compose plugin installed.
- Git.
- Port `80` (and `5000` if you want the API exposed directly) open in both the
  host firewall and any provider-side firewall.
- No other service already bound to port `80` (a system nginx, for example, must
  be stopped: `sudo systemctl stop nginx && sudo systemctl disable nginx`).

### Manual deployment

```bash
# 1. Clone
sudo mkdir -p /path/to/repo/dir && sudo chown "$USER" /path/to/repo/dir
git clone https://github.com/UsamG1t/TCP-Web.git /path/to/repo/dir
cd /path/to/repo/dir

# 2. Build the images locally and start
docker compose up --build -d

# 3. Verify
curl -s localhost:5000/health          # {"status":"ok"}
curl -sI localhost/latest/ | head -1    # 200 OK
curl -sI localhost/old | head -1        # 302 -> /old/
docker compose ps
```

Then browse to:

- `http://<VPS_IP>/latest/` — the new simulator
- `http://<VPS_IP>/old` — the interactive click-to-drop page
- `http://<VPS_IP>/api/schema` — the API through the proxy
- `http://<VPS_IP>:5000/schema` — the API directly on its port

To update later: `git pull && docker compose up --build -d`.

### Where ports and paths are configured

| To change...                        | Edit |
|-------------------------------------|------|
| Host ports (`80`, `5000`)           | `docker-compose.yml` / `docker-compose.prod.yml` → `ports:` |
| URL paths (`/latest`, `/old`, `/api`) | `nginx/nginx.conf` → `location` blocks |
| The frontend's base path            | `nginx/Dockerfile` → `ENV VITE_BASE` |
| The API URL the frontend calls      | `nginx/Dockerfile` → `ENV VITE_API_BASE` / `frontend/.env` (dev) |
| Backend workers / bind              | `backend/Dockerfile` → `gunicorn` command |

For example, to serve the new UI at `/app` instead of `/latest`, change the
`location /latest/` block in `nginx.conf`, the `COPY --from=build ... /latest/`
line in `nginx/Dockerfile`, and `ENV VITE_BASE=/app/`.
