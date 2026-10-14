"""
Measure how well recipe lines are matched to foods and converted to grams.

    python -m scripts.eval_matching            # uses data/raw
    python -m scripts.eval_matching --show-all

The labeled lines are in data/eval/ingredient_lines.csv. Each row gives the
recipe line, a regular expression for the acceptable USDA descriptions, and a
reference weight in grams (blank = not scored). Rows are split into "dev"
(used while tuning the matcher) and "test" (held out, checked only after
tuning), so the test numbers are an honest estimate.

Metrics, per split:
  - food match: the top match is an acceptable food
  - grams within 25%: the final gram estimate is within 25% of the reference
    (end to end, so a wrong match usually counts against it too)
"""

import argparse
import re
from pathlib import Path

import pandas as pd

from app.ingredients.grams import Portion, to_grams
from app.ingredients.match import FoodIndex, query_text
from app.ingredients.parse import parse_line
from scripts import sr_legacy

BACKEND = Path(__file__).resolve().parents[1]
RAW = BACKEND.parent / "data" / "raw"
LINES = BACKEND / "data" / "eval" / "ingredient_lines.csv"
GRAM_TOLERANCE = 0.25


def build(sr_folder: Path, input_food: Path | None):
    foods = sr_legacy.read_foods(sr_folder)
    portions = sr_legacy.read_portions(sr_folder, set(foods["fdc_id"]))
    usage = {}
    if input_food is not None and input_food.exists():
        usage = sr_legacy.usage_counts(pd.read_csv(input_food, low_memory=False), foods)
    index = FoodIndex(list(zip(foods["fdc_id"], foods["description"], strict=True)), usage)
    by_food: dict[int, list[Portion]] = {}
    for row in portions.itertuples(index=False):
        by_food.setdefault(row.fdc_id, []).append(Portion(row.description, row.gram_weight))
    return index, by_food


def evaluate(index: FoodIndex, portions: dict[int, list[Portion]],
             lines: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for item in lines.itertuples(index=False):
        parsed = parse_line(item.line)
        top = index.search(query_text(parsed), limit=1)
        desc = top[0].description if top else ""
        grams = to_grams(parsed, portions.get(top[0].food_code, [])).grams if top else None
        ref = item.grams if pd.notna(item.grams) else None
        rows.append({
            "split": item.split, "line": item.line, "matched": desc,
            "food_ok": bool(re.fullmatch(item.accept, desc, re.IGNORECASE)),
            "grams": None if grams is None else round(grams, 1), "ref": ref,
            "grams_ok": (None if ref is None else
                         grams is not None and abs(grams - ref) <= GRAM_TOLERANCE * ref),
        })
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> str:
    out = []
    for split, g in results.groupby("split", sort=False):
        scored = g.dropna(subset=["grams_ok"])
        out.append(f"{split:<5} food match {g['food_ok'].mean():6.1%}  ({g['food_ok'].sum()}/"
                   f"{len(g)})   grams within 25% {scored['grams_ok'].astype(bool).mean():6.1%}"
                   f"  ({int(scored['grams_ok'].sum())}/{len(scored)})")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sr", type=Path, default=RAW / "sr_legacy")
    ap.add_argument("--input-food", type=Path, default=None,
                    help="FNDDS input_food.csv (default: found under data/raw/fndds)")
    ap.add_argument("--split", default=None)
    ap.add_argument("--show-all", action="store_true")
    args = ap.parse_args()

    input_food = args.input_food
    if input_food is None:
        found = sorted((RAW / "fndds").rglob("input_food.csv"))
        input_food = found[0] if found else None

    lines = pd.read_csv(LINES)
    if args.split:
        lines = lines[lines["split"] == args.split]
    index, portions = build(args.sr, input_food)
    results = evaluate(index, portions, lines)

    shown = results if args.show_all else results[
        ~results["food_ok"] | (results["grams_ok"] == False)  # noqa: E712
    ]
    with pd.option_context("display.width", 200, "display.max_colwidth", 70,
                           "display.max_rows", 500):
        if len(shown):
            print(shown[["split", "line", "matched", "food_ok", "grams", "ref"]]
                  .to_string(index=False))
            print()
    print(summarize(results))


if __name__ == "__main__":
    main()
