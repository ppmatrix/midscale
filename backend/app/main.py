import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.config import settings
from app.database import init_db, close_db, get_session_factory
from app.core.logging import setup_logging
from app.api.v1 import auth, networks, devices, acls, dns, ws as ws_router
from app.api.v1 import health as health_router
from app.api.v1 import routes as routes_router
from app.api.v1 import audit as audit_router
from app.api.v1 import nat as nat_router
from app.api.v1 import relay as relay_router

from app.services.event_bus import EventBus
from app.services.event_types import Event, CONFIG_CHANGED
from app.services.metrics import (
    WS_CONNECTIONS,
    WS_MESSAGES_SENT,
    HEALTH_CHECK,
    DEVICES_ONLINE,
    DEVICES_TOTAL,
)
from app.services.rate_limiter import RateLimiter
from app.services.wg_controller import WireGuardController
from app.services.ws_manager import WebSocketConnectionManager
from app.services.health import HealthChecker
from app.services.daemon import stale_endpoint_cleanup
from app.services.nat import expire_stale_sessions
from app.services.stun_server import StunServer
from app.services.relay_server import RelayServer, set_relay_server, get_relay_server
from app.services.relay import cleanup_expired_relays
from app.core.middleware import RateLimitMiddleware

setup_logging(debug=settings.debug)

_wg_controller: Optional[WireGuardController] = None
_event_bus: Optional[EventBus] = None
_ws_manager: Optional[WebSocketConnectionManager] = None
_stun_server: Optional[StunServer] = None
_relay_server_instance: Optional[RelayServer] = None
_rate_limiter_default: Optional[RateLimiter] = None
_rate_limiter_auth: Optional[RateLimiter] = None
_rate_limiter_register: Optional[RateLimiter] = None
_rate_limiter_heartbeat: Optional[RateLimiter] = None
_rate_limiter_websocket: Optional[RateLimiter] = None
_rate_limiter_admin: Optional[RateLimiter] = None
_health_checker: Optional[HealthChecker] = None


def get_wg_controller() -> Optional[WireGuardController]:
    return _wg_controller


def get_event_bus() -> Optional[EventBus]:
    return _event_bus


async def _update_metrics() -> None:
    while True:
        if _ws_manager:
            WS_CONNECTIONS.set(_ws_manager.active_connections)
            from app.services.metrics import DEVICES_ONLINE as _DEV_ONLINE
            try:
                _DEV_ONLINE.set(_ws_manager.active_daemon_connections)
            except Exception:
                pass
        if _health_checker:
            for probe in ("live", "ready", "startup"):
                try:
                    result = await (
                        _health_checker.check_liveness()
                        if probe == "live"
                        else _health_checker.check_readiness()
                        if probe == "ready"
                        else _health_checker.check_startup()
                    )
                    HEALTH_CHECK.labels(probe=probe).set(1 if result.healthy else 0)
                except Exception:
                    HEALTH_CHECK.labels(probe=probe).set(0)

        if _wg_controller:
            from sqlalchemy import select, func
            from app.models.device import Device
            from datetime import datetime, timezone, timedelta
            try:
                async with get_session_factory()() as session:
                    total = await session.execute(select(func.count(Device.id)))
                    DEVICES_TOTAL.set(total.scalar() or 0)
                    cutoff = datetime.now(timezone.utc) - timedelta(seconds=180)
                    online = await session.execute(
                        select(func.count(Device.id)).where(
                            Device.last_handshake.isnot(None),
                            Device.last_handshake > cutoff,
                        )
                    )
                    DEVICES_ONLINE.set(online.scalar() or 0)
            except Exception:
                pass
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _wg_controller, _event_bus, _ws_manager
    global _rate_limiter_default, _rate_limiter_auth
    global _rate_limiter_register, _rate_limiter_heartbeat
    global _rate_limiter_websocket, _rate_limiter_admin
    global _health_checker

    await init_db(settings.database_url)

    if settings.rate_limit_enabled:
        _rate_limiter_default = RateLimiter(
            max_requests=settings.rate_limit_default_max,
            window_seconds=settings.rate_limit_default_window_seconds,
            redis_url=settings.redis_url,
        )
        _rate_limiter_auth = RateLimiter(
            max_requests=settings.rate_limit_auth_max,
            window_seconds=settings.rate_limit_auth_window_seconds,
            redis_url=settings.redis_url,
        )
        _rate_limiter_register = RateLimiter(
            max_requests=settings.rate_limit_register_max,
            window_seconds=settings.rate_limit_register_window_seconds,
            redis_url=settings.redis_url,
        )
        _rate_limiter_heartbeat = RateLimiter(
            max_requests=settings.rate_limit_heartbeat_max,
            window_seconds=settings.rate_limit_heartbeat_window_seconds,
            redis_url=settings.redis_url,
        )
        _rate_limiter_websocket = RateLimiter(
            max_requests=settings.rate_limit_websocket_max,
            window_seconds=settings.rate_limit_websocket_window_seconds,
            redis_url=settings.redis_url,
        )
        _rate_limiter_admin = RateLimiter(
            max_requests=settings.rate_limit_admin_max,
            window_seconds=settings.rate_limit_admin_window_seconds,
            redis_url=settings.redis_url,
        )
        for limiter in [
            _rate_limiter_default, _rate_limiter_auth,
            _rate_limiter_register, _rate_limiter_heartbeat,
            _rate_limiter_websocket, _rate_limiter_admin,
        ]:
            await limiter.start()

        app.state.rate_limiters = {
            "default": _rate_limiter_default,
            "auth": _rate_limiter_auth,
            "register": _rate_limiter_register,
            "heartbeat": _rate_limiter_heartbeat,
            "websocket": _rate_limiter_websocket,
            "admin": _rate_limiter_admin,
        }

    _ws_manager = WebSocketConnectionManager()

    _event_bus = EventBus(
        redis_url=settings.redis_url if settings.redis_url else None
    )
    await _event_bus.start()

    async def bridge_event(event: Event):
        if _ws_manager:
            await _ws_manager.broadcast(event.to_dict())
            WS_MESSAGES_SENT.inc()
        if event.event_type == CONFIG_CHANGED and _ws_manager:
            data = event.data or {}
            target_device_id = data.get("device_id", "")
            if target_device_id:
                await _ws_manager.send_to_device(
                    target_device_id,
                    event.to_dict(),
                )

    await _event_bus.start_listener(bridge_event)

    if settings.wg_controller_enabled:
        _wg_controller = WireGuardController(
            session_factory=get_session_factory(),
            event_bus=_event_bus,
            interval_seconds=settings.wg_controller_interval_seconds,
        )
        await _wg_controller.start()

    session_factory = get_session_factory()
    _health_checker = HealthChecker(
        session_factory=session_factory,
        wg_controller=_wg_controller,
        event_bus=_event_bus,
    )
    app.state.health_checker = _health_checker

    if settings.stun_enabled:
        global _stun_server
        _stun_server = StunServer(host=settings.stun_host, port=settings.stun_port)
        await _stun_server.start()

    if settings.relay_enabled:
        global _relay_server_instance
        _relay_server_instance = RelayServer(
            host=settings.relay_host,
            port=settings.relay_port,
        )
        await _relay_server_instance.start()
        set_relay_server(_relay_server_instance)

    async def _stale_endpoint_cleanup_loop():
        while True:
            try:
                async with get_session_factory()() as session:
                    await stale_endpoint_cleanup(session, max_age_minutes=30)
            except Exception:
                pass
            await asyncio.sleep(300)

    stale_ep_task = asyncio.create_task(_stale_endpoint_cleanup_loop())

    async def _relay_session_cleanup_loop():
        while True:
            try:
                async with get_session_factory()() as session:
                    await cleanup_expired_relays(session)
                relay_server = get_relay_server()
                if relay_server:
                    relay_server.remove_expired_tokens()
            except Exception:
                pass
            await asyncio.sleep(settings.relay_cleanup_interval_seconds)

    relay_cleanup_task = asyncio.create_task(_relay_session_cleanup_loop())

    async def _nat_session_cleanup_loop():
        while True:
            try:
                async with get_session_factory()() as s:
                    await expire_stale_sessions(s)
            except Exception:
                pass
            await asyncio.sleep(120)

    nat_cleanup_task = asyncio.create_task(_nat_session_cleanup_loop())

    metrics_task = asyncio.create_task(_update_metrics())
    yield
    nat_cleanup_task.cancel()
    try:
        await nat_cleanup_task
    except asyncio.CancelledError:
        pass
    stale_ep_task.cancel()
    try:
        await stale_ep_task
    except asyncio.CancelledError:
        pass
    relay_cleanup_task.cancel()
    try:
        await relay_cleanup_task
    except asyncio.CancelledError:
        pass
    metrics_task.cancel()
    try:
        await metrics_task
    except asyncio.CancelledError:
        pass

    if _stun_server:
        await _stun_server.stop()
    if _relay_server_instance:
        await _relay_server_instance.stop()
        set_relay_server(None)
    if _wg_controller:
        await _wg_controller.stop()
    if _event_bus:
        await _event_bus.stop()
    for limiter in [
        _rate_limiter_default, _rate_limiter_auth,
        _rate_limiter_register, _rate_limiter_heartbeat,
        _rate_limiter_websocket, _rate_limiter_admin,
    ]:
        if limiter:
            await limiter.stop()
    await close_db()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(networks.router, prefix="/api/v1")
app.include_router(devices.router, prefix="/api/v1")
app.include_router(acls.router, prefix="/api/v1")
app.include_router(dns.router, prefix="/api/v1")
app.include_router(ws_router.router, prefix="/api/v1")
app.include_router(routes_router.router, prefix="/api/v1")
app.include_router(audit_router.router, prefix="/api/v1")
app.include_router(nat_router.router, prefix="/api/v1")
app.include_router(relay_router.router, prefix="/api/v1")
app.include_router(health_router.router)


@app.get("/health")
async def health(request: Request):
    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            from app.core.security import decode_token
            from app.models.user import User
            payload = decode_token(token)
            if payload and payload.get("type") == "access":
                uid_str = payload.get("sub")
                if uid_str:
                    from sqlalchemy import select
                    from app.database import get_session_factory
                    async with get_session_factory()() as session:
                        u_result = await session.execute(
                            select(User).where(User.id == uuid.UUID(uid_str), User.is_active)
                        )
                        u = u_result.scalar_one_or_none()
                        if u and not u.is_superuser:
                            from fastapi.responses import JSONResponse
                            return JSONResponse(
                                status_code=status.HTTP_403_FORBIDDEN,
                                content={"detail": "Access denied: superuser privileges required"},
                            )
    except Exception:
        pass
    ctrl = get_wg_controller()
    wsm = _ws_manager
    stun = _stun_server
    return {
        "status": "ok",
        "wg_controller": {
            "running": ctrl.is_running if ctrl else False,
            "last_run": ctrl.last_run.isoformat() if ctrl and ctrl.last_run else None,
        },
        "websocket": {
            "active_connections": wsm.active_connections if wsm else 0,
        },
        "stun": {
            "enabled": settings.stun_enabled,
            "running": stun is not None and stun._running if stun else False,
            "port": stun.port if stun else None,
        },
        "relay": {
            "enabled": settings.relay_enabled,
            "running": get_relay_server() is not None,
            "port": settings.relay_port,
        },
    }


@app.get("/metrics")
async def metrics(request: Request):
    from fastapi import HTTPException, status
    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            from app.core.security import decode_token
            from app.models.user import User
            payload = decode_token(token)
            if payload and payload.get("type") == "access":
                uid_str = payload.get("sub")
                if uid_str:
                    from sqlalchemy import select
                    from app.database import get_session_factory
                    async with get_session_factory()() as session:
                        u_result = await session.execute(
                            select(User).where(User.id == uuid.UUID(uid_str), User.is_active)
                        )
                        u = u_result.scalar_one_or_none()
                        if u and not u.is_superuser:
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail="Access denied: superuser privileges required",
                            )
    except HTTPException:
        raise
    except Exception:
        pass
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from starlette.responses import Response
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
