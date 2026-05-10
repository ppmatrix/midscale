# Limitations

## NAT Traversal

### Current State

Midscale implements a layered NAT traversal strategy:

1. **STUN** (RFC 5389): Built-in server on UDP 3478 + daemon client.
   Discovers public IP:port per device. Endpoints tagged `source="stun"`.
2. **Endpoint probing**: Daemon probes candidates for reachability and
   latency. Server scores and orders candidates in config-v2.
3. **UDP hole punching**: Coordinated simultaneous UDP send to all
   candidate pairs. Validates bidirectional connectivity.
4. **TCP relay fallback**: Minimal DERP-style relay server for devices
   that cannot establish direct connectivity after hole punching fails.

### Known Limitations

- **No NAT type classification**: STUN discovers the mapped address but
  does not classify NAT type (full-cone, restricted, port-restricted,
  symmetric) via RFC 3489 behavior tests.
- **Relay is minimal TCP relay**: The DERP-style relay is a simple TCP
  transport, not full Tailscale DERP parity. There is no HTTP-level
  tunneling, multi-region routing, or automatic direct-path upgrade
  after relay activation.
- **Symmetric NAT may always require relay**: UDP hole punching is
  unlikely to succeed through symmetric NAT. Devices behind symmetric
  NAT will fall back to TCP relay for all peer traffic.
- **Single STUN server**: The daemon queries configured STUN servers
  sequentially. No parallel query or latency-based selection.
- **No STUN over TCP/TLS**: Only UDP is supported.
- **No port prediction**: For symmetric NAT, a series of STUN requests
  could predict the next port mapping — not implemented.
- **No path quality scoring beyond latency**: Scores based on
  reachability, latency, and failure count. No bandwidth estimation,
  jitter measurement, or congestion-aware path selection.
- **No multi-path connectivity**: Each peer has one preferred endpoint.
  No multipath or failover beyond the relay fallback.
- **No automatic relay→direct upgrade**: Once a relay session is active,
  the system does not automatically re-attempt direct connectivity.
  Manual re-punching or a reconciliation cycle restart is needed.

## Control Plane

- **Single node**: The backend runs as a single FastAPI process. No
  built-in horizontal scaling or high availability.
- **No sharding**: All device/network state lives in one PostgreSQL
  database. No cross-region replication logic.
- **WebSocket clustering**: Per-device WebSocket connections are managed
  in-process. Multi-backend deployments need a shared connection
  registry (e.g., via Redis pub/sub).

## Security

- **No mTLS**: Communication relies on bearer tokens (JWT for users,
  device tokens for daemons). No mutual TLS or certificate-based device
  identity.
- **Configs are not signed**: Config-v2 payloads are delivered over
  HTTPS/WSS but are not individually signed. A compromised server could
  serve malicious configs.
- **No device certificate enrollment**: Device identity is established
  via pre-auth keys and bearer tokens, not x.509 certificates.
- **No ECDH enrollment**: Private WireGuard keys are generated
  client-side but are still encrypted at rest in the database for
  server-owned devices. Node-owned devices keep keys entirely local.

## Client Support

- **No mobile clients**: No iOS or Android apps.
- **No standalone Go binary**: The `midscaled` daemon is Python-based
  and requires Python 3.12+ on each client machine.

## Performance & Scale

- **Path quality**: Peer probing measures reachability and latency.
  Jitter, bandwidth, and packet loss are not tracked.
- **No MTU negotiation**: WireGuard MTU is hardcoded or configured
  manually. No PMTUD or automatic MTU adjustment.
- **No bandwidth-aware routing**: All traffic for a given peer goes to
  the first available endpoint. No bandwidth estimation or congestion-
  aware path selection.
