import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.device import Device
from app.models.network import Network
from app.models.route import AdvertisedRoute
from app.services.dns_provider import CoreDNSFileProvider, DNSProvider, NoopDNSProvider
from app.services.dns_records import sync_network_dns
from app.services.event_bus import EventBus
from app.services.event_types import (
    Event,
    EVENT_DNS_UPDATED,
    EVENT_DEVICE_ONLINE,
    EVENT_DEVICE_OFFLINE,
    EVENT_PEER_SYNCED,
)
from app.services.metrics import (
    CONTROLLER_ERRORS,
    CONTROLLER_PEERS_ADDED,
    CONTROLLER_PEERS_REMOVED,
    CONTROLLER_RUN_DURATION,
    CONTROLLER_RUNS,
    DNS_SYNC_DURATION,
)
from app.services.wg_adapter import WireGuardAdapter, WgCliAdapter, WgMockAdapter
from app.services.wg_exceptions import (
    WireGuardCommandError,
    WireGuardInterfaceNotFound,
    WireGuardKeyError,
)
from app.services.wg_models import (
    DesiredPeer,
    PeerDiff,
    ReconciliationResult,
    WGPeer,
)

logger = structlog.get_logger(__name__)


def _compute_peer_diff(
    desired_peers: list[DesiredPeer],
    actual_keys: set[str],
) -> PeerDiff:
    diff = PeerDiff()
    desired_keys = {p.public_key for p in desired_peers if not p.remove}
    remove_keys = {p.public_key for p in desired_peers if p.remove}

    for peer in desired_peers:
        if peer.remove:
            if peer.public_key in actual_keys:
                diff.to_remove.append(peer)
        elif peer.public_key not in actual_keys:
            diff.to_add.append(peer)
        elif peer.public_key in actual_keys:
            diff.to_update.append(peer)

    orphaned = actual_keys - desired_keys - remove_keys
    for key in orphaned:
        diff.to_remove.append(DesiredPeer(public_key=key, remove=True))

    return diff


class WireGuardController:
    """Reconciliation controller for WireGuard interfaces.

    Implements the controller pattern:
    1. Read desired state from DB (source of truth)
    2. Read actual state from WireGuard runtime
    3. Compute diff
    4. Apply changes idempotently
    5. Update runtime metadata back to DB

    Runs as an asyncio background task with configurable interval.
    """

    _CLEANUP_INTERVAL_CYCLES = 120  # ~1 hour at 30s interval

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        adapter: Optional[WireGuardAdapter] = None,
        dns_provider: Optional[DNSProvider] = None,
        event_bus: Optional[EventBus] = None,
        interval_seconds: int = 30,
    ):
        self._session_factory = session_factory
        self._adapter = adapter or self._create_adapter()
        self._dns_provider = dns_provider or self._create_dns_provider()
        self._event_bus = event_bus
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_run: Optional[datetime] = None
        self._last_results: list[ReconciliationResult] = []
        self._cycle_count = 0

    def _create_dns_provider(self) -> DNSProvider:
        if not settings.dns_enabled:
            logger.info("dns management disabled")
            return NoopDNSProvider()
        provider = CoreDNSFileProvider(
            zones_path=settings.dns_zones_path,
            reload_cmd=settings.dns_coredns_reload_cmd or None,
        )
        logger.info(
            "using coredns file provider",
            zones_path=settings.dns_zones_path,
        )
        return provider

    def _create_adapter(self) -> WireGuardAdapter:
        import subprocess
        try:
            subprocess.run(
                [settings.wireguard_binary, "version"],
                capture_output=True,
                timeout=5,
            )
            logger.info("using wg cli adapter", binary=settings.wireguard_binary)
            return WgCliAdapter(wg_binary=settings.wireguard_binary)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("wg binary not found, using mock adapter")
            return WgMockAdapter()

    async def start(self) -> None:
        if self._running:
            logger.warning("controller already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "wireguard controller started",
            interval_seconds=self._interval,
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
        logger.info("wireguard controller stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_run(self) -> Optional[datetime]:
        return self._last_run

    @property
    def last_results(self) -> list[ReconciliationResult]:
        return self._last_results

    async def _run_loop(self) -> None:
        backoff = 1
        max_backoff = 300
        while self._running:
            try:
                await self._reconcile_all()
                backoff = 1
            except Exception:
                logger.exception("unexpected error in reconciliation loop")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue

            self._last_run = datetime.now(timezone.utc)
            await asyncio.sleep(self._interval)

    async def _reconcile_all(self) -> None:
        try:
            async with self._session_factory() as session:
                interfaces = await self._get_managed_interfaces(session)
                for interface in interfaces:
                    result = await self._reconcile_interface(session, interface)
                    self._last_results.append(result)
                    if result.errors:
                        for err in result.errors:
                            logger.error(
                                "reconciliation error",
                                interface=interface,
                                error=err,
                            )
                    await self._publish_peer_sync_event(result)

                await self._sync_dns(session)

                self._cycle_count += 1
                if self._cycle_count >= self._CLEANUP_INTERVAL_CYCLES:
                    await self._cleanup_stale_peers(session)
                    self._cycle_count = 0

            if settings.dns_enabled:
                await self._dns_provider.reload()
        except Exception:
            logger.exception("failed to reconcile all interfaces")

    async def _get_managed_interfaces(
        self, session: AsyncSession
    ) -> set[str]:
        result = await session.execute(
            select(Network.interface_name).distinct()
        )
        interfaces = {
            row[0] or settings.wireguard_interface
            for row in result
        }
        if not interfaces:
            interfaces = {settings.wireguard_interface}
        return interfaces

    async def _reconcile_interface(
        self,
        session: AsyncSession,
        interface: str,
    ) -> ReconciliationResult:
        start = time.monotonic()
        result = ReconciliationResult(interface=interface)

        try:
            if not await self._adapter.interface_exists(interface):
                logger.info(
                    "interface not found, skipping",
                    interface=interface,
                )
                result.duration_ms = (time.monotonic() - start) * 1000
                return result

            desired = await self._get_desired_peers(session, interface)
            actual_state = await self._adapter.get_interface_state(interface)
            actual_keys = {p.public_key for p in actual_state.peers}

            diff = _compute_peer_diff(desired, actual_keys)

            for peer in diff.to_remove:
                try:
                    await self._adapter.remove_peer(interface, peer.public_key)
                    result.peers_removed += 1
                    logger.info(
                        "peer removed",
                        interface=interface,
                        public_key=peer.public_key[:16],
                    )
                except (WireGuardInterfaceNotFound, WireGuardKeyError) as e:
                    result.errors.append(f"remove {peer.public_key[:16]}: {e}")

            for peer in diff.to_add:
                try:
                    await self._adapter.add_peer(
                        interface=interface,
                        public_key=peer.public_key,
                        allowed_ips=peer.allowed_ips,
                    )
                    result.peers_added += 1
                    logger.info(
                        "peer added",
                        interface=interface,
                        public_key=peer.public_key[:16],
                        allowed_ips=peer.allowed_ips,
                    )
                except (WireGuardInterfaceNotFound, WireGuardKeyError) as e:
                    result.errors.append(f"add {peer.public_key[:16]}: {e}")

            await self._sync_runtime_metadata(
                session, interface, actual_state.peers
            )

        except WireGuardInterfaceNotFound:
            logger.info(
                "interface disappeared during reconciliation",
                interface=interface,
            )
        except WireGuardCommandError as e:
            result.errors.append(f"command error: {e}")

        duration = (time.monotonic() - start) * 1000
        result.duration_ms = duration
        CONTROLLER_RUNS.labels(interface=interface).inc()
        CONTROLLER_RUN_DURATION.labels(interface=interface).observe(duration / 1000.0)
        CONTROLLER_PEERS_ADDED.labels(interface=interface).inc(result.peers_added)
        CONTROLLER_PEERS_REMOVED.labels(interface=interface).inc(result.peers_removed)
        if result.errors:
            CONTROLLER_ERRORS.labels(interface=interface).inc(len(result.errors))
        return result

    async def _get_desired_peers(
        self,
        session: AsyncSession,
        interface: str,
    ) -> list[DesiredPeer]:
        result = await session.execute(
            select(Device, Network)
            .join(Network, Device.network_id == Network.id)
            .where(
                Device.is_active,
                Device.public_key.isnot(None),
                Device.ip_address.isnot(None),
            )
        )
        rows = result.all()

        interface_devices: list[tuple[Device, Network]] = []
        for device, network in rows:
            net_iface = network.interface_name or settings.wireguard_interface
            if net_iface == interface and device.name != "__midscale_server__":
                interface_devices.append((device, network))

        route_result = await session.execute(
            select(AdvertisedRoute).where(
                AdvertisedRoute.approved,
                AdvertisedRoute.enabled,
            )
        )
        all_routes = route_result.scalars().all()
        routes_by_device: dict[str, list[str]] = {}
        for r in all_routes:
            did = str(r.device_id)
            if did not in routes_by_device:
                routes_by_device[did] = []
            routes_by_device[did].append(r.prefix)

        peers: list[DesiredPeer] = []
        for device, network in interface_devices:
            allowed_ips = [f"{device.ip_address}/32"]
            extra = routes_by_device.get(str(device.id), [])
            allowed_ips.extend(extra)
            peers.append(
                DesiredPeer(
                    public_key=device.public_key,
                    allowed_ips=allowed_ips,
                    remove=False,
                )
            )
        return peers

    async def _sync_runtime_metadata(
        self,
        session: AsyncSession,
        interface: str,
        runtime_peers: list[WGPeer],
    ) -> None:
        now = datetime.now(timezone.utc)
        for rp in runtime_peers:
            result = await session.execute(
                select(Device).where(Device.public_key == rp.public_key)
            )
            device = result.scalar_one_or_none()
            if device is None:
                continue
            changed = False
            was_online = (
                device.last_handshake is not None
                and (now - device.last_handshake).total_seconds() < 180
            )
            if rp.latest_handshake and (
                device.last_handshake is None
                or rp.latest_handshake > device.last_handshake
            ):
                device.last_handshake = rp.latest_handshake
                changed = True
            is_online = (
                device.last_handshake is not None
                and (now - device.last_handshake).total_seconds() < 180
            )
            if changed and is_online and not was_online:
                await self._publish_device_online_event(
                    str(device.id), device.name
                )
            elif changed and not is_online and was_online:
                await self._publish_device_offline_event(
                    str(device.id),
                    device.name,
                    device.last_handshake.isoformat() if device.last_handshake else "",
                )
            if changed:
                device.updated_at = now
        await session.flush()

    async def _publish_peer_sync_event(
        self, result: ReconciliationResult
    ) -> None:
        if not self._event_bus:
            return
        event = Event(
            event_type=EVENT_PEER_SYNCED,
            data={
                "interface": result.interface,
                "peers_added": result.peers_added,
                "peers_removed": result.peers_removed,
                "peers_updated": result.peers_updated,
                "errors": result.errors,
                "duration_ms": result.duration_ms,
            },
        )
        await self._event_bus.publish(event)

    async def _publish_device_online_event(
        self, device_id: str, device_name: str
    ) -> None:
        if not self._event_bus:
            return
        event = Event(
            event_type=EVENT_DEVICE_ONLINE,
            data={"device_id": device_id, "device_name": device_name},
        )
        await self._event_bus.publish(event)

    async def _publish_device_offline_event(
        self, device_id: str, device_name: str, last_seen: str
    ) -> None:
        if not self._event_bus:
            return
        event = Event(
            event_type=EVENT_DEVICE_OFFLINE,
            data={
                "device_id": device_id,
                "device_name": device_name,
                "last_seen": last_seen,
            },
        )
        await self._event_bus.publish(event)

    async def _sync_dns(self, session: AsyncSession) -> None:
        if not settings.dns_enabled:
            return
        dns_start = time.monotonic()
        result = await session.execute(select(Network))
        networks = result.scalars().all()
        for network in networks:
            try:
                await sync_network_dns(
                    session, network.id, self._dns_provider
                )
            except Exception as e:
                logger.error(
                    "dns sync failed for network",
                    network_id=str(network.id),
                    network_name=network.name,
                    error=str(e),
                )
        DNS_SYNC_DURATION.observe(time.monotonic() - dns_start)
        if self._event_bus and networks:
            await self._event_bus.publish(
                Event(
                    event_type=EVENT_DNS_UPDATED,
                    data={"networks_synced": len(networks)},
                )
            )

    async def _cleanup_stale_peers(self, session: AsyncSession) -> None:
        """Deactivate devices that haven't been seen in over 7 days.

        A device is considered stale when it has no recent heartbeat or
        endpoint report, and its last handshake is older than the
        threshold. Stale devices are marked inactive so the controller
        removes them from the WireGuard interface on the next cycle.
        """
        from datetime import timedelta
        from sqlalchemy import or_
        stale_threshold = datetime.now(timezone.utc) - timedelta(days=settings.stale_device_days)
        result = await session.execute(
            select(Device).where(
                Device.is_active,
                or_(
                    Device.last_handshake.is_(None),
                    Device.last_handshake < stale_threshold,
                ),
                Device.created_at < stale_threshold,
            )
        )
        stale_devices = result.scalars().all()
        for device in stale_devices:
            logger.info(
                "deactivating stale device",
                device_id=str(device.id),
                device_name=device.name,
                last_handshake=str(device.last_handshake),
            )
            device.is_active = False
            device.updated_at = datetime.now(timezone.utc)
        if stale_devices:
            await session.flush()
            logger.info(
                "stale peer cleanup complete",
                count=len(stale_devices),
            )

    async def reconcile_all_now(self) -> list[ReconciliationResult]:
        self._last_results = []
        await self._reconcile_all()
        return self._last_results

    async def reconcile_interface_now(
        self, interface: str
    ) -> ReconciliationResult:
        async with self._session_factory() as session:
            return await self._reconcile_interface(session, interface)
