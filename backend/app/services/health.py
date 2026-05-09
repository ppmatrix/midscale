"""Production-grade health check service.

Implements liveness, readiness, and startup probes.
Each check is async and independently failable.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from app.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class HealthCheckResult:
    healthy: bool
    message: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class HealthStatus:
    healthy: bool
    checks: dict[str, HealthCheckResult] = field(default_factory=dict)
    version: str = "0.1.0"
    timestamp: str = ""


class HealthChecker:
    def __init__(
        self,
        session_factory=None,
        wg_controller=None,
        event_bus=None,
        dns_provider=None,
    ):
        self._session_factory = session_factory
        self._wg_controller = wg_controller
        self._event_bus = event_bus
        self._dns_provider = dns_provider

    async def check_liveness(self) -> HealthStatus:
        checks = {
            "app": HealthCheckResult(healthy=True, message="application running"),
        }
        return self._build_status(checks)

    async def check_readiness(self) -> HealthStatus:
        checks = {}

        checks["database"] = await self._check_database()
        checks["redis"] = await self._check_redis()
        checks["wg_controller"] = self._check_wg_controller()
        checks["event_bus"] = self._check_event_bus()
        checks["dns_provider"] = await self._check_dns_provider()

        return self._build_status(checks)

    async def check_startup(self) -> HealthStatus:
        checks = {}

        checks["database"] = await self._check_database()
        checks["encryption_key"] = self._check_encryption_key()
        checks["config"] = self._check_config()
        checks["wg_adapter"] = self._check_wg_adapter()

        return self._build_status(checks)

    async def _check_database(self) -> HealthCheckResult:
        if not self._session_factory:
            return HealthCheckResult(healthy=False, message="no session factory configured")
        try:
            async with self._session_factory() as session:
                await session.execute(select(1))
            return HealthCheckResult(healthy=True, message="database reachable")
        except Exception as e:
            return HealthCheckResult(
                healthy=False, message=f"database unreachable: {e}"
            )

    async def _check_redis(self) -> HealthCheckResult:
        if not settings.redis_url:
            return HealthCheckResult(healthy=True, message="redis not configured")
        if not self._event_bus:
            return HealthCheckResult(healthy=False, message="event bus not initialized")
        from app.services.metrics import EVENT_BUS_CONNECTED
        try:
            connected = bool(EVENT_BUS_CONNECTED._value.get())
        except Exception:
            connected = False
        if connected:
            return HealthCheckResult(healthy=True, message="redis connected")
        return HealthCheckResult(
            healthy=False, message="redis disconnected — in-memory fallback active"
        )

    def _check_wg_controller(self) -> HealthCheckResult:
        if not settings.wg_controller_enabled:
            return HealthCheckResult(healthy=True, message="controller disabled")
        if not self._wg_controller:
            return HealthCheckResult(healthy=False, message="controller not initialized")
        if self._wg_controller.is_running:
            last_run = self._wg_controller.last_run
            detail = f"controller running, last_run={last_run.isoformat() if last_run else 'never'}"
            return HealthCheckResult(healthy=True, message=detail)
        return HealthCheckResult(
            healthy=False, message="controller not running"
        )

    def _check_event_bus(self) -> HealthCheckResult:
        if not self._event_bus:
            return HealthCheckResult(healthy=False, message="event bus not initialized")
        running = getattr(self._event_bus, "_running", True)
        if running:
            return HealthCheckResult(healthy=True, message="event bus running")
        return HealthCheckResult(healthy=False, message="event bus not running")

    async def _check_dns_provider(self) -> HealthCheckResult:
        if not settings.dns_enabled:
            return HealthCheckResult(healthy=True, message="dns disabled")
        if not self._dns_provider:
            return HealthCheckResult(healthy=False, message="dns provider not configured")
        return HealthCheckResult(healthy=True, message="dns provider configured")

    def _check_encryption_key(self) -> HealthCheckResult:
        try:
            from cryptography.fernet import Fernet
            Fernet(settings.encryption_key.encode())
            return HealthCheckResult(healthy=True, message="encryption key valid")
        except Exception as e:
            return HealthCheckResult(
                healthy=False, message=f"invalid encryption key: {e}"
            )

    def _check_config(self) -> HealthCheckResult:
        missing = []
        if not settings.secret_key or settings.secret_key == "change-me-to-a-real-secret-in-production":
            missing.append("SECRET_KEY is default")
        if not settings.database_url:
            missing.append("DATABASE_URL is empty")
        if missing:
            return HealthCheckResult(
                healthy=False,
                message="required config missing",
                details={"missing": missing},
            )
        return HealthCheckResult(healthy=True, message="all required config present")

    def _check_wg_adapter(self) -> HealthCheckResult:
        import subprocess
        try:
            subprocess.run(
                [settings.wireguard_binary, "version"],
                capture_output=True, timeout=5,
            )
            return HealthCheckResult(healthy=True, message=f"adapter {settings.wireguard_binary} available")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return HealthCheckResult(
                healthy=True,
                message=f"adapter {settings.wireguard_binary} not found — mock mode",
            )

    def _build_status(self, checks: dict[str, HealthCheckResult]) -> HealthStatus:
        all_healthy = all(c.healthy for c in checks.values())
        return HealthStatus(
            healthy=all_healthy,
            checks=checks,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
