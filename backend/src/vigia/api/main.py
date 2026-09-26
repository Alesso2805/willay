"""App FastAPI. Se ejecuta con `uvicorn vigia.api.main:app`.

Los workers nunca arrancan en el lifespan de esta app: son procesos separados.
"""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Vigía API", version="0.1.0")

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
