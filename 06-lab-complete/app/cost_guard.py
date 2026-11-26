"""Global daily token spending, stored in Redis with a UTC day boundary."""
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from app.config import settings
from app.redis_client import r

PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_RECORD = r.register_script("""
local total = redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
redis.call('EXPIREAT', KEYS[1], ARGV[2])
return total
""")

def _daily_key():
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return f"day14:cost:{now:%Y-%m-%d}", int(midnight.timestamp())

def check_budget() -> None:
    key, _ = _daily_key()
    spent = float(r.get(key) or 0)
    if spent >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exceeded")

def record_cost(input_tokens: int, output_tokens: int) -> float:
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    key, expires_at = _daily_key()
    _RECORD(keys=[key], args=[cost, expires_at])
    return cost
