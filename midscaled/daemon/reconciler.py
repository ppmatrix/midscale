import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from daemon.peer_prober import PeerProber
    from daemon.relay_client import DaemonRelayClient

import structlog

from daemon.api_client import MidscaleAPIClient
from daemon.config import DaemonConfig
from daemon.models import DaemonState, DesiredConfig, DesiredPeer
from daemon.state_store import StateStore
from daemon.wg_runtime import WireGuardRuntime

logger = structlog.get_logger(__name__)

_INI_PEER_BLOCK = re.compile(r"\[Peer\].*?(?=\[|$)", re.DOTALL)
_INI_KEY_VALUE = re.compile(r"^(\w+)\s*=\s*(.*)$", re.MULTILINE)


def _parse_config_ini(ini: str) -> Optional[DesiredConfig]:
    """Parse a WireGuard INI config string into a DesiredConfig."""
    interface_match = re.search(
        r"\[Interface\](.*?)(?=\[Peer\]|$)", ini, re.DOTALL
    )
    if not interface_match:
        return None

    interface_section = interface_match.group(1)
    kv = dict(_INI_KEY_VALUE.findall(interface_section))

    private_key = kv.get("PrivateKey", "")
    address_raw = kv.get("Address", "")
    dns_raw = kv.get("DNS", "")
    listen_port_raw = kv.get("ListenPort", "")
    mtu_raw = kv.get("MTU", "")

    address = address_raw.split("/")[0] if address_raw else ""
    subnet = ""
    if "/" in address_raw:
        prefix = address_raw.split("/")[1]
        subnet = f"0.0.0.0/{prefix}"

    peers: list[DesiredPeer] = []
    for block in _INI_PEER_BLOCK.findall(ini):
        pkv = dict(_INI_KEY_VALUE.findall(block))
        public_key = pkv.get("PublicKey", "")
        if not public_key:
            continue
        allowed_ips_raw = pkv.get("AllowedIPs", "")
        endpoint_raw = pkv.get("Endpoint", "")
        keepalive_raw = pkv.get("PersistentKeepalive", "")

        endpoint = None
        endpoint_port = None
        if endpoint_raw:
            if ":" in endpoint_raw:
                endpoint, port_str = endpoint_raw.rsplit(":", 1)
                try:
                    endpoint_port = int(port_str)
                except ValueError:
                    endpoint_port = 51820
            else:
                endpoint = endpoint_raw

        peers.append(
            DesiredPeer(
                public_key=public_key,
                allowed_ips=[s.strip() for s in allowed_ips_raw.split(",") if s.strip()],
                endpoint=endpoint,
                endpoint_port=endpoint_port,
                persistent_keepalive=int(keepalive_raw)
                if keepalive_raw
                else None,
            )
        )

    return DesiredConfig(
        private_key=private_key,
        address=address,
        subnet=subnet,
        listen_port=int(listen_port_raw) if listen_port_raw else None,
        dns_servers=[s.strip() for s in dns_raw.split(",") if s.strip()]
        if dns_raw
        else None,
        peers=peers,
        mtu=int(mtu_raw) if mtu_raw else None,
    )


def _parse_config_v2(
    config_v2: dict[str, Any], private_key: str
) -> Optional[DesiredConfig]:
    """Parse a config-v2 JSON dict into a DesiredConfig.

    Injects the local private key — the server never sees it.
    """
    try:
        interface = config_v2.get("interface", {})
        address_raw = interface.get("address", "")
        address = address_raw.split("/")[0] if address_raw else ""
        subnet = ""
        if "/" in address_raw:
            prefix = address_raw.split("/")[1]
            subnet = f"0.0.0.0/{prefix}"

        peers: list[DesiredPeer] = []
        for p in config_v2.get("peers", []):
            relay_required = p.get("relay_required", False)
            relay_candidates = p.get("relay_candidates") or []
            peer = DesiredPeer(
                public_key=p.get("public_key", ""),
                allowed_ips=p.get("allowed_ips", []),
                endpoint=p.get("endpoint"),
                endpoint_port=p.get("endpoint_port"),
                persistent_keepalive=p.get("persistent_keepalive"),
                relay_required=relay_required,
                relay_candidates=relay_candidates,
            )
            peers.append(peer)

        return DesiredConfig(
            private_key=private_key,
            address=address,
            subnet=subnet,
            listen_port=None,
            dns_servers=interface.get("dns"),
            peers=peers,
            mtu=interface.get("mtu"),
        )
    except Exception as e:
        logger.error("failed to parse config-v2", error=str(e))
        return None


class Reconciler:
    """Core reconciliation loop for the daemon.

    Periodically:
    1. Pulls latest config from the Midscale server
    2. Parses the INI config into desired state
    3. Applies desired state to the local WireGuard interface
    4. Updates local state cache
    """

    def __init__(
        self,
        config: DaemonConfig,
        api_client: MidscaleAPIClient,
        wg_runtime: WireGuardRuntime,
        state_store: StateStore,
        peer_prober: Optional["PeerProber"] = None,
        relay_client: Optional["DaemonRelayClient"] = None,
    ):
        self._config = config
        self._api = api_client
        self._wg = wg_runtime
        self._state = state_store
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_config: Optional[str] = None
        self._push_event = asyncio.Event()
        self._peer_prober = peer_prober
        self._relay_client = relay_client

    def trigger(self) -> None:
        """Signal the reconciler to run immediately (push event received)."""
        self._push_event.set()

    async def start(self, daemon_state: DaemonState) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._run_loop(daemon_state)
        )
        logger.info(
            "reconciler started",
            interval_seconds=self._config.polling_interval_seconds,
        )

    async def stop(self) -> None:
        self._running = False
        self._push_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("reconciler stopped")

    async def reconcile_once(self, daemon_state: DaemonState) -> None:
        interface = self._config.interface_name

        if daemon_state.enrolled:
            await self._reconcile_v2(interface, daemon_state)
        else:
            await self._reconcile_v1(interface, daemon_state)

    async def _reconcile_v1(
        self, interface: str, daemon_state: DaemonState
    ) -> None:
        result = await self._api.pull_config()
        if not result.success:
            logger.warning("config pull failed", error=result.error)
            cached = self._state.get_cache("last_config")
            if cached and self._last_config is None:
                logger.info("using cached config")
                self._last_config = cached
                config = _parse_config_ini(cached)
                if config:
                    await self._apply_config(interface, config, daemon_state)
            return

        ini = result.config_ini
        if not ini:
            logger.warning("empty config received")
            return

        if ini == self._last_config:
            logger.debug("config unchanged, skipping apply")
            daemon_state.last_config_fetch = datetime.now(timezone.utc)
            return

        self._state.update_cache("last_config", ini)
        self._last_config = ini

        config = _parse_config_ini(ini)
        if not config:
            logger.error("failed to parse config INI")
            return

        logger.info(
            "config updated",
            peers=len(config.peers),
            address=config.address,
        )

        await self._apply_config(interface, config, daemon_state)

    async def _reconcile_v2(
        self, interface: str, daemon_state: DaemonState
    ) -> None:
        key_path = self._state.get_private_key_path()
        try:
            with open(key_path) as f:
                private_key = f.read().strip()
        except (FileNotFoundError, OSError):
            logger.error("private key not found", key_path=key_path)
            return
        if not private_key:
            logger.error("empty private key")
            return

        result = await self._api.pull_config_v2()
        if not result.success:
            logger.warning("config-v2 pull failed", error=result.error)
            return

        if result.hash:
            last_hash = self._state.get_cache("last_config_hash")
            if result.hash == last_hash:
                logger.debug("config-v2 hash unchanged, skipping apply")
                daemon_state.last_config_fetch = datetime.now(timezone.utc)
                return

        config_v2 = {
            "interface": result.interface,
            "peers": result.peers,
            "routes": result.routes,
            "exit_node": result.exit_node,
        }
        cache_key = json.dumps(config_v2, sort_keys=True)
        last = self._state.get_cache("last_config_v2")
        if not result.hash and cache_key == last:
            logger.debug("config-v2 unchanged, skipping apply")
            daemon_state.last_config_fetch = datetime.now(timezone.utc)
            return

        config = _parse_config_v2(config_v2, private_key)
        if not config:
            logger.error("failed to parse config-v2")
            return

        logger.info(
            "config-v2 updated",
            peers=len(config.peers),
            address=config.address,
            hash=result.hash,
            revision=result.revision,
        )

        await self._apply_config(interface, config, daemon_state)

        if self._relay_client and self._relay_client.is_connected:
            for peer in config.peers:
                if peer.relay_required and peer.relay_candidates:
                    asyncio.create_task(
                        self._activate_relay_for_peer(peer)
                    )
        self._state.update_cache("last_config_v2", cache_key)
        if result.hash:
            self._state.update_cache("last_config_hash", result.hash)
            daemon_state.last_config_hash = result.hash
            daemon_state.last_config_revision = result.revision

        if self._peer_prober and result.peers:
            from daemon.peer_prober import ProbeTarget
            targets = []
            for peer in result.peers:
                peer_device_id = peer.get("public_key", "")
                endpoint = peer.get("endpoint")
                endpoint_port = peer.get("endpoint_port", 51820)
                if endpoint:
                    targets.append(ProbeTarget(
                        peer_device_id=peer_device_id,
                        public_key=peer.get("public_key", ""),
                        endpoint=endpoint,
                        port=endpoint_port,
                    ))
                for cand in peer.get("endpoint_candidates", []):
                    targets.append(ProbeTarget(
                        peer_device_id=peer_device_id,
                        public_key=peer.get("public_key", ""),
                        endpoint=cand.get("endpoint", endpoint or ""),
                        port=cand.get("port", endpoint_port),
                    ))
            self._peer_prober.update_targets(targets)

    async def _apply_config(
        self, interface: str, config: DesiredConfig, daemon_state: DaemonState
    ) -> None:
        up = await self._wg.bring_up_interface(
            interface, config.address, config.subnet
        )
        if not up:
            logger.error("failed to ensure interface is up")
            return

        ok = await self._wg.apply_config(interface, config)
        if ok:
            daemon_state.reconfigure_count += 1
            logger.info(
                "reconciliation applied",
                interface=interface,
                total_reconfigs=daemon_state.reconfigure_count,
            )
        else:
            daemon_state.error_count += 1
            logger.error(
                "reconciliation failed",
                interface=interface,
            )

    async def _run_loop(self, daemon_state: DaemonState) -> None:
        await asyncio.sleep(2)
        while self._running:
            try:
                await self.reconcile_once(daemon_state)
                daemon_state.last_config_fetch = datetime.now(timezone.utc)
            except Exception as e:
                daemon_state.error_count += 1
                logger.error("reconciliation error", error=str(e))

            try:
                await asyncio.wait_for(
                    self._push_event.wait(),
                    timeout=self._config.polling_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
            self._push_event.clear()

    async def _activate_relay_for_peer(self, peer: DesiredPeer) -> None:
        """Activate a relay session for a peer that requires relay fallback."""
        if not self._relay_client or not self._api.device_id:
            return
        try:
            candidates = peer.relay_candidates or []
            if not candidates:
                return
            target_pk = peer.public_key
            target_device_id = await self._resolve_peer_device_id(target_pk)
            if not target_device_id:
                logger.warning(
                    "cannot activate relay: unknown peer",
                    public_key=target_pk,
                )
                return
            result = await self._api.request_relay_session(
                target_device_id=target_device_id,
            )
            if result.success and result.session_id and result.relay_token:
                await self._relay_client.connect_session(
                    session_id=result.session_id,
                    token=result.relay_token,
                )
        except Exception as e:
            logger.error("relay activation error", error=str(e))

    async def _resolve_peer_device_id(self, public_key: str) -> Optional[str]:
        """Resolve a peer device_id from the last pulled config."""
        if not self._last_config:
            return None
        try:
            if self._state.get_cache("last_config_v2"):
                cached = self._state.get_cache("last_config_v2")
                peers = json.loads(cached).get("peers", [])
                for p in peers:
                    if p.get("public_key") == public_key:
                        return p.get("device_id")
        except Exception:
            pass
        return None
