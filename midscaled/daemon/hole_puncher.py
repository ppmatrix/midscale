"""UDP hole punching engine for direct peer-to-peer connectivity.

Implements lightweight coordinated NAT traversal by sending simultaneous
UDP datagrams to all known endpoint candidates of a target peer. When a
response is received, connectivity is validated and the direct path is
promoted.

This is NOT ICE/STUN/TURN — it is a simplified coordinated punch that
works best with endpoint-aware topologies (mesh/hybrid).
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

_PUNCH_MAGIC = b"MIDSCALE_PUNCH_V1"


@dataclass
class PunchTarget:
    peer_device_id: str
    endpoint: str
    port: int = 51820


@dataclass
class CandidatePair:
    local_endpoint: str
    local_port: int
    remote_endpoint: str
    remote_port: int
    pair_key: str = ""

    def __post_init__(self):
        if not self.pair_key:
            self.pair_key = f"{self.local_endpoint}:{self.local_port}->{self.remote_endpoint}:{self.remote_port}"


@dataclass
class PunchAttempt:
    pair: CandidatePair
    started_at: float
    completed_at: Optional[float] = None
    success: bool = False
    latency_ms: Optional[float] = None
    error: Optional[str] = None


@dataclass
class PunchSession:
    session_id: str
    target_device_id: str
    candidates: list[CandidatePair] = field(default_factory=list)
    attempts: list[PunchAttempt] = field(default_factory=list)
    state: str = "pending"
    start_time: float = 0.0
    result_endpoint: Optional[str] = None
    result_port: Optional[int] = None
    result_latency_ms: Optional[float] = None
    on_success: Optional[callable] = None
    on_failure: Optional[callable] = None
    on_relay_fallback: Optional[callable] = None


class HolePuncher:
    """UDP hole punching engine.

    Coordinates simultaneous UDP sends to all candidate pairs of a target
    peer. Uses retry windows and validates bidirectional connectivity.

    Does NOT implement ICE/STUN/TURN complexity — this is a lightweight
    coordinated punch.
    """

    def __init__(
        self,
        enabled: bool = True,
        timeout: float = 10.0,
        retries: int = 3,
        retry_delay: float = 0.5,
        bind_port: int = 51820,
    ):
        self._enabled = enabled
        self._timeout = timeout
        self._retries = retries
        self._retry_delay = retry_delay
        self._bind_port = bind_port
        self._running = False
        self._active_sessions: dict[str, PunchSession] = {}
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._protocol: Optional["_PunchProtocol"] = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        if not self._enabled:
            logger.info("hole puncher disabled")
            return
        if self._running:
            return
        self._running = True
        loop = asyncio.get_running_loop()
        self._protocol = _PunchProtocol(self)
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: self._protocol,
                local_addr=("0.0.0.0", self._bind_port),
            )
            logger.info("hole puncher started", port=self._bind_port)
        except OSError as e:
            logger.warning("hole puncher port bind failed", error=str(e), port=self._bind_port)

    async def stop(self) -> None:
        self._running = False
        if self._transport:
            self._transport.close()
            self._transport = None
        logger.info("hole puncher stopped")

    async def initiate_punch(
        self,
        session_id: str,
        target_device_id: str,
        candidates: list[dict[str, Any]],
        on_success: Optional[callable] = None,
        on_failure: Optional[callable] = None,
        on_relay_fallback: Optional[callable] = None,
    ) -> PunchSession:
        if not self._enabled:
            logger.warning("hole punching disabled, skipping")
            return PunchSession(
                session_id=session_id,
                target_device_id=target_device_id,
                state="disabled",
            )

        pairs = self._build_candidate_pairs(candidates)
        session = PunchSession(
            session_id=session_id,
            target_device_id=target_device_id,
            candidates=pairs,
            state="punching",
            start_time=time.monotonic(),
            on_success=on_success,
            on_failure=on_failure,
            on_relay_fallback=on_relay_fallback,
        )
        self._active_sessions[session_id] = session

        logger.info(
            "initiating hole punch",
            session_id=session_id,
            target=target_device_id,
            pairs=len(pairs),
        )

        asyncio.create_task(self._execute_punch(session))
        return session

    def _build_candidate_pairs(self, candidates: list[dict[str, Any]]) -> list[CandidatePair]:
        initiator_candidates = [c for c in candidates if c.get("side") == "initiator"]
        target_candidates = [c for c in candidates if c.get("side") == "target"]

        if not initiator_candidates or not target_candidates:
            initiator_candidates = candidates
            target_candidates = candidates

        pairs = []
        for ic in initiator_candidates:
            for tc in target_candidates:
                pairs.append(CandidatePair(
                    local_endpoint=ic.get("endpoint", "127.0.0.1"),
                    local_port=ic.get("port", self._bind_port),
                    remote_endpoint=tc.get("endpoint", ""),
                    remote_port=tc.get("port", self._bind_port),
                ))

        if not pairs:
            pairs.append(CandidatePair(
                local_endpoint="127.0.0.1",
                local_port=self._bind_port,
                remote_endpoint="127.0.0.1",
                remote_port=self._bind_port,
            ))

        random.shuffle(pairs)
        return pairs

    async def _execute_punch(self, session: PunchSession) -> None:
        try:
            for attempt_num in range(self._retries):
                if not self._running:
                    return

                for pair in session.candidates:
                    if not self._running:
                        return

                    attempt = await self._attempt_pair(pair)
                    session.attempts.append(attempt)

                    if attempt.success:
                        session.state = "connected"
                        session.result_endpoint = pair.remote_endpoint
                        session.result_port = pair.remote_port
                        session.result_latency_ms = attempt.latency_ms
                        logger.info(
                            "hole punch succeeded",
                            session_id=session.session_id,
                            pair=pair.pair_key,
                            latency_ms=attempt.latency_ms,
                        )
                        if session.on_success:
                            session.on_success(session)
                        return

                if attempt_num < self._retries - 1:
                    await asyncio.sleep(self._retry_delay)

            session.state = "failed"
            logger.warning(
                "hole punch failed after all retries",
                session_id=session.session_id,
                attempts=len(session.attempts),
            )
            if session.on_failure:
                session.on_failure(session)
            if session.on_relay_fallback:
                session.on_relay_fallback(session)
        except Exception as e:
            session.state = "failed"
            logger.error("hole punch error", error=str(e))
            if session.on_failure:
                session.on_failure(session)
            if session.on_relay_fallback:
                session.on_relay_fallback(session)
        finally:
            self._active_sessions.pop(session.session_id, None)

    async def _attempt_pair(self, pair: CandidatePair) -> PunchAttempt:
        attempt = PunchAttempt(pair=pair, started_at=time.monotonic())
        try:
            remote_addr = (pair.remote_endpoint, pair.remote_port)
            payload = _PUNCH_MAGIC + str(time.time()).encode()[:8]

            if self._transport:
                for _ in range(3):
                    self._transport.sendto(payload, remote_addr)
                    await asyncio.sleep(0.05)

                response_waiter = asyncio.get_running_loop().create_future()
                self._protocol.expect_response(pair.pair_key, response_waiter)

                try:
                    await asyncio.wait_for(response_waiter, timeout=2.0)
                    attempt.success = True
                    attempt.completed_at = time.monotonic()
                    attempt.latency_ms = int((attempt.completed_at - attempt.started_at) * 1000)
                except asyncio.TimeoutError:
                    attempt.success = False
                    attempt.completed_at = time.monotonic()
                    attempt.error = "timeout"
                finally:
                    self._protocol.forget_response(pair.pair_key)
            else:
                attempt.success = False
                attempt.error = "no transport"
        except Exception as e:
            attempt.success = False
            attempt.completed_at = time.monotonic()
            attempt.error = str(e)
        return attempt

    def handle_datagram(self, data: bytes, addr: tuple) -> None:
        if data.startswith(_PUNCH_MAGIC):
            pair_key = f"{addr[0]}:{addr[1]}->..."
            self._protocol.deliver_response(pair_key, data)

    def get_session(self, session_id: str) -> Optional[PunchSession]:
        return self._active_sessions.get(session_id)


class _PunchProtocol(asyncio.DatagramProtocol):
    def __init__(self, puncher: HolePuncher):
        self._puncher = puncher
        self._expected_responses: dict[str, asyncio.Future] = {}
        self._transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if data.startswith(_PUNCH_MAGIC):
            addr_key = f"{addr[0]}:{addr[1]}->..."
            future = self._expected_responses.get(addr_key)
            if future and not future.done():
                future.set_result(data)
        self._puncher.handle_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        logger.warning("hole puncher protocol error", error=str(exc))

    def connection_lost(self, exc: Optional[Exception]) -> None:
        pass

    def expect_response(self, key: str, future: asyncio.Future) -> None:
        self._expected_responses[key] = future

    def forget_response(self, key: str) -> None:
        self._expected_responses.pop(key, None)

    def deliver_response(self, key: str, data: bytes) -> None:
        future = self._expected_responses.get(key)
        if future and not future.done():
            future.set_result(data)
