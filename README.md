# Hearten

Meals that fit your health, your budget, and your table.

Hearten checks recipes against published guidelines for hypertension and type 2 diabetes, estimates cost per serving, and respects dietary requirements such as vegetarian, halal, kosher, gluten-free and common allergies.

Educational only; not medical advice. Personal targets come from your care team.

**Status:** in development (version 1: recipe checker).

---

## Local development

You need Python 3.12+ and Docker Desktop.

```bash
# 1. Start Postgres
docker compose up -d db

# 2. Install the backend (from the repo root)
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

# 3. Create the tables, then run the tests and the API
alembic upgrade head
pytest
uvicorn app.main:app --reload    # http://127.0.0.1:8000/health
```

Settings come from environment variables; copy `.env.example` to `.env` to change them.

## Project layout

```text
backend/
  app/           FastAPI app, settings, database models
  migrations/    Alembic database migrations
  tests/         pytest suite (runs in CI against a real Postgres)
docker-compose.yml   local Postgres
.github/workflows/   CI: lint, migrations up/down/up, tests
```

## Data sources

Food, nutrient, price and added-sugar data come from USDA FoodData Central (FNDDS, Foundation Foods), USDA ERS Purchase to Plate, and USDA FPED. Inflation adjustment uses the BLS Consumer Price Index for food at home.
