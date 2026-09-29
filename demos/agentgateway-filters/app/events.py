"""Event stream helpers backed by a Redis stream."""

import json
import os
import time

import redis

STREAM = "agw:events"
client = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)


def publish(kind: str, data: dict) -> None:
    client.xadd(STREAM, {"kind": kind, "data": json.dumps(data), "ts": str(time.time())},
                maxlen=10000, approximate=True)
