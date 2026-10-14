"""
Check a recipe from the command line against your database.

    python -m scripts.check_recipe data/examples/chicken_stir_fry.txt --servings 4 \
        --condition hypertension --condition type2_diabetes --budget 4.00 --diet halal

The recipe file has one ingredient per line. Run with --help for every option.
"""

import argparse
import sys
from pathlib import Path

from app.catalog import Catalog, recipe_lines
from app.rules.engine import RecipeCheck, check_recipe
from app.rules.profile import Profile

ICONS = {"fits": "OK  ", "over": "OVER", "incomplete": "??  ", "info": "    ",
         "meets_goal": "OK  ", "below_goal": "LOW ", "progress": "    ",
         "doesnt_fit": "NO  ", "check": "CHECK"}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipe", type=Path, help="text file, one ingredient per line")
    ap.add_argument("--servings", type=float, required=True)
    ap.add_argument("--condition", action="append", default=[],
                    choices=["hypertension", "type2_diabetes"])
    ap.add_argument("--sex", choices=["male", "female"])
    ap.add_argument("--sodium", choices=["default", "strict"], default="default")
    ap.add_argument("--sodium-mg", type=float, help="your provider's daily sodium limit")
    ap.add_argument("--added-sugars-g", type=float, help="your provider's daily limit")
    ap.add_argument("--carb-target", type=float, help="your carb target per meal, in g")
    ap.add_argument("--insulin", action="store_true")
    ap.add_argument("--meals", type=int, default=3, help="meals per day")
    ap.add_argument("--snack", type=float, choices=[0.5, 0.25, 0.125],
                    help="check as a snack: this fraction of a meal")
    ap.add_argument("--budget", type=float, help="max dollars per meal")
    ap.add_argument("--diet", action="append", default=[],
                    choices=["vegetarian", "vegan", "pescatarian", "no_beef", "halal",
                             "kosher", "gluten_free", "dairy_free", "alcohol_free"])
    ap.add_argument("--allergen", action="append", default=[],
                    choices=["milk", "egg", "fish", "crustacean", "tree_nut", "peanut",
                             "wheat", "soy", "sesame"])
    ap.add_argument("--exclude", action="append", default=[], help="any ingredient word")
    ap.add_argument("--certified", action="store_true",
                    help="you buy certified halal/kosher meat and products")
    return ap.parse_args(argv)


def build_profile(args) -> Profile:
    return Profile(
        conditions=set(args.condition), sex=args.sex,
        sodium="custom" if args.sodium_mg else args.sodium, sodium_custom_mg=args.sodium_mg,
        added_sugars_custom_g=args.added_sugars_g, carb_target_g_per_meal=args.carb_target,
        takes_insulin=args.insulin, meals_per_day=args.meals, snack_fraction=args.snack or 1,
        budget_minor_per_meal=round(args.budget * 100) if args.budget else None,
        diets=set(args.diet), allergens=set(args.allergen), custom_exclusions=args.exclude,
        buys_certified=args.certified,
    )


def report(ingredients, result: RecipeCheck) -> str:
    out = ["Ingredients"]
    for ing in ingredients:
        grams = f"{ing.grams:7.1f} g" if ing.grams is not None else "      - "
        out.append(f"  {grams}  {ing.line}")
        out.append(f"             -> {ing.description or 'not identified'}")
        for w in ing.warnings:
            out.append(f"                ({w})")
    out += ["", result.summary, "", "Nutrients per serving"]
    for c in result.nutrients:
        out.append(f"  [{ICONS[c.status]:<5}] {c.message}")
        if c.status in ("over", "incomplete") and c.contributors:
            names = ", ".join(x.line for x in c.contributors)
            out.append(f"           most from: {names}")
        for note in c.notes:
            out.append(f"           note: {note}")
        if c.source and c.kind != "info":
            out.append(f"           source: {c.source.name}")
    b = result.budget
    out += ["", "Budget", f"  [{ICONS[b.status]:<5}] {b.message}"]
    for x in b.most_expensive:
        out.append(f"           ${x.amount / 100:,.2f}  {x.line}")
    if b.missing_prices:
        out.append(f"           no price: {', '.join(b.missing_prices)}")
    if result.diet:
        out += ["", "Dietary requirements"]
        for d in result.diet:
            out.append(f"  [{ICONS[d.status]:<5}] {d.requirement}: {d.message}")
            for c in d.conflicts:
                out.append(f"           {c.line}: {c.reason}")
            for c in d.to_check:
                out.append(f"           check: {c.line}")
    if result.not_counted:
        out += ["", "Not counted"]
        out += [f"  {n.line}: {n.reason}" for n in result.not_counted]
    out += [""] + [f"* {n}" for n in result.notes]
    return "\n".join(out)


def main(argv=None) -> None:
    from app.db import get_engine

    args = parse_args(argv)
    profile = build_profile(args)
    print("Loading foods...", file=sys.stderr, flush=True)
    catalog = Catalog.load(get_engine())
    ingredients = [catalog.resolve(line)
                   for line in recipe_lines(args.recipe.read_text(encoding="utf-8"))]
    print(report(ingredients, check_recipe(ingredients, args.servings, profile)))


if __name__ == "__main__":
    main()
