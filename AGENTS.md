# AGENTS.md

## Project Philosophy

Self-hosted WireGuard orchestration platform inspired by Tailscale.
Educational clarity + production-grade architecture + security-first.

## Tech Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, Alembic, Pydantic v2
- **Auth**: JWT (python-jose) + bcrypt (passlib, bcrypt<4.1) + Fernet key encryption
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS 3, react-router-dom v6
- **Infra**: Docker Compose (postgres, redis, backend, frontend/nginx)

## Project Structure

```
midscale/
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI app, lifespan, CORS, router includes
│   │   ├── config.py              # Pydantic-settings (env_file=".env")
│   │   ├── database.py            # Async engine, sessionmaker, get_session dependency
│   │   ├── core/
│   │   │   ├── security.py        # JWT create/decode, bcrypt hash/verify, Fernet encrypt/decrypt
│   │   │   └── logging.py         # structlog setup (JSON in prod, console in debug)
│   │   ├── models/                # SQLAlchemy ORM (all datetime defaults use Python-side lambdas)
│   │   │   ├── user.py            # id(UUID), email, password_hash, display_name, is_active, is_superuser
│   │   │   ├── network.py         # id(UUID), name, subnet(CIDR), description, interface_name, topology
│   │   │   ├── device.py          # id(UUID), name, user_id, network_id, public_key, private_key_enc, ip_address, dns_enabled, is_active, is_node_owned, device_token_hash, device_token_prefix, enrollment_status, enrolled_at, last_seen_at, revoked_at, tags(JSON), last_handshake
│   │   │   ├── endpoint.py        # DeviceEndpoint: id, device_id, endpoint, source, port, local_ip, public_ip, priority, is_active, last_seen
│   │   │   ├── preauth_key.py     # id(UUID), key, network_id, reusable, expires_at, used_by(JSON)
│   │   │   ├── acl.py             # id(UUID), network_id, src_tags(JSON), dst_tags(JSON), action, priority
│   │   │   └── dns.py             # id(UUID), network_id, domain, address
│   │   ├── schemas/               # Pydantic v2 schemas (from_attributes=True for responses)
│   │   │   ├── device.py          # Device, PeerInfo, EndpointCandidate, EndpointReport, DeviceConfigV2Response, ...
│   │   │   ├── daemon.py          # DaemonWsEvent, ConfigChangedEvent
│   │   │   └── network.py         # NetworkCreate, NetworkUpdate (incl. topology), NetworkResponse (incl. topology)
│   │   ├── api/v1/                # Route modules
│   │   │   ├── auth.py            # register, login, refresh, me
│   │   │   ├── networks.py        # CRUD + list/create devices + preauth keys (auto-creates __midscale_server__ device)
│   │   │   ├── devices.py         # CRUD, enroll, enroll-by-key, rotate-token, revoke, config, config-v2, register, heartbeat, endpoint report
│   │   │   ├── acls.py            # CRUD tag-based ACL rules per network
│   │   │   ├── dns.py             # CRUD DNS entries per network
│   │   │   ├── routes.py          # Advertise, approve, list routes
│   │   │   ├── ws.py              # Daemon WebSocket endpoint
│   │   │   └── audit.py           # Audit log querying
│   │   ├── api/deps.py            # get_current_user, get_current_superuser, get_current_device, get_current_device_by_id, _lookup_device_by_token
│   │   └── services/
│   │       ├── auth.py            # register/login/refresh business logic
│   │       ├── ipam.py            # allocate_ip (first-available from CIDR), release_ip
│   │       ├── wireguard.py       # generate_keypair, generate_device_config, build_config_v2, compute_config_hash, get_active_endpoints, sync_wireguard_interface
│   │       ├── topology.py        # StarTopologyGenerator, MeshTopologyGenerator, HybridTopologyGenerator, TopologyType
│   │   ├── daemon.py          # process_heartbeat, report_endpoint, stale_endpoint_cleanup
│   │   ├── stun_server.py     # RFC 5389 STUN server (UDP binding response)
│   │       ├── acl.py             # check_device_access (tag-based matching)
│   │       ├── event_bus.py       # Redis pub/sub + in-memory fallback EventBus
│   │       ├── event_types.py     # Event dataclass, CONFIG_CHANGED, channel helpers
│   │       ├── ws_manager.py      # WebSocketConnectionManager (admin + daemon connections)
│   │       ├── wg_controller.py   # WireGuardController — periodic interface reconciliation
│   │       ├── wg_adapter.py      # WgCliAdapter, WgMockAdapter
│   │       ├── wg_models.py       # DesiredPeer, PeerDiff, ReconciliationResult, WGPeer
│   │       ├── wg_exceptions.py   # WireGuard-specific exceptions
│   │       ├── metrics.py         # Prometheus metrics (midscale_ namespace)
│   │       ├── rate_limiter.py    # Sliding window rate limiter (Redis/in-memory)
│   │       ├── audit.py           # Audit logging service
│   │       ├── health.py          # Health checks
│   │       ├── dns_provider.py    # CoreDNS file provider integration
│   │       └── dns_records.py     # DNS record sync logic
│   ├── alembic/                   # env.py (async), versions/, script.py.mako
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── pyproject.toml
│   ├── test_phase5.py             # Phase 5 end-to-end tests (47 tests)
│   ├── test_phase6.py             # Phase 6 end-to-end tests (51 tests)
│   └── Dockerfile
├── midscaled/                     # Go daemon (midscaled CLI)
│   ├── daemon/
│   │   ├── models.py              # DesiredPeer, ConfigV2PullResult
│   │   ├── api_client.py          # HTTP client with auth headers, WebSocket connect
│   │   ├── ws_client.py           # DaemonWebSocketClient with reconnect + polling fallback
│   │   ├── reconciler.py          # Config reconciliation loop with push trigger
│   │   ├── endpoint_monitor.py    # STUN + local IP detection, endpoint change reporting
│   │   ├── stun_client.py         # RFC 5389 STUN client (Binding Request/Response)
│   │   └── config.py              # Daemon config
│   └── cmd/
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts          # Fetch wrapper, auth header, error formatting
│   │   │   ├── auth.ts            # Login/register/refresh/me + types
│   │   │   ├── networks.ts        # Network, Device, PreAuthKey, ACLRule, DNSEntry types + API calls
│   │   │   └── devices.ts         # Device CRUD + rotate/config/register
│   │   ├── hooks/useAuth.tsx      # AuthProvider context, login/register/logout, token in localStorage
│   │   ├── components/
│   │   │   ├── Layout.tsx         # Navbar + Outlet
│   │   │   └── ProtectedRoute.tsx # Redirect to /login if no token
│   │   └── pages/
│   │       ├── Login.tsx          # Email/password form
│   │       ├── Register.tsx       # Display name/email/password form
│   │       ├── Dashboard.tsx      # Networks grid + device table + create network
│   │       ├── NetworkDetail.tsx  # Tabs: devices, ACLs, DNS, pre-auth keys
│   │       └── DeviceDetail.tsx   # Device info, rotate keys, view/download config, toggle active
│   ├── package.json               # react, react-router-dom, vite, tailwind, typescript
│   ├── vite.config.ts             # Proxy /api -> localhost:8000
│   └── Dockerfile
├── coredns/
│   ├── Corefile
│   └── zones/
├── nginx/default.conf             # SPA + /api reverse proxy to backend:8000
├── docker-compose.yml             # postgres, redis, backend, frontend, coredns
├── .env.example
├── .gitignore
├── AGENTS.md
├── README.md
├── dev_instructions.md
└── INITIAL_IMPLEMENTATION.md
```

## Database Notes

- All `created_at`/`updated_at` use Python-side `default=lambda: datetime.now(timezone.utc)` (NOT `server_default=func.now()`) to avoid `MissingGreenlet` errors in async SQLAlchemy
- `tags`, `used_by`, `src_tags`, `dst_tags` use `JSON` column type (not PostgreSQL ARRAY) for portability
- `private_key_enc` stores WireGuard private key encrypted with Fernet (symmetric)
- `device_token_hash` stores bcrypt hash of device auth token (one-time return at enrollment)
- `enrollment_status` tracks device lifecycle: `pending` → `active` → `revoked` / `expired`
- `last_seen_at` set on each heartbeat (separate from `last_handshake` which is WireGuard protocol level)
- `device_token_prefix` stores first 8 chars of token secret for O(1) daemon auth lookup (indexed)
- `DeviceEndpoint` stores endpoint candidates with priority/active flags for mesh/hybrid routing
- Migration chain: `e44cb5174045` → `b02bde8a120e` → `2c1a3b5e6d7f` → `3d4e5f6a7b8c` → `4a5b6c7d8e9f` → `5f6a7b8c9d0e` → `6a7b8c9d0e1f` → `7b8c9d0e1f2a` → `8c9d0e1f2a3b` → `737e64bcc13f`

## WireGuard Integration

- `wg genkey` / `wg pubkey` via subprocess (falls back to mock keys if `wg` binary not found)
- Keys encrypted at rest with `cryptography.fernet.Fernet`
- Configs generated as standard `[Interface]` + `[Peer]` ini format (config-v1)
- Config v2: structured JSON without private key for node-owned devices; daemon injects local private key
- `sync_wireguard_interface` attempts to manage a real `wg` interface (skips if not found)
- Topology support: Star (hub-and-spoke), Mesh (full peer-to-peer), Hybrid (direct when endpoints available, hub fallback otherwise)
- `DeviceEndpoint` model tracks endpoint candidates (local_ip, public_ip, priority, source) for mesh/hybrid routing
- Stale endpoint cleanup marks endpoints older than 30 min as inactive (runs every 5 min in background)

## Auth System

- JWT with access tokens (30min) + refresh tokens (7 days)
- Passwords hashed with bcrypt (passlib, pin bcrypt<4.1 for compatibility)
- Pre-auth keys for headless device registration
- `DeviceRegisterRequest` allows devices to register using a pre-auth key (no user token needed)
- Device token auth: `midscale_device_<8-char-prefix>_<48-char-secret>` — prefix for O(1) lookup, bcrypt-hashed secret
- Token rotation preserves prefix (lookup hint, not secret)

## Networking & Topology

- **Star** (default): all devices connect to server hub; server has one peer per client
- **Mesh**: every device has peer entries for all other devices with best endpoint candidates; includes server for subnet routing
- **Hybrid**: direct peer endpoints when available; no-endpoint peers included without endpoint (hub handles routing)
- Topology is configurable per-network (`networks.topology` column) or globally via `WIREGUARD_TOPOLOGY` setting
- Endpoint reports (`POST /devices/{id}/endpoint`) trigger `config.changed` events for live config push

## Fixes Applied (for future reference)

1. **`email-validator` not installed** — added to requirements.txt
2. **`MessageResponse` unused import** — cleaned up by ruff
3. **`Device.is_active == True`** — changed to `Device.is_active` (ruff E712)
4. **`bcrypt` version conflict with passlib** — pinned `bcrypt<4.1`
5. **`[object Object]` error display** — client.ts now flattens FastAPI validation error array
6. **`.local` TLD rejected by EmailStr** — changed all `EmailStr` to `str` in schemas
7. **`MissingGreenlet` on datetime columns** — replaced `server_default=func.now()` with Python `default=lambda: datetime.now(timezone.utc)`
8. **`user_id=None` in pre-auth register** — `DeviceResponse.user_id` changed to `Optional[uuid.UUID]` to handle pre-auth key registered devices (migration `7b8c9d0e1f2a` makes column nullable)
9. **`DAEMON_AUTH_FAILURES` import in devices.py** — unused import removed
10. **`_lookup_device_by_token` exposed as module-level function** — enables reuse in config-v2 endpoint and daemon WebSocket auth
11. **`generate_device_token()` in security.py** — produces structured tokens (`midscale_device_<prefix>_<secret>`) with prefix for O(1) lookup and bcrypt-hashed secret
12. **Token URL-safe base64 can contain `_`** — `_lookup_device_by_token` uses position-based extraction (prefix at fixed offset 8), not `split("_")`, to handle base64url tokens that may contain underscores
13. **Token rotation keeps same prefix** — only the secret part rotates; prefix stays the same since it's a lookup hint (not secret)
14. **Config-v2 `routes` never populated** — `build_config_v2()` now queries approved/enabled routes from `AdvertisedRoute` table; hash changes when routes change
15. **`DeviceEndpoint` model had no `local_ip`/`public_ip`/`priority`/`is_active`** — added via migration `737e64bcc13f`; `report_endpoint()` now accepts them
16. **Network creation did not create `__midscale_server__` device** — now auto-created with `.1` IP and WireGuard keypair
17. **`IPv4Network.hosts()` returns generator in Python 3.12** — wrapped with `list()` for subscript access

## Seeding

```bash
cd backend && DATABASE_URL="postgresql+asyncpg://midscale:midscale@localhost:5432/midscale" python app/seed.py
```
Creates `admin@midscale.local` / `admin123` superuser.

## Development

```bash
# Backend (live reload, requires DB running)
cd backend && source venv/bin/activate
DATABASE_URL="postgresql+asyncpg://midscale:midscale@localhost:5432/midscale" \
  uvicorn app.main:app --reload --host 0.0.0.0

# Or with Docker
docker compose up -d postgres redis
cd backend && source venv/bin/activate
DATABASE_URL="postgresql+asyncpg://midscale:midscale@localhost:5432/midscale" \
  uvicorn app.main:app --reload --host 0.0.0.0

# Full Docker stack
docker compose up -d

# Frontend
cd frontend && npm run dev

# Migration
cd backend && alembic revision --autogenerate -m "description"
cd backend && alembic upgrade head

# Run tests (requires backend running on localhost:8000)
cd backend && python test_phase5.py
cd backend && python test_phase6.py
```

## Test Summary

| Phase | Tests | Description |
|-------|-------|-------------|
| 5 | 47 | Token auth, heartbeat/endpoint/route auth, config hash/rev, token rotation, revoke |
| 6 | 51 | Star/mesh/hybrid topology, endpoint candidates, hash on endpoint change, topology persistence, stale cleanup |

## What's Implemented vs What's Next

### Phase 1 — Complete (MVP)
- [x] Project scaffolding
- [x] Database models + migrations
- [x] JWT auth (register, login, refresh)
- [x] CRUD for networks, devices, ACLs, DNS, pre-auth keys
- [x] IPAM (auto-IP allocation)
- [x] WireGuard key generation + config download
- [x] Tag-based ACL engine
- [x] React frontend (dashboard, network/device detail, auth pages)
- [x] Docker Compose (postgres, redis, backend, nginx + frontend)

### Phase 2 — Complete (Node-Owned Keys & Enrollment)
- [x] Node-owned WireGuard keys (device generates keypair client-side, sends only public key)
- [x] Device enrollment lifecycle (pending → active → revoked / expired)
- [x] Device token auth (bcrypt-hashed tokens for daemon↔server auth)
- [x] Config v2 (structured JSON config without private key for node-owned devices)
- [x] Endpoints: enroll, rotate-token, revoke, config-v2, node-device creation

### Phase 3 — Complete (Secure Pre-Auth Key Enrollment)
- [x] `POST /devices/enroll` — unauthenticated pre-auth key based enrollment
- [x] Daemon `midscaled enroll` CLI command (generates keys locally, enrolls, saves state)
- [x] Config-v2 support in daemon reconciler (JSON parsing + local private key injection)
- [x] Prometheus enrollment metrics (`midscale_device_enrollment_total`)
- [x] Config-v2 refactored into reusable `build_config_v2()` service function
- [x] Device.user_id migration (nullable for preauth-enrolled devices)
- [x] Secure state storage (0600 perms for enrollment.json and private.key)
- [x] Backward compatible — existing `/devices/{id}/enroll`, `/register`, config-v1 unchanged

### Phase 4 — Complete (Production Hardening)
- [x] Audit logging with structured event records
- [x] Rate limiting (per-endpoint sliding window, Redis-backed)
- [x] Prometheus metrics (midscale_ namespace)
- [x] Health checks (liveness, readiness, startup)
- [x] Subnet router support (AdvertisedRoute model + approval flow)
- [x] Exit node support (exit_node_id on Device)
- [x] WireGuard controller (periodic interface reconciliation)
- [x] Real WireGuard interface management (peer add/remove on server)
- [x] CoreDNS integration (MagicDNS via file-based zones)
- [x] WebSocket push for real-time config updates
- [x] Mesh topology (peer-to-peer configs, not star)

### Phase 5 — Complete (Secure Daemon API & Live Config Push)
- [x] Device token auth on all daemon endpoints (heartbeat, endpoint, route advertise)
- [x] Optimized device token lookup via prefix-based indexing (`device_token_prefix`)
- [x] Token format: `midscale_device_<prefix>_<secret>` (prefix stored plaintext for O(1) lookup, secret bcrypt-hashed)
- [x] Backward compatible: old-format tokens still work via full-scan fallback
- [x] Config-v2 revision number, generation timestamp, and deterministic SHA-256 hash
- [x] Daemon WebSocket endpoint (`/api/v1/daemon/ws`) with device token auth
- [x] Per-device WebSocket connection tracking in `WebSocketConnectionManager`
- [x] Config-changed events published to Redis/in-memory event bus on state changes
- [x] Targeted WebSocket push to affected device's daemon connection
- [x] Idempotent config application via hash comparison (skip apply if unchanged)
- [x] Daemon-side WebSocket client with auto-reconnect + polling fallback
- [x] Reconciler push event trigger (immediate reconcile on `config.changed`)
- [x] Metrics: `midscale_daemon_auth_failures_total` with `reason` label
- [x] `config.changed` event type in event_types.py
- [x] Migration `8c9d0e1f2a3b` adds `device_token_prefix` column with index

### Phase 6 — Complete (Mesh/Hybrid Topology & Endpoint Management)
- [x] `DeviceEndpoint` model with `local_ip`, `public_ip`, `priority`, `is_active` fields
- [x] `MeshTopologyGenerator` — every device gets direct peer entries for all other devices
- [x] `HybridTopologyGenerator` — direct peer when endpoints available, hub fallback when not
- [x] `_get_topology_generator()` resolution: per-network → global setting → star (default)
- [x] `build_config_v2()` now topology-aware, passes `endpoints_by_device` to generators
- [x] `EndpointCandidate` schema nested in `PeerInfo` for mesh/hybrid configs
- [x] `relay_fallback` flag on peers without endpoints in mesh/hybrid mode
- [x] Endpoint report (`POST /devices/{id}/endpoint`) accepts `local_ip`, `public_ip`
- [x] Endpoint report publishes `config.changed` event for live peer update
- [x] `get_active_endpoints()` helper queries active endpoints grouped by device
- [x] `stale_endpoint_cleanup()` background job (every 5 min, 30 min cutoff)
- [x] Network creation auto-creates `__midscale_server__` device with `.1` IP + keypair
- [x] `topology` field on `NetworkUpdate`/`NetworkResponse` schemas
- [x] Migration `737e64bcc13f` adds endpoint fields, topology column
- [x] Config hash changes on endpoint updates (deterministic)
- [x] Phase 6 end-to-end tests: 51/51 passing

### Phase 7 — Platform Maturity
- [x] STUN (RFC 5389) Binding Request/Response — backend server + daemon client
- [ ] DERP relay for symmetric NAT
- [ ] Multi-node control plane
- [ ] Mobile support
