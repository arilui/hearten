"""
Tag every food with what it contains, and list the foods a person should check.

Run from the backend folder after the data import:

    python -m scripts.tag_foods

Outputs:
  - the food_tag table, rebuilt from the rules plus reviewed overrides
  - data/review/tag_review.csv: foods the rules couldn't settle, with reasons

Reviewing: for each food in tag_review.csv that needs a change, add a row to
backend/data/tag_overrides.csv:

    food_code,tag,action,note
    22401000,pork,remove,"Turkey hot dog per USDA ingredients"
    83107000,fish,add,"Contains anchovy paste"

Overrides are applied after the rules on every run, so decisions are kept.
Tags they add or confirm are recorded as set_by = 'review'.
"""

import io
from pathlib import Path

import pandas as pd

from scripts.tag_rules import FPED_GROUPS, TAGS, tag_food

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
REVIEW_FILE = ROOT / "data" / "review" / "tag_review.csv"
OVERRIDES_FILE = Path(__file__).resolve().parents[1] / "data" / "tag_overrides.csv"

FPED_SEAFOOD_AND_NUTS = ["PF_SEAFD_HI (oz eq)", "PF_SEAFD_LOW (oz eq)", "PF_NUTSDS (oz eq)"]


# ----------------------------------------------------------------- readers ----

def read_foods(fndds: Path) -> pd.DataFrame:
    food = pd.read_csv(next(fndds.rglob("food.csv")), low_memory=False)
    codes = pd.read_csv(next(fndds.rglob("survey_fndds_food.csv")), low_memory=False)
    return food[["fdc_id", "description"]].merge(codes[["fdc_id", "food_code"]], on="fdc_id")


def read_ingredients(fndds: Path, foods: pd.DataFrame) -> dict[int, list[str]]:
    """
    Ingredient descriptions for each food, keyed by fdc_id. Some ingredients are
    themselves FNDDS foods (fdc_of_input_food); their names and ingredients are
    pulled in too, a few levels deep.
    """
    inputs = pd.read_csv(next(fndds.rglob("input_food.csv")), low_memory=False)
    names = foods.set_index("fdc_id")["description"].to_dict()

    direct: dict[int, list[str]] = {}
    nested: dict[int, list[int]] = {}
    for row in inputs.itertuples(index=False):
        fdc = int(row.fdc_id)
        if isinstance(row.sr_description, str):
            direct.setdefault(fdc, []).append(row.sr_description)
        if pd.notna(row.fdc_of_input_food):
            child = int(row.fdc_of_input_food)
            nested.setdefault(fdc, []).append(child)
            if child in names:
                direct.setdefault(fdc, []).append(names[child])

    def collect(fdc: int, depth: int) -> list[str]:
        items = list(direct.get(fdc, []))
        if depth > 0:  # recipes rarely nest deeper than a few levels
            for child in nested.get(fdc, []):
                items.extend(collect(child, depth - 1))
        return items

    return {fdc: collect(fdc, 3) for fdc in direct.keys() | nested.keys()}


def read_fped_groups(path: Path) -> dict[int, dict[str, float]]:
    raw = pd.read_csv(path) if path.suffix == ".csv" else pd.read_excel(path)
    columns = [c for c in [*FPED_GROUPS, *FPED_SEAFOOD_AND_NUTS] if c in raw.columns]
    raw = raw.set_index(raw["FOODCODE"].astype(int))[columns]
    return raw.to_dict(orient="index")


def read_overrides(path: Path = OVERRIDES_FILE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["food_code", "tag", "action", "note"])
    overrides = pd.read_csv(path, comment="#")
    unknown = set(overrides["tag"]) - set(TAGS)
    bad_action = set(overrides["action"]) - {"add", "remove"}
    if unknown or bad_action:
        raise ValueError(f"tag_overrides.csv: unknown tags {unknown or '-'}, "
                         f"unknown actions {bad_action or '-'}")
    return overrides


# -------------------------------------------------------------- transform ----

def compute_tags(foods: pd.DataFrame, ingredients: dict[int, list[str]],
                 fped: dict[int, dict[str, float]],
                 overrides: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (food_tag rows, review rows)."""
    tag_rows, review_rows = [], []
    for food in foods.itertuples(index=False):
        code = int(food.food_code)
        result = tag_food(food.description, ingredients.get(int(food.fdc_id), []),
                          fped.get(code, {}))
        tag_rows.extend({"food_code": code, "tag": t, "set_by": "rule"} for t in result.tags)
        if result.review_reasons:
            review_rows.append({
                "food_code": code,
                "description": food.description,
                "tags": " ".join(sorted(result.tags)),
                "reasons": "; ".join(sorted(set(result.review_reasons))),
            })

    tags = pd.DataFrame(tag_rows, columns=["food_code", "tag", "set_by"])
    known = set(foods["food_code"].astype(int))
    added = []
    for o in overrides.itertuples(index=False):
        code = int(o.food_code)
        if code not in known:
            continue
        match = (tags["food_code"] == code) & (tags["tag"] == o.tag)
        if o.action == "remove":
            tags = tags[~match]
        elif match.any():
            tags.loc[match, "set_by"] = "review"
        else:
            added.append({"food_code": code, "tag": o.tag, "set_by": "review"})
    tags = pd.concat([tags, pd.DataFrame(added, columns=tags.columns)], ignore_index=True)

    review = pd.DataFrame(review_rows, columns=["food_code", "description", "tags", "reasons"])
    reviewed = set(overrides["food_code"].astype(int))
    review = review[~review["food_code"].isin(reviewed)].sort_values(["reasons", "description"])
    return tags.drop_duplicates(["food_code", "tag"]).reset_index(drop=True), review


# ------------------------------------------------------------------- write ----

def write_tags(engine, tags: pd.DataFrame) -> None:
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("DELETE FROM food_tag")
            buffer = io.StringIO()
            tags[["food_code", "tag", "set_by"]].to_csv(buffer, index=False, header=False)
            buffer.seek(0)
            sql = "COPY food_tag (food_code, tag, set_by) FROM STDIN WITH (FORMAT csv)"
            with cur.copy(sql) as copy:
                copy.write(buffer.getvalue())
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def main() -> None:
    from app.db import get_engine

    foods = read_foods(RAW / "fndds")
    tags, review = compute_tags(
        foods,
        read_ingredients(RAW / "fndds", foods),
        read_fped_groups(RAW / "fped_1720.xls"),
        read_overrides(),
    )
    REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(REVIEW_FILE, index=False)

    counts = tags["tag"].value_counts()
    print(f"Tagged {tags['food_code'].nunique():,} of {len(foods):,} foods "
          f"with {len(tags):,} tags.")
    for tag in TAGS:
        print(f"  {tag:<16} {counts.get(tag, 0):>5,}")
    print(f"\nFoods to review: {len(review):,} (written to {REVIEW_FILE.relative_to(ROOT)})")
    for reason, n in review["reasons"].str.split("; ").explode().value_counts().items():
        print(f"  {n:>5,}  {reason}")

    write_tags(get_engine(), tags)
    print("\nSaved to the database.")


if __name__ == "__main__":
    main()
