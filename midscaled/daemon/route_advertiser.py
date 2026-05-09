"""Subnet route advertiser for the midscaled daemon.

Advertises configured LAN subnet routes to the Midscale control plane.
The daemon periodically reports its locally-configured routes so the
server can include them in other peers' WireGuard AllowedIPs.

Subnet router nodes must also enable IP forwarding and NAT for traffic
to reach the advertised subnets. This module provides helpers for that.

Configure with ``MIDSCALE_ADVERTISED_ROUTES`` env var (comma-separated
CIDRs), e.g.::

    MIDSCALE_ADVERTISED_ROUTES=192.168.1.0/24,10.0.0.0/16
"""

import asyncio
from typing import Optional

import structlog

from daemon.api_client import MidscaleAPIClient
from daemon.config import DaemonConfig
from daemon.models import DaemonState

logger = structlog.get_logger(__name__)


class RouteAdvertiser:
    """Periodically advertises configured LAN subnet routes to the server.

    Each route is advertised to the control plane. The server validates
    the prefix, checks for conflicts, and creates an unapproved route
    record requiring admin approval before it becomes active.
    """

    def __init__(
        self,
        config: DaemonConfig,
        api_client: MidscaleAPIClient,
    ):
        self._config = config
        self._api = api_client
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self, state: DaemonState) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._run_loop(state)
        )
        logger.info(
            "route advertiser started",
            routes=self._config.advertised_routes,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("route advertiser stopped")

    async def _run_loop(self, state: DaemonState) -> None:
        while self._running:
            try:
                for prefix in self._config.advertised_routes:
                    result = await self._api.advertise_route(prefix)
                    if result.success:
                        logger.info(
                            "route advertised",
                            prefix=prefix,
                        )
                    else:
                        logger.warning(
                            "route advertisement failed",
                            prefix=prefix,
                            error=result.error,
                        )
            except Exception as e:
                logger.error("route advertisement error", error=str(e))

            await asyncio.sleep(300)

    @staticmethod
    async def ensure_ip_forwarding() -> bool:
        """Enable IP forwarding on the system.

        Required for subnet router and exit node operation.
        Returns True if forwarding is already enabled or was
        successfully enabled.
        """
        import subprocess

        try:
            result = subprocess.run(
                ["sysctl", "-n", "net.ipv4.ip_forward"],
                capture_output=True, text=True, timeout=10,
            )
            if result.stdout.strip() == "1":
                return True

            subprocess.run(
                ["sysctl", "-w", "net.ipv4.ip_forward=1"],
                capture_output=True, timeout=10,
            )
            logger.info("enabled net.ipv4.ip_forward")
            return True
        except Exception as e:
            logger.error("failed to enable ip forwarding", error=str(e))
            return False

    @staticmethod
    async def ensure_nat(interface: str, wg_interface: str) -> bool:
        """Ensure NAT (masquerade) is set up between the physical interface
        and the WireGuard interface.

        This allows traffic from WireGuard peers to reach the internet
        (or advertised subnets) through this node.

        Returns True if NAT was already configured or was successfully
        added.
        """
        import subprocess

        rule = f"-s 100.64.0.0/10 -o {interface} -j MASQUERADE"
        check = [
            "iptables", "-t", "nat", "-C", "POSTROUTING",
        ] + rule.split()

        try:
            result = subprocess.run(check, capture_output=True, timeout=10)
            if result.returncode == 0:
                return True

            add = [
                "iptables", "-t", "nat", "-A", "POSTROUTING",
            ] + rule.split()
            subprocess.run(add, capture_output=True, timeout=10)
            logger.info(
                "added NAT masquerade rule",
                interface=interface,
                wg_interface=wg_interface,
            )
            return True
        except Exception as e:
            logger.error("failed to ensure NAT", error=str(e))
            return False
