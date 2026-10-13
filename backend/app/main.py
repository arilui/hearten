from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session

app = FastAPI(title="Hearten API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> dict:
    """Liveness plus a database round trip, so a broken connection shows up here first."""
    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
