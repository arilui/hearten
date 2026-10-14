"""
The food catalogue in memory: everything the recipe check needs from Postgres.

Loading ~12,000 foods with their portions, the checked nutrients, tags and
prices takes a few queries and a few MB, so the API loads it once per process
and reuses it. Resolving a recipe line (parse -> match -> grams) then needs no
database round trips.
"""

from dataclasses import dataclass, field

from sqlalchemy import Engine, bindparam, text

from app import nutrients as N
from app.ingredients.grams import Portion, to_grams
from app.ingredients.match import MIN_SCORE, FoodIndex, build_index, query_text
from app.ingredients.parse import parse_line
from app.rules.engine import Ingredient


@dataclass
class Food:
    code: int
    description: str
    source: str
    recipe_uses: int
    portions: list[Portion] = field(default_factory=list)
    nutrients: dict[int, float] = field(default_factory=dict)
    tags: set[str] = field(default_factory=set)
    price_minor_per_100g: float | None = None


class Catalog:
    def __init__(self, foods: dict[int, Food]):
        self.foods = foods
        self.index: FoodIndex = build_index(
            [(f.code, f.description, f.source, f.recipe_uses) for f in foods.values()])

    @classmethod
    def load(cls, engine: Engine, currency: str = "USD") -> "Catalog":
        with engine.connect() as conn:
            foods = {
                code: Food(code, desc, source, uses)
                for code, desc, source, uses in conn.execute(text(
                    "SELECT food_code, description, source, recipe_uses FROM food"))
            }
            for code, desc, grams in conn.execute(text(
                    "SELECT food_code, description, gram_weight FROM food_portion "
                    "ORDER BY food_code, portion_id")):
                foods[code].portions.append(Portion(desc, float(grams)))
            query = text("SELECT food_code, nutrient_id, amount_per_100g FROM food_nutrient "
                         "WHERE nutrient_id IN :ids").bindparams(
                bindparam("ids", expanding=True))
            for code, nutrient, amount in conn.execute(query, {"ids": list(N.CHECKED)}):
                foods[code].nutrients[nutrient] = float(amount)
            for code, tag in conn.execute(text("SELECT food_code, tag FROM food_tag")):
                foods[code].tags.add(tag)
            for code, amount in conn.execute(
                    text("SELECT food_code, amount_minor_per_100g FROM food_price "
                         "WHERE currency = :currency"), {"currency": currency}):
                foods[code].price_minor_per_100g = float(amount)
        return cls(foods)

    def resolve(self, line: str) -> Ingredient:
        """One recipe line -> a matched food with grams, or an unmatched line."""
        parsed = parse_line(line)
        candidates = self.index.search(query_text(parsed), limit=1) if parsed.food else []
        if not candidates or candidates[0].score < MIN_SCORE:
            return Ingredient(line=line, food_words=parsed.food, food_code=None,
                              description=None, grams=None,
                              warnings=["couldn't identify the food"])
        food = self.foods[candidates[0].food_code]
        grams = to_grams(parsed, food.portions)
        return Ingredient(
            line=line, food_words=parsed.food, food_code=food.code,
            description=food.description, grams=grams.grams,
            nutrients_per_100g=dict(food.nutrients), tags=frozenset(food.tags),
            price_minor_per_100g=food.price_minor_per_100g,
            warnings=parsed.warnings + grams.warnings,
        )


def recipe_lines(text_block: str) -> list[str]:
    """Ingredient lines from pasted text: one per line, skipping blanks and headings."""
    lines = []
    for raw in text_block.splitlines():
        line = raw.strip().lstrip("-•*·▢□☐").strip()
        if not line or line.endswith(":"):
            continue
        lines.append(line)
    return lines
