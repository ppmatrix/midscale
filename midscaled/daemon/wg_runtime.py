import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

import structlog

from daemon.models import DesiredConfig, DesiredPeer, InterfaceState, PeerState

logger = structlog.get_logger(__name__)

_PEER_KEY_PATTERN = re.compile(r"^[A-Za-z0-9+/]{43}=$")


def _validate_key(key: str) -> bool:
    return bool(key and _PEER_KEY_PATTERN.match(key))


def _parse_dump_timestamp(raw: str) -> Optional[datetime]:
    raw = raw.strip()
    if not raw or raw == "0":
        return None
    try:
        ts = int(raw)
        if ts == 0:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, OSError):
        return None


class WireGuardRuntime:
    """Manages the local WireGuard interface for the daemon.

    Mirrors the backend's WgCliAdapter pattern but is focused on
    the client-side lifecycle: bringing up the interface, applying
    config, monitoring state.
    """

    def __init__(self, wg_binary: str = "wg"):
        self._wg_binary = wg_binary

    async def generate_keypair(self) -> tuple[Optional[str], Optional[str]]:
        try:
            private_proc = await asyncio.create_subprocess_exec(
                self._wg_binary, "genkey",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            priv_stdout, _ = await private_proc.communicate()
            if private_proc.returncode != 0:
                logger.error("wg genkey failed")
                return None, None
            private_key = priv_stdout.decode().strip()

            public_proc = await asyncio.create_subprocess_exec(
                self._wg_binary, "pubkey",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            pub_stdout, _ = await public_proc.communicate(
                input=private_key.encode()
            )
            if public_proc.returncode != 0:
                logger.error("wg pubkey failed")
                return None, None
            public_key = pub_stdout.decode().strip()

            return private_key, public_key
        except Exception as e:
            logger.error("key generation failed", error=str(e))
            return None, None

    async def _run(
        self, *args: str, input_data: Optional[str] = None
    ) -> tuple[str, str]:
        proc = await asyncio.create_subprocess_exec(
            self._wg_binary,
            *args,
            stdin=asyncio.subprocess.PIPE if input_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(
            input=input_data.encode() if input_data else None
        )
        return stdout.decode().strip(), stderr.decode().strip()

    async def interface_exists(self, interface: str) -> bool:
        try:
            await self._run("show", interface)
            return True
        except Exception:
            return False

    async def get_state(self, interface: str) -> Optional[InterfaceState]:
        try:
            raw, _ = await self._run("show", interface, "dump")
            if not raw:
                return None
            return self._parse_dump(raw, interface)
        except Exception:
            return None

    async def apply_config(self, interface: str, config: DesiredConfig) -> bool:
        try:
            await self._run(
                "set",
                interface,
                "private-key",
                "/dev/stdin",
                "listen-port",
                str(config.listen_port or 51820),
                input_data=config.private_key,
            )
            current = await self.get_state(interface)
            current_keys = {p.public_key for p in current.peers} if current else set()
            desired_keys = {p.public_key for p in config.peers}

            for peer in config.peers:
                args = [
                    "set",
                    interface,
                    "peer",
                    peer.public_key,
                    "allowed-ips",
                    ",".join(peer.allowed_ips),
                ]
                if peer.endpoint:
                    port = peer.endpoint_port or 51820
                    args.extend(["endpoint", f"{peer.endpoint}:{port}"])
                if peer.persistent_keepalive is not None:
                    args.extend(
                        ["persistent-keepalive", str(peer.persistent_keepalive)]
                    )
                await self._run(*args)

            for key in current_keys:
                if key not in desired_keys:
                    await self._run("set", interface, "peer", key, "remove")
                    logger.info(
                        "removed stale peer",
                        public_key=key[:16],
                        interface=interface,
                    )

            logger.info(
                "config applied",
                interface=interface,
                peers=len(config.peers),
            )
            return True

        except Exception as e:
            logger.error(
                "failed to apply config",
                interface=interface,
                error=str(e),
            )
            return False

    async def bring_up_interface(
        self, interface: str, address: str, subnet: str
    ) -> bool:
        try:
            exists = await self.interface_exists(interface)
            if not exists:
                private_key = None
                proc = await asyncio.create_subprocess_exec(
                    self._wg_binary, "genkey",
                    stdout=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    private_key = stdout.decode().strip()

                import subprocess as sp
                sp.run(
                    ["ip", "link", "add", interface, "type", "wireguard"],
                    capture_output=True, timeout=10,
                )
                sp.run(
                    ["ip", "addr", "add", f"{address}/{subnet.split('/')[1] if '/' in subnet else '24'}", "dev", interface],
                    capture_output=True, timeout=10,
                )
                sp.run(
                    ["ip", "link", "set", interface, "up"],
                    capture_output=True, timeout=10,
                )

                if private_key:
                    proc2 = await asyncio.create_subprocess_exec(
                        self._wg_binary, "set", interface, "private-key",
                        "/dev/stdin",
                        stdin=asyncio.subprocess.PIPE,
                    )
                    await proc2.communicate(input=private_key.encode())

                logger.info("interface created", interface=interface)
            else:
                import subprocess as sp
                sp.run(
                    ["ip", "addr", "add", f"{address}/{subnet.split('/')[1] if '/' in subnet else '24'}", "dev", interface],
                    capture_output=True, timeout=10,
                )
                sp.run(
                    ["ip", "link", "set", interface, "up"],
                    capture_output=True, timeout=10,
                )

            return True
        except Exception as e:
            logger.error(
                "failed to bring up interface",
                interface=interface,
                error=str(e),
            )
            return False

    async def bring_down_interface(self, interface: str) -> bool:
        try:
            import subprocess as sp
            sp.run(
                ["ip", "link", "set", interface, "down"],
                capture_output=True, timeout=10,
            )
            sp.run(
                ["ip", "link", "delete", interface],
                capture_output=True, timeout=10,
            )
            logger.info("interface removed", interface=interface)
            return True
        except Exception as e:
            logger.error(
                "failed to remove interface",
                interface=interface,
                error=str(e),
            )
            return False

    def _parse_dump(self, raw: str, interface: str) -> InterfaceState:
        lines = raw.split("\n")
        if not lines:
            return InterfaceState(name=interface)
        first = lines[0].split("\t")
        priv_key = first[0] if len(first) > 0 and first[0] != "(none)" else None
        listen_port = int(first[1]) if len(first) > 1 else 51820
        pub_key = first[2] if len(first) > 2 and first[2] != "(none)" else None

        peers: list[PeerState] = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            peers.append(
                PeerState(
                    public_key=parts[0],
                    allowed_ips=parts[1].split(",") if parts[1] else [],
                    endpoint=parts[2]
                    if parts[2] and parts[2] != "(none)"
                    else None,
                    latest_handshake=_parse_dump_timestamp(parts[3]),
                    transfer_rx=int(parts[4]) if parts[4] else 0,
                    transfer_tx=int(parts[5])
                    if len(parts) > 5 and parts[5]
                    else 0,
                )
            )

        return InterfaceState(
            name=interface,
            public_key=pub_key,
            listen_port=listen_port,
            peers=peers,
        )
