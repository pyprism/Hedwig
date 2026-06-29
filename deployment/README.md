# Hedwig Deployment with Ansible (Docker)

Automated Docker-based deployment of the [Hedwig](https://github.com/pyprism/Hedwig) Django REST API using Ansible.

The playbooks clone the repo, render a production `.env`, and bring up the `web`
(uWSGI), `celery_worker`, and `celery_beat` containers via `docker compose`.

> **Docker is assumed to be already installed on the host.** The playbook only
> verifies Docker Engine + the Compose plugin are present (and fails early with
> a clear message if not) — it does not install them.
>
> **The Docker stack does NOT include PostgreSQL or RabbitMQ.** Only the
> application containers (`web`, `celery_worker`, `celery_beat`) are managed
> here. PostgreSQL (database) and RabbitMQ (Celery broker) must already be
> running on, or reachable from, the host — the containers connect to them via
> `host.docker.internal`. Provisioning and managing those services is your
> responsibility.

## Super Quick Start 🚀

```bash
cd deployment
ansible-playbook -i inventories/production deploy.yaml -K
```

---

## Quick Start

### 1. Prerequisites

- Ansible on your local machine: `pip install -r requirements.txt`
- SSH access to the target server(s)
- Server running Ubuntu/Debian or RedHat/CentOS
- **Docker Engine + Docker Compose plugin already installed** on the target
  server (the playbook verifies but does not install them)
- PostgreSQL running on (or reachable from) the target server — containers reach
  it via `host.docker.internal` (not provisioned by this playbook)
- RabbitMQ running on (or reachable from) the target server (Celery broker —
  also not provisioned by this playbook)

> Hedwig is a **public** repo, so no deploy key is needed.

### 2. Setup

```bash
# 1. Enter the deployment directory
cd deployment

# 2. Install Ansible
pip install -r requirements.txt

# 3. Copy and configure secrets
cp vars/secrets.yaml.example vars/secrets.yaml
# Edit vars/secrets.yaml with your real values

# 4. Configure inventory
cp inventories/production/hosts.example inventories/production/hosts
# Edit hosts with your server IP/hostname + the deployment_base_dir / deployment_user

# 5. Test connectivity
ansible -i inventories/production webservers -m ping
```

### 3. Deploy

```bash
# Full deploy (clones repo, builds & starts containers)
ansible-playbook -i inventories/production deploy.yaml -K

# Verbose (debugging)
ansible-playbook -i inventories/production deploy.yaml -K -vvv

# Only a subset of steps
ansible-playbook -i inventories/production deploy.yaml -K --tags docker
```

`-K` prompts for the sudo (become) password.

## How It Works

1. **common** role — checks the deployment user.
2. **deployment_user** role — creates the deploy user, grants Docker sudo, sets up
   `~/.ssh` (only used if you supply `git_ssh_private_key` for a private fork).
3. **docker** role —
   - verifies Docker Engine + Compose plugin are installed (fails early if not),
   - clones/pulls the repo at `project_branch`,
   - renders `.env` from `vars/secrets.yaml` (`roles/docker/templates/env.j2`),
   - `docker compose up -d --build`, waits for the healthcheck,
   - runs `migrate`,
   - prunes dangling images (`docker image prune -f`) to reclaim disk space
     after the rebuild.

## Available Playbooks

| Playbook | Description |
|----------|-------------|
| `deploy.yaml` | Full deployment (first time or updates) |
| `update.yaml` | Pull code, rebuild containers, migrate |
| `rollback.yaml` | Roll back to a specific git commit/tag (prompts for the ref) |
| `healthcheck.yaml` | Verify Docker + container + DB health |

## Available Tags

```bash
--tags common       # System / user checks only
--tags user         # Deployment user setup only
--tags docker       # Docker verify + application deployment
--tags deploy       # Application deployment
```

## Configuration

### `vars/secrets.yaml` (required, gitignored)

Sensitive values — Django secret key, DB creds, AWS/S3, RabbitMQ URL, Sentry DSN,
JWT lifetimes, deployment user/dir. See `vars/secrets.yaml.example` for the full
annotated list. These feed the rendered server `.env` and mirror Hedwig's
`.env_example`.

### `inventories/production/group_vars/all.yaml`

Non-sensitive config: `project_repo`, `project_branch`, paths, Django settings
module.

### `.env` on the server

Generated from `vars/secrets.yaml` via `env.j2` — never edit it by hand on the
server; re-run `update.yaml` instead.

## Common Tasks

```bash
# Update application code (pull, rebuild, migrate)
ansible-playbook -i inventories/production update.yaml -K

# Health check
ansible-playbook -i inventories/production healthcheck.yaml -K

# Rollback (prompts for commit/tag)
ansible-playbook -i inventories/production rollback.yaml -K

# Restart / status / logs (replace /opt/hedwig with your deployment_base_dir)
ansible -i inventories/production webservers -b -a "cd /opt/hedwig && docker compose restart"
ansible -i inventories/production webservers -b -a "cd /opt/hedwig && docker compose ps"
ansible -i inventories/production webservers -b -a "cd /opt/hedwig && docker compose logs --tail=50"

# Run a Django management command
ansible -i inventories/production webservers -b -a "cd /opt/hedwig && docker compose exec web python manage.py <command>"
```

## Troubleshooting

```bash
ansible -i inventories/production webservers -m ping                 # connectivity
ansible -i inventories/production webservers -a "docker info"        # docker up?
ansible -i inventories/production webservers -b -a "cd /opt/hedwig && docker compose ps"
ansible -i inventories/production webservers -b -a "cd /opt/hedwig && docker compose logs --tail=30"
ansible -i inventories/production webservers -a "df -h"              # disk
ansible -i inventories/production webservers -a "docker system prune -f"
```

## Security Notes

1. **Never commit secrets** — `vars/secrets.yaml` and the server `.env` are gitignored.
2. **DB & broker** — Postgres/RabbitMQ live on the host; containers reach them via
   `host.docker.internal`. Don't expose them publicly.
3. **Port** — the `web` container binds `127.0.0.1:${server_port}` only; put
   nginx/caddy with TLS in front.
4. **Registration** — set `registration_open: false` in secrets after the first
   (superuser) account is created.

## Default Paths on Server

```
/opt/hedwig/                  # project root (= deployment_base_dir, configurable)
├── docker-compose.yaml       # web + celery_worker + celery_beat
├── Dockerfile                # multi-stage build (python:3.14-slim, uWSGI)
├── .env                      # generated by Ansible
└── [application code]
```
