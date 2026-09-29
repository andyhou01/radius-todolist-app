"""Upstream reconcilers consuming the event stream: meter, perf, and audit.

Each reconciler is its own Redis consumer group, so every group sees every event.
A metrics bridge publishes agentgateway's Prometheus metrics into the same stream.
"""

import json
import os
import re
import threading
import time
import urllib.request
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import redis
from events import STREAM, publish

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
METRICS_URL = os.environ.get("AGW_METRICS_URL", "http://agentgateway:15020/metrics")
state = {
    "meter": {"requests": defaultdict(int), "denied": defaultdict(int), "tokens": {}},
    "perf": {"request_duration_seconds": {}},
    "audit": [],
}
lock = threading.Lock()


def meter(kind, data):
    if kind == "audit":
        state["meter"]["requests"][f"{data['tenant']}/{data['target']}"] += 1
    elif kind in ("policy", "guardrail") and data.get("decision") != "allow":
        state["meter"]["denied"][f"{data['tenant']}/{kind}"] += 1
    elif kind == "metrics":
        state["meter"]["tokens"] = data.get("tokens", {})


def perf(kind, data):
    if kind == "metrics":
        state["perf"]["request_duration_seconds"] = data.get("duration", {})


def audit(kind, data):
    if kind in ("audit", "policy", "guardrail"):
        state["audit"] = ([{"kind": kind, **data}] + state["audit"])[:50]


def consume(group, handler):
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    while True:
        try:
            try:
                client.xgroup_create(STREAM, group, id="0", mkstream=True)
            except redis.ResponseError:
                pass  # group already exists
            while True:
                batches = client.xreadgroup(group, group, {STREAM: ">"}, count=100, block=2000)
                for _, entries in batches or []:
                    for entry_id, fields in entries:
                        with lock:
                            handler(fields["kind"], json.loads(fields["data"]))
                        client.xack(STREAM, group, entry_id)
        except redis.ConnectionError as error:
            # Redis may start after this process; keep the consumer alive and retry.
            print(f"{group}: {error}", flush=True)
            time.sleep(2)


SAMPLE = re.compile(r"^(?P<name>[a-zA-Z_:][\w:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>\S+)")


def metrics_bridge():
    while True:
        tokens, duration = {}, {}
        try:
            text = urllib.request.urlopen(METRICS_URL, timeout=3).read().decode()
            for line in text.splitlines():
                match = SAMPLE.match(line)
                if not match:
                    continue
                name, labels, value = match["name"], match["labels"] or "", float(match["value"])
                if "token_usage" in name and name.endswith("_sum"):
                    tokens[labels] = value
                elif "request_duration" in name and name.endswith(("_sum", "_count")):
                    duration[f"{name}{{{labels}}}"] = value
            if tokens or duration:
                publish("metrics", {"tokens": tokens, "duration": duration})
        except OSError as error:
            print(f"metrics bridge: {error}", flush=True)
        time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with lock:
            body = json.dumps(state, indent=2, default=dict).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    for name, fn in (("meter", meter), ("perf", perf), ("audit", audit)):
        threading.Thread(target=consume, args=(name, fn), daemon=True).start()
    threading.Thread(target=metrics_bridge, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 9200), Handler).serve_forever()
