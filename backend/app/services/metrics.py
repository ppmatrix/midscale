"""Prometheus metrics for Midscale backend.

Tracks reconciliation, WebSocket, DNS, event bus, and device lifecycle.
All metrics use the `midscale_` prefix for consistent namespace.
"""

from prometheus_client import Counter, Gauge, Histogram

# Controller metrics
CONTROLLER_RUNS = Counter(
    "midscale_controller_runs_total",
    "Total reconciliation cycles",
    ["interface"],
)

CONTROLLER_RUN_DURATION = Histogram(
    "midscale_controller_run_duration_seconds",
    "Reconciliation cycle duration",
    ["interface"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

CONTROLLER_PEERS_ADDED = Counter(
    "midscale_controller_peers_added_total",
    "Peers added to interfaces",
    ["interface"],
)

CONTROLLER_PEERS_REMOVED = Counter(
    "midscale_controller_peers_removed_total",
    "Peers removed from interfaces",
    ["interface"],
)

CONTROLLER_ERRORS = Counter(
    "midscale_controller_errors_total",
    "Reconciliation errors",
    ["interface"],
)

# WebSocket metrics
WS_CONNECTIONS = Gauge(
    "midscale_websocket_connections",
    "Active WebSocket connections",
)

WS_MESSAGES_SENT = Counter(
    "midscale_websocket_messages_sent_total",
    "WebSocket messages broadcast to clients",
)

# Event bus metrics
EVENTS_PUBLISHED = Counter(
    "midscale_events_published_total",
    "Events published to event bus",
    ["event_type"],
)

EVENT_BUS_CONNECTED = Gauge(
    "midscale_event_bus_connected",
    "Whether event bus is connected to Redis (1=connected, 0=in-memory)",
)

# DNS metrics
DNS_ZONES_MANAGED = Gauge(
    "midscale_dns_zones_managed",
    "Number of DNS zones managed by the backend",
)

DNS_SYNC_DURATION = Histogram(
    "midscale_dns_sync_duration_seconds",
    "DNS zone sync duration",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0),
)

# Device metrics
DEVICES_TOTAL = Gauge(
    "midscale_devices_total",
    "Total number of devices",
)

DEVICES_ONLINE = Gauge(
    "midscale_devices_online",
    "Number of devices with recent handshake (<180s)",
)

# API metrics
API_REQUESTS = Counter(
    "midscale_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status"],
)

# Audit metrics
AUDIT_EVENTS = Counter(
    "midscale_audit_events_total",
    "Total audit log events",
    ["action"],
)

# Route metrics
ROUTES_TOTAL = Counter(
    "midscale_routes_total",
    "Total advertised routes",
)

ROUTES_APPROVED = Counter(
    "midscale_routes_approved_total",
    "Routes that have been approved",
)

EXIT_NODES_TOTAL = Counter(
    "midscale_exit_nodes_total",
    "Total exit node advertisements",
)

# Enrollment metrics
DEVICE_ENROLLMENT = Counter(
    "midscale_device_enrollment_total",
    "Device enrollment attempts",
    ["result"],
)

# Daemon auth metrics
DAEMON_AUTH_FAILURES = Counter(
    "midscale_daemon_auth_failures_total",
    "Daemon authentication failures",
    ["reason"],
)

# Rate limit metrics
RATE_LIMIT_BLOCKED = Counter(
    "midscale_rate_limit_blocked_total",
    "Total requests blocked by rate limiter",
    ["limiter", "path"],
)

# Health metrics
HEALTH_CHECK = Gauge(
    "midscale_health_check",
    "Health check outcome (1=healthy, 0=unhealthy)",
    ["probe"],
)
