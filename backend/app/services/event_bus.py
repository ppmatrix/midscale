import asyncio
import json
from typing import Any, Callable, Optional

import structlog

from app.services.event_types import Event
from app.services.metrics import EVENTS_PUBLISHED, EVENT_BUS_CONNECTED

logger = structlog.get_logger(__name__)


class EventBus:
    """Publish/subscribe event bus.

    Uses Redis pub/sub when available, falls back to in-memory broadcast
    for development environments without Redis.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url
        self._redis = None
        self._pubsub = None
        self._listener_task: Optional[asyncio.Task] = None
        self._in_memory_subscribers: list[Callable[[Event], None]] = []
        self._running = False

    async def _connect_redis(self):
        try:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            await self._redis.ping()
            self._pubsub = self._redis.pubsub()
            logger.info("connected to redis", url=self._redis_url)
            return True
        except Exception as e:
            logger.warning(
                "redis unavailable, using in-memory event bus",
                error=str(e),
            )
            self._redis = None
            self._pubsub = None
            return False

    async def start(self):
        if self._running:
            return
        self._running = True
        if self._redis_url:
            await self._connect_redis()
        EVENT_BUS_CONNECTED.set(1 if self._redis else 0)
        logger.info("event bus started", redis_connected=self._redis is not None)

    async def stop(self):
        self._running = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None
        if self._pubsub:
            await self._pubsub.unsubscribe()
        if self._redis:
            await self._redis.close()
        logger.info("event bus stopped")

    async def publish(self, event: Event) -> None:
        payload = json.dumps(event.to_dict())
        EVENTS_PUBLISHED.labels(event_type=event.event_type).inc()
        if self._redis:
            try:
                await self._redis.publish(event.channel(), payload)
                logger.debug("event published", type=event.event_type)
            except Exception as e:
                logger.error("failed to publish event to redis", error=str(e))
        for cb in self._in_memory_subscribers:
            try:
                cb(event)
            except Exception as e:
                logger.error("in-memory subscriber error", error=str(e))

    def subscribe_in_memory(self, callback: Callable[[Event], None]) -> None:
        self._in_memory_subscribers.append(callback)

    def unsubscribe_in_memory(self, callback: Callable[[Event], None]) -> None:
        self._in_memory_subscribers.remove(callback)

    async def _call_handler(self, handler: Callable, event: Event) -> None:
        import asyncio
        result = handler(event)
        if asyncio.iscoroutine(result):
            await result

    async def listen(self, handler: Callable[[Event], None]) -> None:
        if self._pubsub:
            await self._pubsub.psubscribe("midscale:event:*")
            logger.info("listening for events on redis pub/sub")
            async for message in self._pubsub.listen():
                if message["type"] == "pmessage":
                    try:
                        data = json.loads(message["data"])
                        event = Event(
                            event_type=data["type"],
                            data=data.get("data", {}),
                            event_id=data.get("id", ""),
                            created_at=data.get("created_at", ""),
                        )
                        await self._call_handler(handler, event)
                    except Exception as e:
                        logger.error("failed to process event", error=str(e))
                elif message["type"] == "unsubscribe":
                    break
        else:
            logger.info("in-memory mode — events delivered via local subscribers")
            reconnect_interval = 30
            while self._running:
                if self._redis_url and not self._redis:
                    logger.info("attempting redis reconnection")
                    connected = await self._connect_redis()
                    if connected:
                        EVENT_BUS_CONNECTED.set(1)
                        self._pubsub = self._redis.pubsub()
                        await self._pubsub.psubscribe("midscale:event:*")
                        logger.info("redis reconnected, resuming pub/sub listener")
                        async for message in self._pubsub.listen():
                            if message["type"] == "pmessage":
                                try:
                                    data = json.loads(message["data"])
                                    event = Event(
                                        event_type=data["type"],
                                        data=data.get("data", {}),
                                        event_id=data.get("id", ""),
                                        created_at=data.get("created_at", ""),
                                    )
                                    await self._call_handler(handler, event)
                                except Exception as e:
                                    logger.error(
                                        "failed to process event", error=str(e)
                                    )
                            elif message["type"] == "unsubscribe":
                                break
                        break
                    EVENT_BUS_CONNECTED.set(0)
                await asyncio.sleep(reconnect_interval)

    async def start_listener(self, handler: Callable[[Event], None]) -> None:
        if self._listener_task:
            return
        self._listener_task = asyncio.create_task(self.listen(handler))
