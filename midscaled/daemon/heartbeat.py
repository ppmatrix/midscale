import asyncio
from typing import Optional

import structlog

from daemon.api_client import MidscaleAPIClient
from daemon.config import DaemonConfig
from daemon.models import DaemonState

logger = structlog.get_logger(__name__)


class HeartbeatSender:
    """Periodically sends heartbeats to the Midscale control plane.

    Heartbeats keep the device marked as online in the server's
    database and allow the server to detect device connectivity.
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
            "heartbeat sender started",
            interval_seconds=self._config.heartbeat_interval_seconds,
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
        logger.info("heartbeat sender stopped")

    async def _run_loop(self, state: DaemonState) -> None:
        while self._running:
            try:
                result = await self._api.send_heartbeat()
                if result.success:
                    state.last_heartbeat = __import__(
                        "datetime"
                    ).datetime.now(__import__("datetime").timezone.utc)
                    logger.debug("heartbeat sent")
                else:
                    logger.warning(
                        "heartbeat failed", error=result.error
                    )
            except Exception as e:
                logger.error("heartbeat error", error=str(e))

            await asyncio.sleep(
                self._config.heartbeat_interval_seconds
            )
