# Limitations

## NAT Traversal

### Current State
STUN (RFC 5389) is implemented in both the backend and daemon:
- **Backend**: Built-in STUN server (`StunServer` in `app/services/stun_server.py`) listens on UDP port 3478 and responds to Binding Requests per RFC 5389.
- **Daemon**: STUN client (`stun_client.py`) queries the configured STUN servers on each endpoint check interval. Discovers public IP:port as seen from the server.
- **Fallback**: If STUN is unavailable/disbled, the daemon falls back to local IP detection via UDP socket trick.
- **Source tagging**: STUN-discovered endpoints are reported with `source="stun"` and include both `local_ip` and `public_ip`.

### Known Limitations
- **No NAT type classification**: The STUN implementation only discovers the mapped address. It does not classify NAT type (full-cone, restricted, port-restricted, symmetric) via RFC 3489 behavior tests.
- **No connectivity checks**: There is no mechanism to verify that two peers can establish a direct connection before falling back to relay.
- **No DERP relay**: Devices behind symmetric NAT or firewalls that block UDP cannot establish direct WireGuard connections. A DERP relay server (similar to Tailscale's DERP) would be needed for reliable connectivity in such environments.
- **Single STUN server**: The daemon queries the configured STUN servers sequentially (first success wins). There's no parallel query or latency-based selection.
- **No STUN over TCP/TLS**: Only UDP is supported, which may be blocked in restrictive networks.
- **No port prediction**: For symmetric NAT, a series of STUN requests could be used to predict the next port mapping, but this is not implemented.

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

- **Path quality unaware**: The control plane does not measure or score path quality between peers. It simply provides known endpoints.
- **No MTU negotiation**: WireGuard MTU is hardcoded or configured manually. There is no PMTUD or automatic MTU adjustment.
- **No bandwidth-aware routing**: All traffic for a given peer goes to the first available endpoint. There is no bandwidth estimation or congeston-aware path selection.
