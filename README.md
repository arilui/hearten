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
  tests/         pytest suite (runs in CI against a real Postgres)
docker-compose.yml   optional local Postgres
.github/workflows/   CI: lint, migrations up/down/up, tests
```

## Data sources

Food, nutrient, price and added-sugar data come from USDA FoodData Central (FNDDS, Foundation Foods), USDA ERS Purchase to Plate, and USDA FPED. Inflation adjustment uses the BLS Consumer Price Index for food at home.
