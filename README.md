# Midscale

Self-hosted WireGuard orchestration platform inspired by Tailscale.
Private, secure, and under your control.

## Overview

Midscale is a control plane for WireGuard that lets you manage mesh VPN networks through a web dashboard and API. Devices authenticate via pre-shared keys or JWT, automatically receive IP addresses and WireGuard configs, and connect in star, mesh, or hybrid topologies.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  midscaled  │────▶│  Midscale    │◀───▶│  PostgreSQL  │
│  (Go daemon)│     │  API Server  │     │              │
│             │     │  (FastAPI)   │     │  Redis       │
│  WebSocket  │◀───▶│              │     └──────────────┘
│  + polling  │     │  Web UI     │
└─────────────┘     │  (React)     │
                    └──────────────┘
```

## Features

- **Multi-topology**: Star (hub-and-spoke), Mesh (full mesh), Hybrid (direct + fallback)
- **Device enrollment**: Pre-auth key based headless enrollment, device token auth
- **Live config push**: WebSocket + polling for real-time WireGuard config updates
- **IPAM**: Automatic IP allocation from CIDR ranges
- **Auth**: JWT (server), bcrypt device tokens (daemon), pre-auth keys (enrollment)
- **DNS**: CoreDNS integration for MagicDNS
- **Subnet routing**: Advertise and approve routes, exit node support
- **ACL engine**: Tag-based access control rules
- **Audit logging**: Structured event records for all mutations
- **Metrics**: Prometheus (`midscale_` namespace), health checks, rate limiting
- **Config v2**: Deterministic SHA-256 hashed JSON configs, idempotent reconciliation

## Quick Start

```bash
# Clone and configure
git clone <repo> && cd midscale
cp .env.example .env
# Edit .env to set SECRET_KEY and ENCRYPTION_KEY

# Start all services
docker compose up -d

# Seed admin user (admin@midscale.local / admin123)
docker compose exec backend python app/seed.py

# Open http://localhost:80
```

## Development

```bash
# Prerequisites: PostgreSQL 16, Redis 7, Python 3.12+, Node 20+
docker compose up -d postgres redis

# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
DATABASE_URL="postgresql+asyncpg://midscale:midscale@localhost:5432/midscale" \
  uvicorn app.main:app --reload --host 0.0.0.0

# Frontend
cd frontend && npm install && npm run dev

# Tests (require backend running on localhost:8000)
cd backend && python test_phase5.py && python test_phase6.py
```

## API

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/auth/register` | Register user |
| `POST /api/v1/auth/login` | Login, get JWT tokens |
| `POST /api/v1/networks` | Create network (auto-creates server device) |
| `POST /api/v1/networks/{id}/preauth-keys` | Create pre-auth key for enrollment |
| `POST /api/v1/devices/enroll` | Enroll device with pre-auth key |
| `GET /api/v1/devices/{id}/config-v2` | Get structured WireGuard config |
| `POST /api/v1/devices/{id}/heartbeat` | Device heartbeat (token auth) |
| `POST /api/v1/devices/{id}/endpoint` | Report endpoint candidate (token auth) |
| `POST /api/v1/devices/{id}/rotate-token` | Rotate device auth token |
| `POST /api/v1/routes/devices/{id}/advertise` | Advertise subnet route |
| `GET /api/v1/daemon/ws` | Daemon WebSocket (config push) |

## Topologies

| Topology | Description |
|----------|-------------|
| **Star** (default) | All devices connect only to the server hub. Minimal config, central routing. |
| **Mesh** | Every device connects directly to every other device. Best performance, requires endpoint discovery. |
| **Hybrid** | Direct peer-to-peer when endpoints known, hub fallback otherwise. Balances performance and reliability. |

Set per-network: `PUT /api/v1/networks/{id}` with `{"topology": "mesh"}`.
Set globally: `WIREGUARD_TOPOLOGY=mesh` in `.env`.

## Device Token Auth

Daemon endpoints use structured device tokens for auth:

```
midscale_device_<8-char-prefix>_<48-char-secret>
```

The prefix enables O(1) lookup. The secret is bcrypt-hashed server-side.
Token rotation keeps the same prefix (it's a hint, not a secret).

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, Alembic, Pydantic v2
- **Daemon**: Go (midscaled CLI)
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS 3
- **Infra**: Docker Compose, CoreDNS, Prometheus, Redis

## Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ | MVP — CRUD, JWT auth, WireGuard configs, frontend |
| 2 | ✅ | Node-owned keys, enrollment lifecycle, device token auth |
| 3 | ✅ | Pre-auth key enrollment, daemon CLI, config v2 |
| 4 | ✅ | Production hardening — audit, metrics, health, rate limits, DNS, WebSocket |
| 5 | ✅ | Secure daemon API — token auth, live config push via WebSocket |
| 6 | ✅ | Mesh/hybrid topology, endpoint management, stale cleanup |
| 7 | ⏳ | NAT traversal, multi-node, relay/DERP |
