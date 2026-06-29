# Hedwig [![CI](https://github.com/pyprism/Hedwig/actions/workflows/ci.yml/badge.svg)](https://github.com/pyprism/Hedwig/actions/workflows/ci.yml) [![codecov](https://codecov.io/gh/pyprism/Hedwig/graph/badge.svg?token=JMKaZbOg7J)](https://codecov.io/gh/pyprism/Hedwig)

A Django REST Framework backend for managing shared email inboxes.
Built for personal use, small teams, helpdesks, or anyone who needs multiple people
working out of the same mailbox. Hedwig manages mailboxes and domains,
ingests inbound mail and sends outbound mail through pluggable email providers
(currently Postmark), and tracks delivery events via webhooks.

## Requirement

- PostgreSQL && Rabbitmq
- Docker
- Any AWS S3 compatible storage for storing files.
- Electricity is optional

## Status
Still in early stage

## Running locally (no Docker)

Requires a local PostgreSQL and rabbitmq reachable per the `db_*` env vars (defaults: db/user/pass `hedwig` on `localhost`).

```bash
cp .env_example .env          # then edit values
scripts/dockerless_run.sh runserver          # runserver on 127.0.0.1:8000
scripts/dockerless_run.sh migrate
scripts/dockerless_run.sh celery-worker          # celery worker
scripts/dockerless_run.sh test            # pytest suite
```

`scripts/dockerless_run.sh` creates/uses a `.venv`, loads `.env`, applies sane dev
defaults, and dispatches to `manage.py`.

## Running with Docker

```bash
cp .env_example .env          # then edit values
docker compose up -d --build  # web (uWSGI) + celery_worker + celery_beat
```

The `web` container exposes uWSGI on `127.0.0.1:${server_port}` (front it with
nginx/caddy + TLS). Postgres and RabbitMQ run on the host and are reached via
`host.docker.internal`.

Test suites live under `hedwig/tests/`. Celery runs eagerly (synchronous) in tests.

## Configuration

All config comes from environment variables (lowercase names, e.g. `secret_key`,
`debug`, `db_host`, `allowed_hosts`, `aws_*`, `rabbitmq_url`). See
[`.env_example`](.env_example) for the full annotated list.


## Deployment

Production deployment is automated with Ansible (installs Docker, clones the repo,
renders `.env`, and brings up the containers).

**See [`deployment/README.md`](deployment/README.md) for the full deployment guide.**

```bash
cd deployment
cp vars/secrets.yaml.example vars/secrets.yaml      # fill in secrets
cp inventories/production/hosts.example inventories/production/hosts
ansible-playbook -i inventories/production deploy.yaml -K
```
## License
MIT
