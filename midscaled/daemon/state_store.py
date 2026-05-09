import json
import os
import stat
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


def _secure_write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


class StateStore:
    """Persistent local state cache for the daemon.

    Stores device identity, enrollment credentials, and last known
    configuration in JSON files under the state directory.
    Enables offline resilience — daemon can reconnect without
    re-registration after restart.
    """

    def __init__(self, state_dir: str):
        self._state_dir = state_dir
        self._identity_file = os.path.join(state_dir, "identity.json")
        self._enrollment_file = os.path.join(state_dir, "enrollment.json")
        self._cache_file = os.path.join(state_dir, "cache.json")
        self._identity: dict[str, Any] = {}
        self._enrollment: dict[str, Any] = {}
        self._cache: dict[str, Any] = {}

    def ensure_dirs(self) -> None:
        os.makedirs(self._state_dir, exist_ok=True)
        os.makedirs(os.path.join(self._state_dir, "keys"), exist_ok=True)

    def load(self) -> None:
        self._identity = self._read_json(self._identity_file)
        self._enrollment = self._read_json(self._enrollment_file)
        self._cache = self._read_json(self._cache_file)
        logger.debug(
            "state loaded",
            has_identity="device_id" in self._identity,
            has_enrollment="device_token" in self._enrollment,
        )

    def save_identity(self, device_id: str) -> None:
        self._identity["device_id"] = device_id
        self._write_json(self._identity_file, self._identity)
        logger.info("identity saved", device_id=device_id)

    def get_device_id(self) -> Optional[str]:
        return self._identity.get("device_id")

    def save_enrollment(
        self,
        device_id: str,
        device_token: str,
        private_key: str,
        network_id: Optional[str] = None,
    ) -> None:
        self._enrollment["device_id"] = device_id
        self._enrollment["device_token"] = device_token
        self._enrollment["network_id"] = network_id or ""
        self._secure_write(self._enrollment_file, self._enrollment)
        key_path = os.path.join(self._state_dir, "keys", "private.key")
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        tmp_key = key_path + ".tmp"
        with open(tmp_key, "w") as f:
            f.write(private_key + "\n")
        os.chmod(tmp_key, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_key, key_path)
        logger.info(
            "enrollment saved",
            device_id=device_id,
            key_path=key_path,
        )

    def get_device_token(self) -> Optional[str]:
        return self._enrollment.get("device_token")

    def get_network_id(self) -> Optional[str]:
        net = self._enrollment.get("network_id")
        return net if net else None

    def get_private_key_path(self) -> str:
        return os.path.join(self._state_dir, "keys", "private.key")

    def has_enrollment(self) -> bool:
        return "device_token" in self._enrollment and os.path.exists(
            self.get_private_key_path()
        )

    def update_cache(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._write_json(self._cache_file, self._cache)

    def get_cache(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def clear(self) -> None:
        self._identity = {}
        self._enrollment = {}
        self._cache = {}
        for f in [self._identity_file, self._enrollment_file, self._cache_file]:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass
        key_path = self.get_private_key_path()
        try:
            if os.path.exists(key_path):
                os.remove(key_path)
        except OSError:
            pass
        logger.info("state cleared")

    def _read_json(self, path: str) -> dict:
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_json(self, path: str, data: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _secure_write(self, path: str, data: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, path)
