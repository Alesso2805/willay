"""FastAPI dependencies shared by the modules (api layer)."""

import math
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from willay.shared.clock import Clock
from willay.shared.config import Settings
from willay.shared.errors import ErrorCode
from willay.shared.i18n import negotiate, translate


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


@dataclass(frozen=True)
class FieldProblem:
    """One invalid input, as in FastAPI's own 422s: where it is and what is wrong with it."""

    loc: Sequence[str | int]
    code: ErrorCode
    params: Mapping[str, object] = field(default_factory=dict)
    type: str = "value_error"


class ApiError(HTTPException):
    """An API error by code (VIG-40): answered as `{"detail": text, "code": code}`, the text in
    the request's language. With `fields`, a 422 whose detail lists them like FastAPI does."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        *,
        fields: Sequence[FieldProblem] = (),
        headers: Mapping[str, str] | None = None,
        **params: object,
    ) -> None:
        super().__init__(status_code, detail=code.value, headers=dict(headers or {}) or None)
        self.code = code
        self.fields = tuple(fields)
        self.params = params


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    language = negotiate(request.headers.get("accept-language"))
    detail: object = translate(f"errors.{exc.code}", language, **exc.params)
    if exc.fields:
        detail = [
            {
                "loc": list(problem.loc),
                "msg": translate(f"errors.{problem.code}", language, **problem.params),
                "type": problem.type,
                "code": problem.code.value,
            }
            for problem in exc.fields
        ]
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail, "code": exc.code.value},
        headers={**(exc.headers or {}), "Content-Language": language.value},
    )
