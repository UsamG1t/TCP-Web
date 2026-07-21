---
title: Package Versions
parent: Guide
nav_order: 7
---

**Backend**

| Package     | Version   |
|-------------|-----------|
| Python      | 3.12      |
| Flask       | >= 3.0    |
| flask-cors  | >= 4.0    |
| gunicorn    | >= 21.2   |

**Frontend**

| Package                      | Version    |
|------------------------------|------------|
| Node.js                      | 20         |
| Svelte                       | ^4.2.18    |
| Vite                         | ^5.3.4     |
| @sveltejs/vite-plugin-svelte | ^3.1.1     |

The `/old` page has no build step and no runtime dependencies (vanilla
JavaScript).

**Container base images:** `python:3.12-slim`, `node:20-alpine`, `nginx:alpine`.
