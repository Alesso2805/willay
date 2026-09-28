"""Dependencias de FastAPI compartidas por los módulos (capa api)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


async def db_connection(request: Request) -> AsyncIterator[AsyncConnection]:
    """Una transacción por petición: commit si el endpoint termina bien, rollback si lanza."""
    engine: AsyncEngine = request.app.state.engine
    async with engine.begin() as conn:
        yield conn


DbConnection = Annotated[AsyncConnection, Depends(db_connection)]
