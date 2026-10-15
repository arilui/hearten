"""
Hearten API.

    GET  /health   liveness plus a database round trip
    GET  /warm     load the food catalogue now (the website calls this on page load)
    POST /check    check a pasted recipe against a person's plan

The food catalogue is loaded from Postgres on the first /check and kept in
memory for the life of the process (one Lambda container, or one dev server).
Nothing a person sends is stored.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.catalog import Catalog, recipe_lines
from app.config import get_settings
from app.db import get_engine, get_session
from app.rules.engine import RecipeCheck, check_recipe
from app.rules.profile import Profile

MAX_LINES = 60

app = FastAPI(title="Hearten API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@lru_cache
def _load_catalog() -> Catalog:
    return Catalog.load(get_engine())


def get_catalog() -> Catalog:
    """FastAPI dependency; tests replace it with a small in-memory catalogue."""
    return _load_catalog()


class CheckRequest(BaseModel):
    recipe: str = Field(min_length=1, max_length=20_000,
                        description="Ingredient lines, one per line, as pasted.")
    servings: float = Field(gt=0, le=100)
    profile: Profile = Field(default_factory=Profile)


class MatchedLine(BaseModel):
    line: str
    food_code: int | None
    food: str | None
    grams: float | None
    warnings: list[str]


class CheckResponse(BaseModel):
    ingredients: list[MatchedLine]
    result: RecipeCheck


@app.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> dict:
    """Liveness plus a database round trip, so a broken connection shows up here first."""
    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@app.get("/warm")
def warm(catalog: Annotated[Catalog, Depends(get_catalog)]) -> dict:
    """Loading the catalogue takes a few seconds on a cold start; doing it while the
    person is still typing their recipe makes the first check fast."""
    return {"status": "ready", "foods": len(catalog.foods)}


@app.post("/check")
def check(request: CheckRequest,
          catalog: Annotated[Catalog, Depends(get_catalog)]) -> CheckResponse:
    lines = recipe_lines(request.recipe)
    if not lines:
        raise HTTPException(422, "No ingredient lines found. Paste one ingredient per line.")
    if len(lines) > MAX_LINES:
        raise HTTPException(422, f"That's {len(lines)} lines; the limit is {MAX_LINES}.")
    ingredients = [catalog.resolve(line) for line in lines]
    result = check_recipe(ingredients, request.servings, request.profile)
    return CheckResponse(
        ingredients=[MatchedLine(line=i.line, food_code=i.food_code, food=i.description,
                                 grams=None if i.grams is None else round(i.grams, 1),
                                 warnings=i.warnings) for i in ingredients],
        result=result,
    )
