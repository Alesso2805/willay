"""FastAPI dependencies shared by the modules (api layer)."""

import math
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from vigia.shared.clock import Clock
from vigia.shared.config import Settings


async def db_connection(request: Request) -> AsyncIterator[AsyncConnection]:
    """One transaction per request: commit if the endpoint succeeds, rollback if it raises."""
    engine: AsyncEngine = request.app.state.engine
    async with engine.begin() as conn:
        yield conn


def get_engine(request: Request) -> AsyncEngine:
    """For steps that open their own short transaction, outside the request's one."""
    engine: AsyncEngine = request.app.state.engine
    return engine


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_app_settings(request: Request) -> Settings:
    """The settings the app started with (in tests, the test's settings)."""
    settings: Settings = request.app.state.settings
    return settings


DbConnection = Annotated[AsyncConnection, Depends(db_connection)]
EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
ClockDep = Annotated[Clock, Depends(get_clock)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)  # "nan", "inf", "-inf"
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    return value


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """422 in FastAPI's format, but serializable even when the input contains NaN.

    The default handler echoes the received value; a broken sensor sending NaN would make the
    response JSON unrenderable and the API would return 500 instead of 422.
    """
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": _json_safe(jsonable_encoder(exc.errors()))},
    )
