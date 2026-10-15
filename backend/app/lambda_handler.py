"""AWS Lambda entry point: API Gateway events in, the FastAPI app handles them."""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
