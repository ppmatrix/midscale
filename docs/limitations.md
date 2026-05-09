# Limitations

## NAT Traversal

### Current State
STUN (RFC 5389) is implemented in both the backend and daemon:
- **Backend**: Built-in STUN server (`StunServer` in `app/services/stun_server.py`) listens on UDP port 3478 and responds to Binding Requests per RFC 5389.
- **Daemon**: STUN client (`stun_client.py`) queries the configured STUN servers on each endpoint check interval. Discovers public IP:port as seen from the server.
- **Fallback**: If STUN is unavailable/disbled, the daemon falls back to local IP detection via UDP socket trick.
- **Source tagging**: STUN-discovered endpoints are reported with `source="stun"` and include both `local_ip` and `public_ip`.

### Current State
Peer connectivity probing is implemented:
- **Backend**: `endpoint_scoring.py` computes scores from reachability, latency, failures, and success count. `POST /devices/{id}/probe-result` accepts probe results, updates `DeviceEndpoint` rows with scoring fields, and triggers `config.changed` events.
- **Daemon**: `peer_prober.py` performs lightweight UDP probes against known endpoint candidates. Reports reachability and latency to the control plane for scoring.
- **Config-v2**: Endpoint candidates include `score`, `reachable`, `latency_ms`, and `preferred` fields. Candidates are sorted by descending score with the best marked as `preferred=True`.

### Known Limitations
- **No NAT type classification**: The STUN implementation only discovers the mapped address. It does not classify NAT type (full-cone, restricted, port-restricted, symmetric) via RFC 3489 behavior tests.
- **No DERP relay**: Devices behind symmetric NAT or firewalls that block UDP cannot establish direct WireGuard connections. A DERP relay server (similar to Tailscale's DERP) would be needed for reliable connectivity in such environments.
- **Single STUN server**: The daemon queries the configured STUN servers sequentially (first success wins). There's no parallel query or latency-based selection.
- **No STUN over TCP/TLS**: Only UDP is supported, which may be blocked in restrictive networks.
- **No port prediction**: For symmetric NAT, a series of STUN requests could be used to predict the next port mapping, but this is not implemented.
- **No full UDP hole punching**: Peer probing measures reachability and latency but does not perform full hole punching. Symmetric NAT traversal requires DERP relay.
- **No path quality scoring**: Scores are based on reachability, latency, and failure count only. There is no bandwidth estimation, jitter measurement, or congestion-aware path selection.
- **No multi-path connectivity**: Each peer has one preferred endpoint. There is no multipath or failover between endpoints beyond fallback logic.

## Control Plane

- **Single node**: The backend runs as a single FastAPI process. There is no built-in horizontal scaling or high availability.
- **No sharding**: All device/network state lives in one PostgreSQL database. No cross-region replication logic.
- **WebSocket clustering**: Per-device WebSocket connections are managed in-process. In a multi-backend deployment, a device would need to re-connect to the correct node or the system would need a shared connection registry (e.g., via Redis pub/sub).

## Security

- **No mTLS**: Communication relies on bearer tokens (JWT for users, device tokens for daemons). There is no mutual TLS or certificate-based device identity.
- **Configs are not signed**: Config-v2 payloads are delivered over HTTPS/WSS but are not individually signed. A compromised server could serve malicious configs.
- **No device certificate enrollment**: Device identity is established via pre-auth keys and bearer tokens, not x.509 certificates.
- **No ECDH enrollment**: Private WireGuard keys are generated client-side but are still encrypted at rest in the database for server-owned devices. Node-owned devices keep keys entirely local.

## Client Support

- **No mobile clients**: There are no iOS or Android apps.
- **No CLI installer**: The `midscaled` daemon is planned but not yet fully implemented as a standalone Go binary.

## Performance & Scale

- **Path quality**: Peer probing measures reachability and latency. Jitter, bandwidth, and packet loss are not tracked.
- **No MTU negotiation**: WireGuard MTU is hardcoded or configured manually. There is no PMTUD or automatic MTU adjustment.
- **No bandwidth-aware routing**: All traffic for a given peer goes to the first available endpoint. There is no bandwidth estimation or congeston-aware path selection.
