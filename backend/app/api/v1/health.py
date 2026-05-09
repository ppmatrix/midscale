"""Health check endpoints for Kubernetes-style probes.

- /health/live  — lightweight, indicates process is alive
- /health/ready — indicates service is ready to accept traffic
- /health/startup — validates the service started correctly
"""

from typing import Annotated, Optional

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.services.health import HealthChecker, HealthStatus

router = APIRouter(tags=["health"])


def _get_checker(request: Request) -> Optional[HealthChecker]:
    return getattr(request.app.state, "health_checker", None)


def _response(status_obj: HealthStatus) -> JSONResponse:
    code = status.HTTP_200_OK if status_obj.healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=code,
        content={
            "healthy": status_obj.healthy,
            "version": status_obj.version,
            "timestamp": status_obj.timestamp,
            "checks": {
                name: {
                    "healthy": check.healthy,
                    "message": check.message,
                }
                for name, check in status_obj.checks.items()
            },
        },
    )


@router.get("/health/live")
async def health_live(request: Request):
    checker = _get_checker(request)
    if not checker:
        return JSONResponse({"healthy": True, "message": "no checker configured"})
    status_obj = await checker.check_liveness()
    return _response(status_obj)


@router.get("/health/ready")
async def health_ready(request: Request):
    checker = _get_checker(request)
    if not checker:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"healthy": False, "message": "health checker not initialized"},
        )
    status_obj = await checker.check_readiness()
    return _response(status_obj)


@router.get("/health/startup")
async def health_startup(request: Request):
    checker = _get_checker(request)
    if not checker:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"healthy": False, "message": "health checker not initialized"},
        )
    status_obj = await checker.check_startup()
    return _response(status_obj)
