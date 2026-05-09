import os
from abc import ABC, abstractmethod
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class DNSRecord:
    """Represents a single DNS resource record."""

    def __init__(
        self,
        name: str,
        record_type: str,
        value: str,
        ttl: int = 300,
    ):
        self.name = name
        self.record_type = record_type
        self.value = value
        self.ttl = ttl


class ZoneData:
    """Represents a complete DNS zone."""

    def __init__(
        self,
        origin: str,
        records: list[DNSRecord],
        serial: int,
        ttl: int = 300,
        admin_email: str = "admin.wg.midscale",
    ):
        self.origin = origin
        self.records = records
        self.serial = serial
        self.ttl = ttl
        self.admin_email = admin_email


class DNSProvider(ABC):
    """Abstract interface for DNS record management.

    Implementations handle the actual storage and serving of DNS records.
    """

    @abstractmethod
    async def ensure_zone(self, zone: ZoneData) -> None:
        """Create or update a DNS zone."""

    @abstractmethod
    async def remove_zone(self, origin: str) -> None:
        """Remove a DNS zone."""

    @abstractmethod
    async def reload(self) -> None:
        """Signal the DNS server to reload its configuration."""


class CoreDNSFileProvider(DNSProvider):
    """Writes standard DNS zone files for CoreDNS to serve.

    Zone files are written to a configurable directory. CoreDNS uses the
    `file` plugin to load them. After writing, CoreDNS is reloaded via
    a configurable command (default: SIGUSR1 to the coredns process).
    """

    def __init__(
        self,
        zones_path: str = "/etc/coredns/zones",
        reload_cmd: Optional[str] = None,
    ):
        self._zones_path = zones_path
        self._reload_cmd = reload_cmd

    async def ensure_zone(self, zone: ZoneData) -> None:
        os.makedirs(self._zones_path, exist_ok=True)
        filepath = self._zone_filepath(zone.origin)

        content = self._format_zone(zone)
        existing = ""
        try:
            with open(filepath) as f:
                existing = f.read()
        except FileNotFoundError:
            pass

        if content != existing:
            with open(filepath, "w") as f:
                f.write(content)
            logger.info(
                "zone file updated",
                zone=zone.origin,
                path=filepath,
                records=len(zone.records),
            )

    async def remove_zone(self, origin: str) -> None:
        filepath = self._zone_filepath(origin)
        try:
            os.remove(filepath)
            logger.info("zone file removed", zone=origin, path=filepath)
        except FileNotFoundError:
            pass

    async def reload(self) -> None:
        if not self._reload_cmd:
            logger.debug("no reload command configured, skipping")
            return
        try:
            import subprocess
            subprocess.run(
                self._reload_cmd, shell=True, check=True, timeout=10
            )
            logger.info("dns server reloaded", cmd=self._reload_cmd)
        except Exception as e:
            logger.error("failed to reload dns server", error=str(e))

    def _zone_filepath(self, origin: str) -> str:
        filename = origin.rstrip(".").replace(".", "-") + ".zone"
        return os.path.join(self._zones_path, filename)

    def _format_zone(self, zone: ZoneData) -> str:
        lines: list[str] = []
        lines.append(f"$ORIGIN {zone.origin}.")
        lines.append(f"$TTL {zone.ttl}")
        lines.append("")

        admin = zone.admin_email.replace("@", ".")
        lines.append(
            f"@  IN SOA  ns1.{zone.origin}. {admin}. ("
        )
        lines.append(f"    {zone.serial} ; serial")
        lines.append(f"    3600       ; refresh")
        lines.append(f"    900        ; retry")
        lines.append(f"    86400      ; expire")
        lines.append(f"    {zone.ttl}  ; minimum")
        lines.append(")")
        lines.append("")

        lines.append(f"@  IN NS  ns1.{zone.origin}.")
        lines.append("")

        seen_names: set[str] = set()
        for record in zone.records:
            key = f"{record.name}:{record.record_type}:{record.value}"
            if key in seen_names:
                continue
            seen_names.add(key)
            name = record.name if record.name != "@" else ""
            lines.append(
                f"{name:<30} {record.ttl} {record.record_type:>5} {record.value}"
            )

        lines.append("")
        return "\n".join(lines)


class NoopDNSProvider(DNSProvider):
    """No-op provider for when DNS management is disabled."""

    async def ensure_zone(self, zone: ZoneData) -> None:
        pass

    async def remove_zone(self, origin: str) -> None:
        pass

    async def reload(self) -> None:
        pass
