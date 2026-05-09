"""Midscale protocol and schema constants.

All versioned contracts used across the platform are defined here
to ensure a single source of truth.
"""

# Config V2 contract
CONFIG_V2_VERSION = "2"
CONFIG_V2_SCHEMA_VERSION = "1"
CONFIG_V2_MIN_DAEMON_VERSION = "0.1.0"

# Topology types
TOPOLOGY_STAR = "star"
TOPOLOGY_MESH = "mesh"
TOPOLOGY_HYBRID = "hybrid"

# Event types
EVENT_PEER_SYNCED = "peer.synced"
EVENT_PEER_ADDED = "peer.added"
EVENT_PEER_REMOVED = "peer.removed"
EVENT_DEVICE_ONLINE = "device.online"
EVENT_DEVICE_OFFLINE = "device.offline"
EVENT_DEVICE_ENROLLED = "device.enrolled"
EVENT_DEVICE_REVOKED = "device.revoked"
EVENT_DEVICE_HEARTBEAT = "device.heartbeat"
EVENT_DNS_UPDATED = "dns.updated"
EVENT_NETWORK_CREATED = "network.created"
EVENT_NETWORK_CHANGED = "network.changed"
EVENT_NETWORK_DELETED = "network.deleted"
EVENT_CONFIG_CHANGED = "config.changed"
EVENT_ENDPOINT_REPORTED = "endpoint.reported"
EVENT_ENDPOINT_STALE = "endpoint.stale"
EVENT_ENDPOINT_PROBE = "endpoint.probe"
EVENT_ROUTE_CHANGED = "route.changed"
EVENT_ACL_CHANGED = "acl.changed"

# Event channel prefix
EVENT_CHANNEL_PREFIX = "midscale:event"
