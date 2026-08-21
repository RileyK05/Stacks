from __future__ import annotations

from fastapi import FastAPI
from src.backend.api import auth


def create_app() -> FastAPI:
    app = FastAPI(title="Course Assistant")
    app.include_router(auth.router)
    return app


app = create_app()
