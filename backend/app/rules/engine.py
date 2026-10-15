"""
Check one recipe against a person's plan: condition limits, budget and diet.

The engine is pure: it takes ingredients that are already matched to foods
(with grams, nutrients, tags and prices) and a Profile, and returns a
structured result. Loading foods and matching lines happens in app.catalog.

How daily limits apply to one recipe (see the spec, "From daily limits to a
single recipe"): a serving is compared with one meal's share of each daily
limit (daily limit / meals per day, times a snack fraction). Goals such as
potassium are shown as progress, never as a failure. Ratios such as fiber per
1,000 kcal are judged on the recipe itself.

Missing data is never treated as zero. If some ingredients have no value for
a nutrient or no price, the result says "incomplete" unless the known part is
already over the limit.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app import nutrients as N
from app.rules import guidelines as G
from app.rules.profile import Profile
from app.rules.requirements import ALLERGENS, DIETS, KOSHER_MEAT, Requirement

Status = Literal["fits", "over", "incomplete", "info", "meets_goal", "below_goal", "progress",
                 "doesnt_fit", "check"]


@dataclass
class Ingredient:
    """One recipe line, matched to a food. food_code None = couldn't be matched."""
    line: str
    food_words: str
    food_code: int | None
    description: str | None
    grams: float | None
    nutrients_per_100g: dict[int, float] = field(default_factory=dict)
    tags: frozenset[str] = frozenset()
    price_minor_per_100g: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class Contributor:
    line: str
    amount: float


@dataclass
class NutrientCheck:
    key: str
    label: str
    unit: str
    per_serving: float | None
    kind: Literal["limit", "goal", "ratio", "info"]
    status: Status
    message: str
    daily_value: float | None = None
    meal_share: float | None = None
    percent_of_day: float | None = None
    contributors: list[Contributor] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    source: G.Source | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class BudgetCheck:
    currency: str
    cost_minor_per_serving: int | None
    budget_minor: int | None
    status: Status
    message: str
    most_expensive: list[Contributor] = field(default_factory=list)
    missing_prices: list[str] = field(default_factory=list)


@dataclass
class Conflict:
    line: str
    reason: str


@dataclass
class DietCheck:
    requirement: str
    status: Status
    message: str
    conflicts: list[Conflict] = field(default_factory=list)
    to_check: list[Conflict] = field(default_factory=list)
    cant_know: str = ""


@dataclass
class NotCounted:
    line: str
    reason: str


@dataclass
class RecipeCheck:
    servings: float
    fits_plan: bool | None   # None: can't tell yet, some data is missing
    summary: str
    nutrients: list[NutrientCheck]
    budget: BudgetCheck
    diet: list[DietCheck]
    not_counted: list[NotCounted]
    notes: list[str]


# ------------------------------------------------------------------ helpers --

def _fmt(value: float, unit: str) -> str:
    if unit == "mg" or value >= 100:
        return f"{value:,.0f} {unit}"
    return f"{value:,.1f} {unit}".replace(".0 ", " ")


def _share_words(fraction: float) -> str:
    named = {1.0: "all of your day", 0.5: "half your day", 0.25: "a quarter of your day"}
    for value, words in named.items():
        if abs(fraction - value) < 0.02:
            return words
    return f"{fraction:.0%} of your day"


def _amounts(ingredients: list[Ingredient], key: int) -> tuple[list[Contributor], list[str]]:
    """Each ingredient's amount of a nutrient, and the lines with no data for it."""
    found, missing = [], []
    for ing in ingredients:
        if ing.grams is None or ing.food_code is None:
            continue  # reported once, as unmatched
        if key not in ing.nutrients_per_100g:
            missing.append(ing.line)
            continue
        found.append(Contributor(ing.line, ing.grams * ing.nutrients_per_100g[key] / 100))
    return found, missing


def _per_serving(ingredients, key, servings) -> tuple[float, list[Contributor], list[str]]:
    found, missing = _amounts(ingredients, key)
    per = [Contributor(c.line, round(c.amount / servings, 2)) for c in found]
    per.sort(key=lambda c: -c.amount)
    return sum(c.amount for c in per), per, missing


def _limit_check(key: str, label: str, unit: str, value: float, contributors, missing,
                 daily: float, share: float, source: G.Source) -> NutrientCheck:
    meal_share = daily * share
    pct = value / daily
    amount = _fmt(value, unit)
    top = [c for c in contributors if c.amount > 0][:3]
    if value > meal_share:
        status = "over"
        message = (f"{amount} {label.lower()} per serving, {_share_words(pct)}. "
                   f"That's more than one meal's share ({_fmt(meal_share, unit)}).")
    elif missing:
        status = "incomplete"
        message = (f"At least {amount} {label.lower()} per serving; {len(missing)} "
                   f"ingredient(s) have no data, so it may be more.")
    else:
        status = "fits"
        message = (f"{amount} {label.lower()} per serving fits your plan "
                   f"({pct:.0%} of your daily limit).")
    return NutrientCheck(key, label, unit, round(value, 2), "limit", status, message,
                         daily_value=daily, meal_share=round(meal_share, 2),
                         percent_of_day=round(pct, 4), contributors=top,
                         missing_data=missing, source=source)


def _info(key, label, unit, value, contributors, missing, note="") -> NutrientCheck:
    amount = _fmt(value, unit)
    message = f"{'At least ' if missing else ''}{amount} {label.lower()} per serving."
    if note:
        message += " " + note
    return NutrientCheck(key, label, unit, round(value, 2), "info", "info", message,
                         contributors=[c for c in contributors if c.amount > 0][:3],
                         missing_data=missing)


# ---------------------------------------------------------- nutrient checks --

def _sodium_limit(profile: Profile) -> tuple[float, G.Source]:
    if profile.sodium == "custom":
        return profile.sodium_custom_mg, G.YOUR_PROVIDER
    if profile.sodium == "strict":
        return G.SODIUM_STRICT_MG, G.ACC_AHA_2025
    source = G.NHLBI_DASH if "hypertension" in profile.conditions else G.ADA_2026
    return G.SODIUM_DEFAULT_MG, source


def check_nutrients(ingredients: list[Ingredient], servings: float,
                    profile: Profile) -> list[NutrientCheck]:
    has_ht = "hypertension" in profile.conditions
    has_t2d = "type2_diabetes" in profile.conditions
    sex = profile.sex or G.UNSPECIFIED_SEX
    share = profile.meal_share
    checks = []

    value, contrib, missing = _per_serving(ingredients, N.SODIUM_MG, servings)
    if profile.conditions:
        daily, source = _sodium_limit(profile)
        checks.append(_limit_check("sodium", "Sodium", "mg", value, contrib, missing,
                                   daily, share, source))
    else:
        checks.append(_info("sodium", "Sodium", "mg", value, contrib, missing))

    value, contrib, missing = _per_serving(ingredients, N.ADDED_SUGARS_G, servings)
    if has_t2d:
        daily = profile.added_sugars_custom_g or G.ADDED_SUGARS_FLAG_G
        source = G.YOUR_PROVIDER if profile.added_sugars_custom_g else G.FDA_DAILY_VALUE
        checks.append(_limit_check("added_sugars", "Added sugars", "g", value, contrib,
                                   missing, daily, share, source))
    else:
        checks.append(_info("added_sugars", "Added sugars", "g", value, contrib, missing))

    value, contrib, missing = _per_serving(ingredients, N.CARBOHYDRATE_G, servings)
    carb_servings = f"About {value / G.CARB_SERVING_G:.1f} carb servings of 15 g."
    if has_t2d and profile.carb_target_g_per_meal:
        checks.append(_carb_target_check(value, contrib, missing, profile, carb_servings))
    else:
        checks.append(_info("carbohydrate", "Carbohydrate", "g", value, contrib, missing,
                            carb_servings if has_t2d else ""))

    if has_t2d:
        checks.append(_fiber_check(ingredients, servings))

    if has_ht:
        value, contrib, missing = _per_serving(ingredients, N.POTASSIUM_MG, servings)
        goal = G.POTASSIUM_GOAL_MG[sex]
        pct = value / goal
        checks.append(NutrientCheck(
            "potassium", "Potassium", "mg", round(value, 2), "goal", "progress",
            f"{'At least ' if missing else ''}{_fmt(value, 'mg')} potassium per serving, "
            f"{pct:.0%} of the daily goal.",
            daily_value=goal, percent_of_day=round(pct, 4),
            contributors=[c for c in contrib if c.amount > 0][:3], missing_data=missing,
            source=G.NIH_POTASSIUM, notes=[G.POTASSIUM_CAUTION]))

    # Alcohol is only shown when the recipe has some; "0 drinks" on every recipe is noise.
    alcohol = _alcohol_check(ingredients, servings, profile, sex, has_ht, has_t2d)
    if profile.conditions and alcohol.per_serving > 0:
        checks.append(alcohol)
    return checks


def _carb_target_check(value, contrib, missing, profile: Profile,
                       carb_servings: str) -> NutrientCheck:
    """Carbs are judged only against the user's own per-meal target (ADA sets none)."""
    target = profile.carb_target_g_per_meal * profile.snack_fraction
    amount = _fmt(value, "g")
    if value > target:
        status = "over"
        message = f"{amount} carbohydrate per serving, above your {_fmt(target, 'g')} target."
    elif missing:
        status = "incomplete"
        message = (f"At least {amount} carbohydrate per serving; {len(missing)} ingredient(s) "
                   f"have no data, so it may be more than your {_fmt(target, 'g')} target.")
    else:
        status = "fits"
        message = f"{amount} carbohydrate per serving fits your {_fmt(target, 'g')} target."
    return NutrientCheck("carbohydrate", "Carbohydrate", "g", round(value, 2), "limit", status,
                         message, daily_value=None, meal_share=round(target, 2),
                         contributors=[c for c in contrib if c.amount > 0][:3],
                         missing_data=missing, source=G.YOUR_PROVIDER, notes=[carb_servings])


def _fiber_check(ingredients: list[Ingredient], servings: float) -> NutrientCheck:
    fiber, contrib, missing_f = _per_serving(ingredients, N.FIBER_G, servings)
    kcal, _, missing_e = _per_serving(ingredients, N.ENERGY_KCAL, servings)
    missing = sorted(set(missing_f) | set(missing_e))
    if kcal <= 0:
        return NutrientCheck("fiber", "Fiber", "g", round(fiber, 2), "ratio", "info",
                             f"{_fmt(fiber, 'g')} fiber per serving.", source=G.ADA_2026)
    per_1000 = fiber / kcal * 1000
    goal = G.FIBER_G_PER_1000_KCAL
    if per_1000 >= goal:
        status, words = "meets_goal", "meets the goal"
    elif missing:
        status, words = "incomplete", "can't be judged yet (some ingredients have no data)"
    else:
        status, words = "below_goal", "is below the goal"
    return NutrientCheck(
        "fiber", "Fiber", "g", round(fiber, 2), "ratio", status,
        f"{_fmt(fiber, 'g')} fiber per serving: {per_1000:.1f} g per 1,000 kcal {words} "
        f"of {goal} g.", daily_value=goal,
        contributors=[c for c in contrib if c.amount > 0][:3], missing_data=missing,
        source=G.ADA_2026)


def _alcohol_check(ingredients, servings, profile, sex, has_ht, has_t2d) -> NutrientCheck:
    grams, contrib, missing = _per_serving(ingredients, N.ALCOHOL_G, servings)
    drinks = grams / G.GRAMS_ALCOHOL_PER_DRINK
    contrib = [Contributor(c.line, c.amount / G.GRAMS_ALCOHOL_PER_DRINK) for c in contrib]
    daily = G.ALCOHOL_DRINKS_PER_DAY[sex]
    source = G.ADA_2026 if has_t2d else G.ACC_AHA_2025
    check = _limit_check("alcohol", "Alcohol", "drinks", drinks, contrib, missing,
                         daily, profile.meal_share, source)
    if drinks > 0:
        check.notes.append("Counted before cooking; simmering removes some alcohol, "
                           "not all of it.")
        if has_ht:
            check.notes.append("For blood pressure, less alcohol is better; none is preferred.")
        if has_t2d and profile.takes_insulin:
            check.notes.append(G.INSULIN_ALCOHOL_NOTE)
    return check


# ------------------------------------------------------------------ budget ---

def check_budget(ingredients: list[Ingredient], servings: float,
                 profile: Profile) -> BudgetCheck:
    costs, missing = [], []
    for ing in ingredients:
        if ing.grams is None or ing.food_code is None:
            continue
        price = profile.price_overrides_minor_per_100g.get(ing.food_code,
                                                           ing.price_minor_per_100g)
        if price is None:
            missing.append(ing.line)
            continue
        costs.append(Contributor(ing.line, ing.grams * price / 100 / servings))
    costs.sort(key=lambda c: -c.amount)
    total = sum(c.amount for c in costs)
    cost = round(total)
    dollars = f"${total / 100:,.2f}"
    top = [Contributor(c.line, round(c.amount)) for c in costs[:3]]
    budget = (None if profile.budget_minor_per_meal is None
              else round(profile.budget_minor_per_meal * profile.snack_fraction))

    if budget is None:
        status = "info"
        message = f"{'At least ' if missing else 'About '}{dollars} per serving."
    elif total > budget:
        status = "over"
        message = (f"About {dollars} per serving, over your ${budget / 100:,.2f} budget. "
                   f"The most expensive ingredients are listed below.")
    elif missing:
        status = "incomplete"
        message = (f"At least {dollars} per serving; {len(missing)} ingredient(s) have no "
                   f"price estimate, so it may be more than your ${budget / 100:,.2f} budget.")
    else:
        status = "fits"
        message = f"About {dollars} per serving fits your ${budget / 100:,.2f} budget."
    message += " Prices are estimates from USDA and BLS national averages."
    return BudgetCheck(profile.currency, cost if costs or not missing else None, budget,
                       status, message, top, missing)


# -------------------------------------------------------------------- diet ---

def _custom(word: str) -> Requirement:
    return Requirement(f"No {word}", frozenset())


def _word_in(word: str, text: str) -> bool:
    pattern = r"\b" + re.escape(word.lower()).replace(r"\ ", r"\s+") + r"(?:e?s)?\b"
    return bool(re.search(pattern, text.lower()))


def check_diet(ingredients: list[Ingredient], profile: Profile) -> list[DietCheck]:
    requirements: list[tuple[str, Requirement]] = (
        [(name, DIETS[name]) for name in sorted(profile.diets)]
        + [(name, ALLERGENS[name]) for name in sorted(profile.allergens)]
        + [(f"custom:{w}", _custom(w)) for w in profile.custom_exclusions if w.strip()]
    )
    matched = [i for i in ingredients if i.food_code is not None]
    unmatched = [i.line for i in ingredients if i.food_code is None]
    results = []
    for name, req in requirements:
        conflicts, to_check = [], []
        for ing in matched:
            if name.startswith("custom:"):
                word = name.split(":", 1)[1].strip()
                if _word_in(word, f"{ing.line} {ing.description or ''}"):
                    conflicts.append(Conflict(ing.line, f"contains {word}"))
                continue
            hit = ing.tags & req.excludes
            if hit:
                conflicts.append(Conflict(ing.line, "contains " + ", ".join(sorted(hit))))
            elif not profile.buys_certified:
                reasons = [req.check[t] for t in sorted(ing.tags) if t in req.check]
                if reasons:
                    to_check.append(Conflict(ing.line, reasons[0]))
        if name == "kosher":
            meat = [i.line for i in matched if i.tags & KOSHER_MEAT]
            dairy = [i.line for i in matched if "dairy" in i.tags]
            if meat and dairy:
                conflicts.append(Conflict(f"{meat[0]} + {dairy[0]}",
                                          "combines meat or poultry with dairy"))
        # Custom words can also be checked on lines that weren't matched.
        if name.startswith("custom:"):
            word = name.split(":", 1)[1].strip()
            conflicts += [Conflict(line, f"contains {word}") for line in unmatched
                          if _word_in(word, line)]

        if conflicts and name in ALLERGENS:
            status, message = "doesnt_fit", "Contains an allergen you avoid."
        elif conflicts:
            status, message = "doesnt_fit", f"Has ingredients that don't fit {req.label.lower()}."
        elif unmatched and not name.startswith("custom:"):
            status = "incomplete"
            message = (f"No conflicts found, but {len(unmatched)} ingredient(s) couldn't be "
                       f"identified, so they weren't checked.")
        elif to_check:
            status, message = "check", "Some ingredients need a certification check."
        else:
            status, message = "fits", f"Fits {req.label.lower()} as far as the data shows."
        results.append(DietCheck(req.label, status, message, conflicts, to_check,
                                 req.cant_know))
    return results


# ------------------------------------------------------------------- recipe --

def check_recipe(ingredients: list[Ingredient], servings: float,
                 profile: Profile) -> RecipeCheck:
    if servings <= 0:
        raise ValueError("servings must be positive")
    nutrient_checks = check_nutrients(ingredients, servings, profile)
    budget = check_budget(ingredients, servings, profile)
    diet = check_diet(ingredients, profile)
    not_counted = [
        NotCounted(i.line, "couldn't identify the food" if i.food_code is None
                   else (i.warnings[0] if i.warnings else "couldn't work out the amount"))
        for i in ingredients if i.food_code is None or i.grams is None
    ]

    statuses = [c.status for c in nutrient_checks] + [budget.status] + [d.status for d in diet]
    if any(s in ("over", "doesnt_fit") for s in statuses):
        fits, summary = False, "This recipe doesn't fit your plan as written."
    elif any(s in ("incomplete", "check") for s in statuses) or not_counted:
        fits, summary = None, "Nothing is over so far, but some things need a check."
    else:
        fits, summary = True, "This recipe fits your plan."

    notes = [G.ESTIMATE_NOTE]
    if profile.allergens:
        notes.append(G.LABEL_REMINDER)
    return RecipeCheck(servings, fits, summary, nutrient_checks, budget, diet, not_counted,
                       notes)
