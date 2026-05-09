import argparse
import asyncio
import os
import signal
import sys
from typing import Optional

import structlog

from daemon.api_client import MidscaleAPIClient
from daemon.config import DaemonConfig
from daemon.endpoint_monitor import EndpointMonitor
from daemon.heartbeat import HeartbeatSender
from daemon.route_advertiser import RouteAdvertiser
from daemon.logging import setup_logging
from daemon.models import DaemonState
from daemon.reconciler import Reconciler
from daemon.state_store import StateStore
from daemon.wg_runtime import WireGuardRuntime
from daemon.ws_client import DaemonWebSocketClient, WebSocketClient

logger = structlog.get_logger(__name__)


async def cmd_enroll(args: argparse.Namespace) -> int:
    """Run the enrollment flow: generate keys, enroll with server, save state."""
    setup_logging(debug=args.debug)
    logger.info("enrolling device", server=args.server, name=args.name)

    config = DaemonConfig(
        server_url=args.server,
        preauth_key=args.preauth_key,
        device_name=args.name,
        state_dir=args.state_dir or "/var/lib/midscaled",
        tls_verify=not args.insecure,
    )

    state_store = StateStore(config.state_dir)
    state_store.ensure_dirs()
    state_store.load()

    if state_store.has_enrollment():
        logger.warning("device is already enrolled")
        return 0

    api_client = MidscaleAPIClient(config)
    wg = WireGuardRuntime(wg_binary=config.wg_binary)

    try:
        private_key, public_key = await wg.generate_keypair()
        if not private_key or not public_key:
            logger.error("failed to generate WireGuard keypair")
            return 1

        result = await api_client.enroll(
            preauth_key=args.preauth_key,
            device_name=args.name,
            public_key=public_key,
        )
        if not result.success:
            logger.error("enrollment failed", error=result.error)
            return 1

        state_store.save_enrollment(
            device_id=result.device_id,
            device_token=result.device_token,
            private_key=private_key,
            network_id=result.network_id,
        )
        state_store.save_identity(result.device_id)

        logger.info(
            "enrollment complete",
            device_id=result.device_id,
            ip_address=result.ip_address,
            network_id=result.network_id,
        )

        if args.apply:
            await _apply_enrolled_config(
                config=config,
                state_store=state_store,
                config_v2=result.config_v2,
                private_key=private_key,
            )

        return 0
    except Exception as e:
        logger.error("enrollment failed unexpectedly", error=str(e))
        return 1
    finally:
        await api_client.close()


async def _apply_enrolled_config(
    config: DaemonConfig,
    state_store: StateStore,
    config_v2: Optional[dict],
    private_key: str,
) -> None:
    from daemon.models import DesiredConfig, DesiredPeer
    from daemon.reconciler import _parse_config_v2

    if not config_v2:
        logger.warning("no config-v2 in enrollment response, skipping apply")
        return

    parsed = _parse_config_v2(config_v2, private_key)
    if not parsed:
        logger.error("failed to parse enrollment config-v2")
        return

    wg = WireGuardRuntime(wg_binary=config.wg_binary)
    interface = config.interface_name
    up = await wg.bring_up_interface(
        interface, parsed.address, parsed.subnet
    )
    if not up:
        logger.error("failed to bring up interface after enrollment")
        return

    ok = await wg.apply_config(interface, parsed)
    if ok:
        logger.info("config applied after enrollment", interface=interface)
    else:
        logger.error("failed to apply config after enrollment")


class MidscaledDaemon:
    """Midscale client daemon — manages local WireGuard tunnel.

    Lifecycle:
    1. Load config
    2. Restore local state
    3. Register if not registered, or enroll if not enrolled
    4. Start reconciliation loop
    5. Start heartbeat
    6. Start endpoint monitor
    7. Wait for shutdown signal
    """

    def __init__(self):
        self._config = DaemonConfig.load()
        self._state = DaemonState()
        self._running = False
        self._api_client: Optional[MidscaleAPIClient] = None
        self._wg_runtime: Optional[WireGuardRuntime] = None
        self._reconciler: Optional[Reconciler] = None
        self._heartbeat: Optional[HeartbeatSender] = None
        self._endpoint_monitor: Optional[EndpointMonitor] = None
        self._route_advertiser: Optional[RouteAdvertiser] = None
        self._state_store: Optional[StateStore] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._ws_client: Optional[WebSocketClient] = None
        self._daemon_ws: Optional[DaemonWebSocketClient] = None

    async def run(self) -> None:
        setup_logging(debug=self._config.debug)
        logger.info(
            "midscaled starting",
            server_url=self._config.server_url,
            device_name=self._config.device_name,
            interface=self._config.interface_name,
        )

        self._shutdown_event = asyncio.Event()
        self._state_store = StateStore(self._config.state_dir)
        self._state_store.ensure_dirs()
        self._state_store.load()

        self._api_client = MidscaleAPIClient(self._config)
        self._wg_runtime = WireGuardRuntime(
            wg_binary=self._config.wg_binary
        )

        stored_id = self._state_store.get_device_id()
        device_token = self._state_store.get_device_token()

        if stored_id and device_token:
            self._state.device_id = stored_id
            self._state.registered = True
            self._state.enrolled = True
            self._api_client.set_device_auth(stored_id, device_token)
            logger.info("restored device identity", device_id=stored_id)

        if not self._state.registered:
            if self._state_store.has_enrollment():
                stored_id = self._state_store.get_device_id()
                device_token = self._state_store.get_device_token()
                if stored_id and device_token:
                    self._state.device_id = stored_id
                    self._state.registered = True
                    self._state.enrolled = True
                    self._api_client.set_device_auth(stored_id, device_token)
                    logger.info(
                        "restored enrollment",
                        device_id=stored_id,
                    )
                else:
                    logger.error("incomplete enrollment state")
                    await self._api_client.close()
                    sys.exit(1)
            elif self._config.preauth_key:
                await self._legacy_register()
            else:
                logger.error(
                    "no preauth key configured — set MIDSCALE_PREAUTH_KEY"
                )
                await self._api_client.close()
                sys.exit(1)

        if not self._state.registered:
            logger.error(
                "registration failed, shutting down"
            )
            await self._api_client.close()
            sys.exit(1)

        self._reconciler = Reconciler(
            config=self._config,
            api_client=self._api_client,
            wg_runtime=self._wg_runtime,
            state_store=self._state_store,
        )
        await self._reconciler.start(self._state)

        self._heartbeat = HeartbeatSender(
            config=self._config,
            api_client=self._api_client,
        )
        await self._heartbeat.start(self._state)

        self._endpoint_monitor = EndpointMonitor(
            config=self._config,
            api_client=self._api_client,
        )
        await self._endpoint_monitor.start(self._state)

        if self._config.advertised_routes:
            self._route_advertiser = RouteAdvertiser(
                config=self._config,
                api_client=self._api_client,
            )
            await self._route_advertiser.start(self._state)
            await RouteAdvertiser.ensure_ip_forwarding()

        if self._config.ws_enabled and self._state.enrolled and device_token:
            self._daemon_ws = DaemonWebSocketClient(
                server_url=self._config.server_url,
                device_token=device_token,
                device_id=stored_id or "",
                on_config_changed=self._on_ws_config_changed,
            )
            await self._daemon_ws.start()
            self._ws_client = WebSocketClient(
                server_url=self._config.server_url,
                token=device_token,
                device_id=stored_id or "",
                message_callback=self._on_ws_message,
            )
            connected = await self._ws_client.connect()
            if connected:
                asyncio.create_task(self._ws_client.listen())
                logger.info("websocket live push enabled")
            else:
                logger.info("websocket unavailable, using polling fallback")

        self._running = True
        logger.info("midscaled running")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig, lambda: asyncio.ensure_future(self._shutdown())
            )

        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass

        await self._cleanup()

    async def _legacy_register(self) -> None:
        result = await self._api_client.register(
            preauth_key=self._config.preauth_key,
            device_name=self._config.device_name,
        )
        if result.success and result.device_id:
            self._state.device_id = result.device_id
            self._state.registered = True
            self._state_store.save_identity(result.device_id)
            logger.info(
                "registration complete",
                device_id=result.device_id,
            )
        else:
            logger.error(
                "registration failed",
                error=result.error,
            )

    async def _shutdown(self) -> None:
        logger.info("shutdown signal received")
        self._shutdown_event.set()

    def _on_ws_config_changed(self, data: dict) -> None:
        if self._reconciler:
            logger.info(
                "config change event received, triggering reconcile",
                reason=data.get("reason", "unknown"),
            )
            self._reconciler.trigger()

    def _on_ws_message(self, data: dict) -> None:
        msg_type = data.get("type", "")
        if msg_type == "config.changed":
            self._on_ws_config_changed(data)

    async def _cleanup(self) -> None:
        logger.info("shutting down midscaled")
        if self._ws_client:
            await self._ws_client.close()
        if self._daemon_ws:
            await self._daemon_ws.stop()
        if self._reconciler:
            await self._reconciler.stop()
        if self._heartbeat:
            await self._heartbeat.stop()
        if self._endpoint_monitor:
            await self._endpoint_monitor.stop()
        if self._route_advertiser:
            await self._route_advertiser.stop()
        if self._api_client:
            await self._api_client.close()
        self._running = False
        logger.info("midscaled stopped")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="midscaled",
        description="Midscale client daemon — WireGuard tunnel manager",
    )
    sub = parser.add_subparsers(dest="command")

    enroll_p = sub.add_parser("enroll", help="Enroll device with the Midscale server")
    enroll_p.add_argument(
        "--server", required=True,
        help="Midscale server URL (e.g. https://midscale.example.com)",
    )
    enroll_p.add_argument(
        "--preauth-key", required=True,
        help="Pre-authentication key for enrollment",
    )
    enroll_p.add_argument(
        "--name", required=True,
        help="Device name",
    )
    enroll_p.add_argument(
        "--state-dir",
        default="/var/lib/midscaled",
        help="State directory (default: /var/lib/midscaled)",
    )
    enroll_p.add_argument(
        "--insecure", action="store_true",
        help="Disable TLS verification",
    )
    enroll_p.add_argument(
        "--apply", action="store_true",
        help="Apply config immediately after enrollment",
    )
    enroll_p.add_argument(
        "--debug", action="store_true",
        help="Enable debug logging",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "enroll":
        sys.exit(asyncio.run(cmd_enroll(args)))
    else:
        daemon = MidscaledDaemon()
        asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
