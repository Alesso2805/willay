"""Dependencias de FastAPI compartidas por los módulos (capa api)."""

import math
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from vigia.shared.clock import Clock


async def db_connection(request: Request) -> AsyncIterator[AsyncConnection]:
    """Una transacción por petición: commit si el endpoint termina bien, rollback si lanza."""
    engine: AsyncEngine = request.app.state.engine
    async with engine.begin() as conn:
        yield conn


def get_engine(request: Request) -> AsyncEngine:
    """Para pasos que abren su propia transacción corta, fuera de la de la petición."""
    engine: AsyncEngine = request.app.state.engine
    return engine


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


DbConnection = Annotated[AsyncConnection, Depends(db_connection)]
EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
ClockDep = Annotated[Clock, Depends(get_clock)]


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)  # "nan", "inf", "-inf"
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    return value


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """422 con el mismo formato que FastAPI, pero serializable aunque el input traiga NaN.

    El manejador por defecto incluye el valor recibido; si un sensor averiado envía NaN,
    el JSON de la respuesta no se puede generar y la API devolvería 500 en lugar de 422.
    """
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": _json_safe(jsonable_encoder(exc.errors()))},
    )
