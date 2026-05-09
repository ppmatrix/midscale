import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DaemonConfig:
    server_url: str = "http://localhost:8000"
    preauth_key: str = ""
    device_name: str = ""
    device_token: str = ""

    interface_name: str = "midscale0"
    wg_binary: str = "wg"
    wg_port: int = 51820

    polling_interval_seconds: int = 30
    heartbeat_interval_seconds: int = 60
    endpoint_check_interval_seconds: int = 120
    ws_enabled: bool = True
    ws_reconnect_delay: float = 5.0
    advertised_routes: list[str] = field(default_factory=list)

    stun_enabled: bool = True
    stun_servers: list[str] = field(default_factory=lambda: [])
    stun_timeout: float = 3.0

    probe_enabled: bool = True
    probe_interval_seconds: int = 180
    probe_timeout: float = 5.0

    state_dir: str = "/var/lib/midscaled"
    config_dir: str = "/etc/midscaled"
    log_dir: str = "/var/log/midscaled"

    tls_verify: bool = True
    request_timeout_seconds: int = 30

    debug: bool = False

    @classmethod
    def load(cls) -> "DaemonConfig":
        return cls(
            server_url=os.environ.get(
                "MIDSCALE_SERVER_URL", "http://localhost:8000"
            ),
            preauth_key=os.environ.get("MIDSCALE_PREAUTH_KEY", ""),
            device_name=os.environ.get(
                "MIDSCALE_DEVICE_NAME", os.uname().nodename
            ),
            device_token=os.environ.get("MIDSCALE_DEVICE_TOKEN", ""),
            interface_name=os.environ.get(
                "MIDSCALE_INTERFACE", "midscale0"
            ),
            wg_binary=os.environ.get("MIDSCALE_WG_BINARY", "wg"),
            wg_port=int(os.environ.get("MIDSCALE_WG_PORT", "51820")),
            polling_interval_seconds=int(
                os.environ.get("MIDSCALE_POLL_INTERVAL", "30")
            ),
            heartbeat_interval_seconds=int(
                os.environ.get("MIDSCALE_HEARTBEAT_INTERVAL", "60")
            ),
            endpoint_check_interval_seconds=int(
                os.environ.get("MIDSCALE_ENDPOINT_INTERVAL", "120")
            ),
            advertised_routes=[
                r.strip()
                for r in os.environ.get("MIDSCALE_ADVERTISED_ROUTES", "").split(",")
                if r.strip()
            ],
            state_dir=os.environ.get(
                "MIDSCALE_STATE_DIR", "/var/lib/midscaled"
            ),
            config_dir=os.environ.get(
                "MIDSCALE_CONFIG_DIR", "/etc/midscaled"
            ),
            log_dir=os.environ.get(
                "MIDSCALE_LOG_DIR", "/var/log/midscaled"
            ),
            tls_verify=os.environ.get("MIDSCALE_TLS_VERIFY", "true").lower()
            == "true",
            request_timeout_seconds=int(
                os.environ.get("MIDSCALE_REQUEST_TIMEOUT", "30")
            ),
            debug=os.environ.get("MIDSCALE_DEBUG", "false").lower()
            == "true",
            ws_enabled=os.environ.get("MIDSCALE_WS_ENABLED", "true").lower()
            == "true",
            ws_reconnect_delay=float(
                os.environ.get("MIDSCALE_WS_RECONNECT_DELAY", "5.0")
            ),
            stun_enabled=os.environ.get("MIDSCALE_STUN_ENABLED", "true").lower()
            == "true",
            stun_servers=[
                s.strip()
                for s in os.environ.get("MIDSCALE_STUN_SERVERS", "").split(",")
                if s.strip()
            ],
            stun_timeout=float(
                os.environ.get("MIDSCALE_STUN_TIMEOUT", "3.0")
            ),
            probe_enabled=os.environ.get("MIDSCALE_PROBE_ENABLED", "true").lower()
            == "true",
            probe_interval_seconds=int(
                os.environ.get("MIDSCALE_PROBE_INTERVAL", "180")
            ),
            probe_timeout=float(
                os.environ.get("MIDSCALE_PROBE_TIMEOUT", "5.0")
            ),
        )
