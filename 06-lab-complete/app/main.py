"""Production agent: auth, Redis limits, JSON logs and graceful lifecycle."""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask

class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        data.update(getattr(record, "fields", {}))
        return json.dumps(data, ensure_ascii=False)

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("day14.agent")
logger.handlers = [handler]
logger.setLevel(settings.log_level.upper())
logger.propagate = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", extra={"fields": {"environment": settings.environment}})
    yield
    # Uvicorn owns SIGTERM handling and waits for requests before cleanup.
    r.close()
    logger.info("shutdown_complete")

app = FastAPI(title="Production AI Agent", lifespan=lifespan)

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=200)

@app.middleware("http")
async def log_request(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    logger.info("request", extra={"fields": {
        "method": request.method,
        "route": route.path if route else "unmatched",
        "status": response.status_code,
        "ms": round((time.perf_counter() - started) * 1000, 2),
    }})
    return response

@app.exception_handler(RedisError)
async def redis_error(request: Request, exc: RedisError):
    logger.warning("redis_unavailable")
    return JSONResponse(status_code=503, content={"detail": "Storage temporarily unavailable"})

@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.error("request_failed", extra={"fields": {"error_type": type(exc).__name__}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/ready")
def ready():
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Storage not ready")
    return {"ready": True}

@app.post("/ask")
def ask(body: AskRequest, key: str = Depends(verify_api_key)):
    check_rate_limit(key)
    check_budget()
    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost = record_cost(input_tokens, output_tokens)
    return {"question": body.question, "answer": answer,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost}}
