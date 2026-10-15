# Hearten

Meals that fit your health, your budget, and your table.

Hearten checks recipes against published guidelines for hypertension and type 2 diabetes, estimates cost per serving, and respects dietary requirements such as vegetarian, halal, kosher, gluten-free and common allergies.

Educational only; not medical advice. Personal targets come from your care team.

**Status:** in development (version 1: recipe checker).

---

## Local development

You need Python 3.12+ and a Postgres database. The simplest option is a free [Neon](https://neon.tech) database: create a project, then copy its connection string.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

# Point the app at your database: copy .env.example to .env in the repo root
# and paste your connection string into DATABASE_URL.

alembic upgrade head             # create the tables
pytest                           # run the tests
uvicorn app.main:app --reload    # http://127.0.0.1:8000/health
```

Prefer a local database? `docker compose up -d db` starts one, and the `.env.example` comment shows the matching URL.

## Project layout

```text
backend/
  app/           FastAPI app, settings, database models
  migrations/    Alembic database migrations
  app/ingredients/  recipe line parsing, food matching, gram conversion
  app/rules/     guidelines, profile, dietary requirements, recipe check engine
  app/catalog.py loads foods from Postgres and resolves recipe lines
  scripts/       data download, import, tagging, matching evaluation
  data/eval/     labeled recipe lines for the matching evaluation
  tests/         pytest suite (runs in CI against a real Postgres)
docker-compose.yml   optional local Postgres
.github/workflows/   CI: lint, migrations up/down/up, tests
```

## Data sources

Food, nutrient, price and added-sugar data come from USDA FoodData Central (FNDDS 2021-2023 and SR Legacy), USDA ERS Purchase to Plate, and USDA FPED. Inflation adjustment uses the BLS Consumer Price Index for food at home.

- **FNDDS** describes foods as eaten ("Chicken breast, baked") and carries prices and added sugars.
- **SR Legacy** supplies plain recipe ingredients that FNDDS lacks (flour, salt, spices, dry pasta, raw chicken, broth). SR doesn't report added sugars, so a rule fills them in: sweeteners count fully, plain produce/meat/grains count zero, and anything unclear is left unknown. Prices carry over from FNDDS foods made of essentially that one ingredient.
- **BLS average retail prices** (monthly, via FRED) price staples the survey data misses, such as flour, uncooked rice, dry pasta, eggs, milk and dried beans (`backend/data/bls_staples.csv`). Cooking oil, salt and spices have no public average price, so they show as "price unavailable" unless the user enters their own.

## Ingredient matching

Each recipe line is parsed (amount, unit, food words), matched to a USDA food, and converted to grams using USDA portion weights. The matcher is lexical and explainable: word coverage weighted by rarity, the food's head word, penalties for dishes, brands and food parts, a preference for raw forms, and a tie-breaker from how often USDA's own survey recipes use each ingredient.

It's measured on 97 hand-labeled recipe lines (`backend/data/eval/ingredient_lines.csv`), split into a dev set used while tuning and a held-out test set scored only after tuning:

| Split | Lines | Correct food | Grams within 25% |
|---|---|---|---|
| dev | 60 | 100% | 98% |
| test (held out, first run) | 37 | 92% | 95% |

Adding FNDDS foods to the same search (so prepared foods like salsa or hummus match) scored 89% on its first test run; that run exposed a parsing bug in names with parentheses, which was fixed, bringing it back to 92%. Because that fix was prompted by the test set, the next evaluation should use freshly labeled lines.

```bash
python -m scripts.eval_matching     # needs the downloaded USDA data
```

## Recipe check (rules engine)

`app/rules/` compares one recipe with a person's plan. Every limit cites its source in `app/rules/guidelines.py`:

- **Limits** (sodium, added sugars for diabetes, alcohol, an optional carb target): each serving is compared with one meal's share of the daily limit (daily limit ÷ meals per day, or a half, quarter or eighth of that for a snack). Over-limit results name the ingredients behind them.
- **Goals** (potassium) show progress with a kidney and medication caution; **ratios** (fiber per 1,000 kcal) are judged on the recipe itself.
- **Budget**: cost per serving from USDA average prices, with the user's own prices taking precedence.
- **Diet**: requirements and the 9 major allergens become exclusions over food tags; halal and kosher add "check certification" notes, and kosher also catches meat with dairy.
- Missing data is never counted as zero: results say "incomplete" instead.

Try it against your database from the command line, or through the API:

```bash
python -m scripts.check_recipe data/examples/chicken_stir_fry.txt --servings 4 \
    --condition hypertension --budget 4.00 --diet halal
```

## API

`POST /check` takes the pasted recipe, the number of servings and a profile, and returns each line's matched food and grams plus the full check. Nothing sent is stored. With the dev server running (`uvicorn app.main:app --reload`), interactive docs are at http://127.0.0.1:8000/docs.

```json
{
  "recipe": "1 lb chicken breast\n2 tbsp soy sauce\n1 cup long-grain white rice",
  "servings": 4,
  "profile": {"conditions": ["hypertension"], "diets": ["halal"], "budget_minor_per_meal": 400}
}
```
