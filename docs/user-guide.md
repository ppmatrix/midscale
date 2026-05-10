# Midscale User Guide

## What Midscale Does

Midscale is a self-hosted WireGuard orchestration platform inspired by
Tailscale. It provides a control plane for managing WireGuard mesh VPN
networks through a web UI and JSON API.

Devices authenticate via pre-shared keys, automatically receive IP
addresses and WireGuard configurations, and connect in star, mesh, or
hybrid topologies. The platform handles IP address management (IPAM),
key generation, configuration distribution, NAT traversal, and real-time
config updates over WebSocket.

Node-owned devices generate their WireGuard keypair locally — the server
never sees the private key.

---

## Requirements

| Component | Requirement |
|-----------|-------------|
| Server | Linux x86_64, Docker Compose, ~2 GB RAM, 20 GB disk |
| Client | Linux with WireGuard kernel module (`wg` CLI) |
| Network | UDP port 51820 open for WireGuard, TCP 80/443 for UI/API |
| Optional | UDP port 3478 for STUN, TCP 8765 for relay fallback |
| PostgreSQL | 16 (provided by Docker) |
| Redis | 7 (provided by Docker, optional — falls back to in-memory) |

---

## Docker Deployment

### 1. Clone and configure

```bash
git clone <repo> && cd midscale
cp .env.example .env
```

Edit `.env` and set at minimum:

```
SECRET_KEY=$(openssl rand -hex 32)
WIREGUARD_SERVER_ENDPOINT=<your-server-public-ip-or-domain>
```

### 2. Start all services

```bash
docker compose up -d
```

This starts PostgreSQL, Redis, the Midscale backend (FastAPI on port
8000), CoreDNS (on port 5353), and the React frontend (nginx on port 80).

### 3. Seed the admin user

```bash
docker compose exec backend python app/seed.py
```

Creates `admin@midscale.local` / `admin123` (superuser).

### 4. Open the dashboard

Browse to `http://localhost` and log in with the admin credentials.

---

## Environment Variables

All configuration is via environment variables (`.env` file).

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | — | **Required**. JWT signing key. Generate with `openssl rand -hex 32`. |
| `ENCRYPTION_KEY` | auto‑generated | Fernet key for encrypting server‑owned device private keys at rest. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | JWT access token lifetime. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 7 | JWT refresh token lifetime. |

### WireGuard

| Variable | Default | Description |
|----------|---------|-------------|
| `WIREGUARD_INTERFACE` | `wg0` | Server WireGuard interface name. |
| `WIREGUARD_PORT` | 51820 | Server WireGuard listen port. |
| `WIREGUARD_SERVER_ENDPOINT` | `localhost` | **Required**. Public IP or domain the daemon uses to reach the server. |
| `WIREGUARD_TOPOLOGY` | `star` | Default topology: `star`, `mesh`, or `hybrid`. |
| `WG_CONTROLLER_ENABLED` | `true` | Enable periodic interface reconciliation. |
| `WG_CONTROLLER_INTERVAL_SECONDS` | 30 | Reconciliation interval. |

### Network

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string. |
| `REDIS_URL` | `redis://redis:6379/0` | Redis URL (empty = in‑memory event bus). |
| `CORS_ORIGINS` | `["http://localhost:5177","http://localhost:8000"]` | Allowed CORS origins for the API. |

### NAT Traversal

| Variable | Default | Description |
|----------|---------|-------------|
| `STUN_ENABLED` | `true` | Enable built-in STUN server on UDP 3478. |
| `STUN_HOST` | `0.0.0.0` | STUN server bind address. |
| `STUN_PORT` | 3478 | STUN server port. |
| `RELAY_ENABLED` | `true` | Enable DERP-style TCP relay server. |
| `RELAY_HOST` | `0.0.0.0` | Relay server bind address. |
| `RELAY_PORT` | 8765 | Relay server port. |

### Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_ENABLED` | `true` | Enable sliding‑window rate limiter. |
| `RATE_LIMIT_DEFAULT_MAX` | 120 | Requests per window (default). |
| `RATE_LIMIT_AUTH_MAX` | 10 | Login attempts per window. |
| `RATE_LIMIT_HEARTBEAT_MAX` | 60 | Heartbeat requests per window. |

### DNS

| Variable | Default | Description |
|----------|---------|-------------|
| `DNS_ENABLED` | `false` | Enable CoreDNS/MagicDNS integration. |
| `DNS_DOMAIN` | `wg.midscale` | DNS domain for MagicDNS. |

---

## First Startup

### Verify the backend is healthy

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected output:

```json
{
    "status": "ok",
    "wg_controller": {"running": true},
    "stun": {"enabled": true, "running": true, "port": 3478},
    "relay": {"enabled": true, "running": true, "port": 8765}
}
```

### Health check endpoints

```bash
# Liveness — is the process alive?
curl -s http://localhost:8000/health/live

# Readiness — can it handle requests?
curl -s http://localhost:8000/health/ready

# Startup — has it finished initializing?
curl -s http://localhost:8000/health/startup
```

### Prometheus metrics

```bash
curl -s http://localhost:8000/metrics | grep midscale_
```

---

## Creating a Network

Via the web dashboard (recommended):

1. Log in at `http://localhost`
2. Click **Create Network**
3. Enter a name (e.g., `office`) and subnet (e.g., `10.100.0.0/24`)
4. Click **Save**

Via the API:

```bash
# Login
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@midscale.local","password":"admin123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Create network
curl -s -X POST http://localhost:8000/api/v1/networks \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"office","subnet":"10.100.0.0/24"}'
```

The server automatically creates a `__midscale_server__` device with the
`.1` IP address and a WireGuard keypair.

---

## Creating a Pre-auth Key

Pre-auth keys allow devices to enroll without needing a user JWT token.

Via the dashboard:

1. Open the network detail page
2. Go to the **Pre-auth Keys** tab
3. Click **Create Key**
4. Optionally set it as reusable and set an expiration

Via the API:

```bash
curl -s -X POST "http://localhost:8000/api/v1/networks/$NETWORK_ID/preauth-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"reusable": true, "expires_in_hours": 24}'
```

Response includes the key value:

```json
{"id":"...","key":"midscale_abc123...","reusable":true,"expires_at":"..."}
```

---

## Enrolling a Device with midscaled

The `midscaled` CLI daemon is a Python tool that runs on each client
machine. It generates a WireGuard keypair locally, enrolls with the
server, and manages the local WireGuard interface.

### Install midscaled

```bash
# From the midscale repository
cd midscale/midscaled
pip install .

# Or run directly
python -m daemon.main <command>
```

### Enroll a device

```bash
midscaled enroll \
  --server https://midscale.example.com \
  --preauth-key "midscale_abc123..." \
  --name laptop-01 \
  --apply
```

| Flag | Description |
|------|-------------|
| `--server` | Midscale server URL (required). |
| `--preauth-key` | Pre‑auth key from the dashboard or API (required). |
| `--name` | Device hostname or label (required). |
| `--apply` | Immediately bring up the WireGuard interface after enrollment. |
| `--state-dir` | State directory (default: `/var/lib/midscaled`). |
| `--insecure` | Skip TLS verification (development only). |
| `--debug` | Enable debug logging. |

**What happens during enrollment:**

1. `midscaled` generates a new WireGuard keypair (`wg genkey` + `wg pubkey`)
2. Sends the public key to the server along with the pre-auth key
3. Server allocates an IP, creates the device record, returns a
   `device_token` and config-v2
4. `midscaled` saves the device ID, token, and private key to
   `state_dir` (permissions 0600)
5. With `--apply`, it brings up the WireGuard interface and applies
   the config immediately

**Node-owned keys:** The private key is generated client-side and
never leaves the device. The server only stores the public key.

### Start the daemon

After enrollment, start the daemon to continuously manage the tunnel:

```bash
midscaled
```

The daemon runs in the foreground and will:
- Periodically pull the latest WireGuard config from the server
- Send heartbeats to keep the device marked as online
- Discover endpoints via STUN and report them to the server
- Probe peer endpoints for reachability and latency
- Perform UDP hole punching for direct peer-to-peer connectivity
- Fall back to TCP relay when hole punching fails
- Listen for live config changes via WebSocket
- Handle graceful shutdown on SIGTERM/SIGINT

### Daemon environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MIDSCALE_SERVER_URL` | `http://localhost:8000` | Server API + WebSocket URL. |
| `MIDSCALE_PREAUTH_KEY` | — | Pre‑auth key for registration. |
| `MIDSCALE_DEVICE_NAME` | hostname | Device display name. |
| `MIDSCALE_DEVICE_TOKEN` | — | Token from enrollment (stored by `midscaled enroll`). |
| `MIDSCALE_INTERFACE` | `midscale0` | Local WireGuard interface name. |
| `MIDSCALE_WG_PORT` | 51820 | WireGuard listen port. |
| `MIDSCALE_POLL_INTERVAL` | 30 | Config polling interval in seconds. |
| `MIDSCALE_RELAY_ENABLED` | `true` | Enable relay fallback client. |
| `MIDSCALE_RELAY_HOST` | `127.0.0.1` | Relay server host. |
| `MIDSCALE_RELAY_PORT` | 8765 | Relay server port. |

### Non-root operation

The daemon needs `CAP_NET_ADMIN` to manage the WireGuard interface and
write to `/var/lib/midscaled`. Run as root or grant the capabilities:

```bash
sudo setcap cap_net_admin+ep $(which midscaled)
```

---

## Verifying Device Status

### Via the dashboard

Open the network detail page. Active devices are listed in the
**Devices** tab with their IP address, public key, and online status.

### Via the API

```bash
# List all devices in a network
curl -s "http://localhost:8000/api/v1/networks/$NETWORK_ID/devices" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Get a specific device
curl -s "http://localhost:8000/api/v1/devices/$DEVICE_ID" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Get the structured config-v2 for a device
curl -s "http://localhost:8000/api/v1/devices/$DEVICE_ID/config-v2" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### Check device token auth

Daemon-authenticated endpoints require the device token:

```bash
# Heartbeat
curl -s -X POST "http://localhost:8000/api/v1/devices/$DEVICE_ID/heartbeat" \
  -H "Authorization: Bearer $DEVICE_TOKEN"

# Report endpoint
curl -s -X POST "http://localhost:8000/api/v1/devices/$DEVICE_ID/endpoint" \
  -H "Authorization: Bearer $DEVICE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"endpoint":"203.0.113.5","port":51820,"source":"stun"}'
```

---

## Verifying WireGuard Connectivity

On the enrolled device, check the local WireGuard interface:

```bash
# Show interface status
sudo wg show

# Check for handshake
sudo wg show midscale0 latest-handshakes

# Ping another device on the VPN
ping 10.100.0.2
```

Expected `wg show` output:

```
interface: midscale0
  public key: <device-public-key>
  private key: (hidden)
  listening port: 51820

peer: <server-public-key>
  endpoint: <server-ip>:51820
  allowed ips: 10.100.0.0/24
  latest handshake: 5 seconds ago
  transfer: 1.23 KiB received, 4.56 KiB sent
```

---

## Choosing Topology

Midscale supports three topology modes. The choice affects which peers
appear in each device's WireGuard config and how traffic flows.

| Topology | Traffic Flow | Config Size | Best For |
|----------|-------------|-------------|----------|
| **Star** | All traffic goes through the server hub | Small | Simple setups, hub‑and‑spoke |
| **Mesh** | Direct peer-to-peer for all pairs | Large | Performance‑sensitive, trusted networks |
| **Hybrid** | Direct when endpoints known, hub fallback otherwise | Medium | Mixed environments |

### Star (default)

Every device connects only to the server. The server forwards traffic
between devices. Minimal config, central routing, single point of
failure.

```
Device A ───▶ Server ◀─── Device B
```

Set per-network:

```bash
curl -s -X PUT "http://localhost:8000/api/v1/networks/$NETWORK_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"topology": "star"}'
```

### Mesh

Every device has a WireGuard peer entry for every other device. When
endpoints are known via STUN or probing, traffic flows directly between
peers with no server involvement.

```
Device A ◀───▶ Device B
  ▲               ▲
  │               │
  ▼               ▼
Device C ◀───▶ Device D
```

Requires endpoint discovery (STUN) and probing for all peers. Best
performance, but config grows as O(n peers).

```bash
curl -s -X PUT "http://localhost:8000/api/v1/networks/$NETWORK_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"topology": "mesh"}'
```

### Hybrid

Devices get direct peer entries when endpoint candidates are available.
Peers without known endpoints are included without an endpoint — the
server (hub) handles routing for those peers.

```bash
curl -s -X PUT "http://localhost:8000/api/v1/networks/$NETWORK_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"topology": "hybrid"}'
```

### Global default

Set `WIREGUARD_TOPOLOGY=mesh` (or `hybrid`) in `.env` to change the
default for all networks. Per-network settings override the global
default.

---

## Using MagicDNS

MagicDNS assigns DNS names to each device in the format
`<device-name>.<network-name>.<domain>`. It requires CoreDNS and a
DNS domain configuration.

### Enable MagicDNS

In `.env`:

```env
DNS_ENABLED=true
DNS_DOMAIN=wg.midscale
```

The backend writes CoreDNS zone files to `DNS_ZONES_PATH`
(default: `/etc/coredns/zones`) and optionally reloads CoreDNS
via `DNS_COREDNS_RELOAD_CMD`.

### Add DNS entries

Via the dashboard:

1. Open the network detail page
2. Go to the **DNS** tab
3. Add entries mapping domains to IP addresses

Via the API:

```bash
curl -s -X POST "http://localhost:8000/api/v1/networks/$NETWORK_ID/dns" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"domain":"files.office.wg.midscale","address":"10.100.0.5"}'
```

### Configure devices

Ensure enrolled devices have the DNS server address in their WireGuard
config. Device configs include the DNS setting when `dns_enabled=True`
(default).

---

## Using Subnet Routers

Subnet routers advertise access to additional networks beyond the
WireGuard VPN. For example, you can advertise `10.0.0.0/16` so other
devices can reach your local LAN through the VPN.

### Advertise a route

From the device (after enrollment):

```bash
# Via the daemon (set MIDSCALE_ADVERTISED_ROUTES in env)
export MIDSCALE_ADVERTISED_ROUTES="10.0.0.0/16,192.168.1.0/24"

# Or via the API from any authenticated device
curl -s -X POST "http://localhost:8000/api/v1/routes/devices/$DEVICE_ID/advertise" \
  -H "Authorization: Bearer $DEVICE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"prefix": "10.0.0.0/16", "is_exit_node": false}'
```

### Approve a route

Routes must be approved by an admin before they are distributed:

```bash
curl -s -X PUT "http://localhost:8000/api/v1/routes/$ROUTE_ID/approve" \
  -H "Authorization: Bearer $TOKEN"
```

### List routes

```bash
curl -s "http://localhost:8000/api/v1/routes" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Approved routes appear in each device's config-v2 as additional
`AllowedIPs` entries on the advertising peer.

---

## Using Exit Nodes

An exit node is a device that forwards all internet traffic from other
VPN clients. This routes the client's traffic through the exit node's
network connection.

### A. Making a device act as an exit node

Advertise `0.0.0.0/0` with `is_exit_node=true`:

```bash
curl -s -X POST "http://localhost:8000/api/v1/routes/devices/$DEVICE_ID/advertise" \
  -H "Authorization: Bearer $DEVICE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"prefix": "0.0.0.0/0", "is_exit_node": true}'
```

Optionally also advertise `::/0` if IPv6 is supported:

```bash
curl -s -X POST "http://localhost:8000/api/v1/routes/devices/$DEVICE_ID/advertise" \
  -H "Authorization: Bearer $DEVICE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"prefix": "::/0", "is_exit_node": true}'
```

An administrator must then approve the route:

```bash
curl -s -X PUT "http://localhost:8000/api/v1/routes/$ROUTE_ID/approve" \
  -H "Authorization: Bearer $TOKEN"
```

### B. Selecting an exit node from another device

Once an exit node is approved, any device can use it by setting
`exit_node_id` to the exit node's device ID:

```bash
curl -s -X PUT "http://localhost:8000/api/v1/devices/$CLIENT_DEVICE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"exit_node_id": "'$EXIT_NODE_DEVICE_ID'"}'
```

The client's config-v2 will include the exit node's public key and
`0.0.0.0/0, ::/0` in the allowed IPs of the exit node peer.

### C. Disabling exit node use

To stop using an exit node, set `exit_node_id` to `null` on the client:

```bash
curl -s -X PUT "http://localhost:8000/api/v1/devices/$CLIENT_DEVICE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"exit_node_id": null}'
```

---

## NAT Traversal

Midscale implements a layered NAT traversal strategy. Each layer
attempts to establish direct connectivity; if it fails, the next layer
is tried.

```
STUN Discovery → Endpoint Probing → Hole Punching → Relay Fallback
```

### STUN (RFC 5389)

The backend includes a built-in STUN server on UDP 3478. Each enrolled
device (via `midscaled`) periodically sends STUN Binding Requests to
discover its public IP and port as seen from the server.

```bash
# Verify STUN is running
curl -s http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('STUN:', d['stun'])"
```

The daemon reports discovered endpoints with `source="stun"` including
both `local_ip` and `public_ip`.

### Endpoint Discovery & Probing

The daemon periodically probes known endpoint candidates for
reachability and latency. Results are reported to the server, which
computes a score for each endpoint.

```bash
# Check probe results via device config-v2
curl -s "http://localhost:8000/api/v1/devices/$DEVICE_ID/config-v2" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; cfg=json.load(sys.stdin); [print(json.dumps(p.get('endpoint_candidates',[]),indent=2)) for p in cfg.get('peers',[]) if p.get('endpoint_candidates')]"
```

Each endpoint candidate includes:

```json
{
    "endpoint": "203.0.113.5",
    "port": 51820,
    "source": "stun",
    "local_ip": "192.168.1.10",
    "public_ip": "203.0.113.5",
    "reachable": true,
    "latency_ms": 12,
    "score": 85,
    "preferred": true
}
```

Endpoints are sorted by score, with the highest-scoring endpoint marked
as `preferred=true`.

### UDP Hole Punching

When a mesh or hybrid topology is configured and direct endpoints are
known, the server coordinates UDP hole punching sessions between peers.

The hole punching flow:

1. **Request**: Device A requests a punch session to Device B
2. **Coordinate**: Server builds candidate pairs from both devices'
   endpoint candidates
3. **Instruct**: Both devices receive the candidate pairs via
   WebSocket
4. **Punch**: Each device sends simultaneous UDP datagrams to the
   other's candidates
5. **Validate**: When a response is received, connectivity is validated
6. **Promote**: The successful endpoint is promoted to preferred with a
   score boost

### Relay Fallback

When UDP hole punching fails (after retries), the server automatically
creates a DERP-style TCP relay session. The relay relays traffic
between devices that cannot establish direct connectivity.

The relay fallback flow:

1. Hole punching fails for a peer pair
2. Server detects consecutive failures (≥2) and creates a relay session
3. Server emits a `relay.fallback` event
4. Daemon connects to the TCP relay server
5. Traffic is relayed through the server until direct connectivity can
   be re-established

**Limitations:**

- The relay is a minimal TCP relay, not a full-featured DERP with
  HTTP-level tunneling, multi-region, or NAT traversal inside relay.
- Symmetric NAT clients may still require the relay for all traffic.
- There is no automatic upgrade from relay to direct path yet —
  re-punching must be triggered manually or by a subsequent
  reconciliation cycle.

---

## Monitoring

### Health endpoints

```bash
# Liveness probe — process alive?
curl -s http://localhost:8000/health/live

# Readiness probe — accepting traffic?
curl -s http://localhost:8000/health/ready

# Startup probe — initialization complete?
curl -s http://localhost:8000/health/startup

# Full health summary
curl -s http://localhost:8000/health | python3 -m json.tool
```

### Prometheus metrics

Exposed at `http://localhost:8000/metrics`. Key metrics:

```
# Controller
midscale_controller_runs_total
midscale_controller_peers_added_total
midscale_controller_errors_total

# Devices
midscale_devices_total
midscale_devices_online
midscale_device_enrollment_total

# NAT
midscale_nat_punch_total
midscale_nat_connectivity_total
midscale_nat_session_active

# Relay
midscale_relay_sessions_total
midscale_relay_connections_active
midscale_relay_fallback_total
midscale_relay_bytes_total

# WebSocket
midscale_websocket_connections
midscale_websocket_messages_sent_total

# Endpoint probing
midscale_endpoint_probe_total
midscale_endpoint_reachable_total
midscale_endpoint_score_updates_total
```

### Docker health

```bash
docker compose ps
docker compose logs --tail=50 backend
```

---

## Audit Logs

All mutations are logged as structured audit events. Query audit logs
via the API:

```bash
# List recent audit events
curl -s "http://localhost:8000/api/v1/audit?limit=20" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Filter by action
curl -s "http://localhost:8000/api/v1/audit?action=device.enroll&limit=10" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Audit events capture:

- **Action**: `auth.login`, `network.create`, `device.enroll`,
  `device.revoke`, `preauth_key.create`, `acl.create`, etc.
- **Actor**: User ID or device ID who performed the action
- **Target**: The resource that was created/modified/deleted
- **Timestamp**: ISO 8601 UTC
- **Details**: Additional context (IP address, changes, etc.)

---

## Config Versions

### Config v1 (legacy)

The original INI-format WireGuard config. Generated via:

```bash
curl -s "http://localhost:8000/api/v1/devices/$DEVICE_ID/config"
```

Returns a plain-text `[Interface]` + `[Peer]` block. Includes the
private key for server-owned devices. **Deprecated** — use config-v2
for new deployments.

### Config v2 (recommended)

Structured JSON format without the private key (node-owned devices
inject their local private key). Generated via:

```bash
curl -s "http://localhost:8000/api/v1/devices/$DEVICE_ID/config-v2" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Advantages:

- **No private key in transit**: Node-owned devices keep their key
  entirely local
- **Deterministic hash**: SHA-256 hash of the config content for
  idempotent application. The `generated_at` timestamp is metadata
  and not included in hash input. Secrets (private keys, device
  tokens) are never included in config-v2 or its hash input
- **Revision tracking**: Monotonic timestamp-based revision number
- **Endpoint candidates**: Structured list of candidate endpoints with
  scores, reachability, and latency
- **Relay candidates**: Relay server info when direct connectivity is
  unavailable
- **Relay fallback flag**: Per-peer indication that relay fallback is
  active

Example config-v2:

```json
{
    "interface": {
        "address": "10.100.0.5/24",
        "dns": ["10.100.0.1"],
        "mtu": null
    },
    "peers": [
        {
            "public_key": "<peer-pubkey>",
            "allowed_ips": ["10.100.0.0/24"],
            "endpoint": "203.0.113.10:51820",
            "endpoint_port": 51820,
            "endpoint_candidates": [
                {
                    "endpoint": "203.0.113.10",
                    "port": 51820,
                    "reachable": true,
                    "latency_ms": 12,
                    "score": 85,
                    "preferred": true
                }
            ],
            "relay_fallback": false,
            "relay_required": false,
            "relay_candidates": null
        }
    ],
    "routes": [],
    "exit_node": null,
    "version": "2",
    "revision": "1715000000",
    "hash": "sha256-abc123..."
}
```

---

## Troubleshooting

### Device not appearing online

```bash
# Check backend logs
docker compose logs --tail=50 backend

# Check if the daemon is running
sudo wg show

# Manually send a heartbeat
curl -s -X POST "http://localhost:8000/api/v1/devices/$DEVICE_ID/heartbeat" \
  -H "Authorization: Bearer $DEVICE_TOKEN"
```

### Heartbeat returns 401

The device token is invalid or expired. Re-enroll the device:

```bash
midscaled enroll --server https://... --preauth-key "..." --name my-device --apply
```

### Config not applying

```bash
# Verify the daemon received the config
journalctl -u midscaled --no-pager -n 50

# Force a reconcile
# (send SIGUSR1 or restart the daemon)
```

### Hole punching failing

```bash
# Check if NAT traversal is enabled
docker compose exec backend python -c "
from app.config import settings
print(f'STUN enabled: {settings.stun_enabled}')
print(f'RELAY enabled: {settings.relay_enabled}')
"

# Verify STUN server is responding
curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin)['stun'])"
```

### Relay fallback not working

```bash
# Verify relay server is running
curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin)['relay'])"

# Check daemon relay config
# Ensure MIDSCALE_RELAY_ENABLED=true and MIDSCALE_RELAY_HOST points to the server
```

### Cannot connect to the web UI

```bash
# Verify all services are up
docker compose ps

# Check nginx logs
docker compose logs frontend

# Check backend API directly
curl -s http://localhost:8000/health
```

### Database issues

```bash
# Check migration status
docker compose exec backend alembic current

# Run pending migrations
docker compose exec backend alembic upgrade head
```

---

## Security Notes

- **Always set a strong `SECRET_KEY`** in production. Use
  `openssl rand -hex 32`.
- **Use HTTPS** with a TLS reverse proxy (nginx, Caddy, Traefik) in
  production. The built-in frontend nginx can terminate TLS.
- **Pre-auth keys should expire**. Use the shortest practical
  expiration for headless enrollment.
- **Device tokens are bearer tokens**. Treat them like passwords.
  Rotate tokens periodically via the API or by re-enrolling.
- **Device tokens are returned only once** — at enrollment or
  rotation. The backend stores only the bcrypt hash and token prefix.
  Raw tokens cannot be recovered from the backend.
- **Node-owned devices keep private keys local**. The server never sees
  the private key. Server-owned devices have keys encrypted at rest
  with Fernet.
- **Rate limiting is on by default**. Adjust limits in `.env` if
  needed, but keep auth and register limits low.
- **Audit logging captures all mutations**. Monitor audit logs for
  unexpected device enrollments or network changes.
- **No mTLS**: Communication relies on bearer tokens. Use a VPN or
  WireGuard itself to protect the control plane API in sensitive
  deployments.
- **Configs are not individually signed**: A compromised server could
  serve malicious configs. Deploy with server integrity controls.

---

## Current Limitations

### NAT Traversal

- The STUN implementation discovers the mapped address but does NOT
  classify NAT type (full-cone, restricted, port-restricted, symmetric).
- UDP hole punching works best with endpoint-aware topologies
  (mesh/hybrid) and may fail with symmetric NAT.
- The TCP relay fallback is a minimal DERP-style relay, NOT full
  Tailscale DERP parity. There is no HTTP-level tunneling,
  multi-region routing, or automatic direct-path upgrade after relay
  activation.
- There is no STUN over TCP/TLS — only UDP is supported.
- Path quality scoring is based on reachability and latency only. No
  jitter, bandwidth, or packet loss tracking.

### Control Plane

- Single-node backend with no built-in horizontal scaling or high
  availability.
- WebSocket connections are in-process — multi-backend deployments
  would need a shared connection registry.
- No cross-region replication.

### Client Support

- No native mobile apps (iOS/Android).
- The `midscaled` daemon is Python-based (not Go). It requires Python
  3.12+ on each client machine.
- No automatic upgrade from relay to direct path after connectivity
  improves.

### WireGuard

- No MTU negotiation or PMTUD — MTU is hardcoded.
- No bandwidth-aware routing or congestion-aware path selection.
- No multi-path or failover between endpoints beyond the fallback
  logic.
