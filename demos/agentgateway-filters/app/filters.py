"""PreRouting and PostRouting filters, served as agentgateway HTTP extAuthz endpoints.

/prerouting  (gateway policy, before route selection)
    Passport Control -> Guardrails -> Policy -> Router
    Returns 200 plus x-passport / x-tier / x-route-target headers, or 403 with a reason.
/postrouting (route policy, after route selection)
    Verifies the passport and publishes an audit event for the upstream reconcilers.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from events import publish

SECRET = os.environ["PASSPORT_SECRET"].encode()

# Tenant catalogue: tier, allowed route targets, and per-request token ceiling.
TENANTS = {
    "acme": {"tier": "gold", "targets": {"azure", "vendor"}, "max_tokens": 4096},
    "globex": {"tier": "free", "targets": {"azure"}, "max_tokens": 256},
}
VENDOR_MODELS = {"vendor-large"}
GUARDRAILS = [
    ("pii.ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("secret.credential", re.compile(r"(?i)(password|api[_-]?key|secret|token)\s*[=:]\s*\S+")),
    (
        "prompt.injection",
        re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions"),
    ),
]
PASSPORT_TTL = 60


def sign(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True).encode()).decode()
    mac = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def verify(passport: str) -> dict | None:
    body, _, mac = passport.partition(".")
    expected = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    if not mac or not hmac.compare_digest(mac, expected):
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(body))
    except ValueError:
        return None
    if not isinstance(claims, dict) or time.time() - claims.get("iat", 0) > PASSPORT_TTL:
        return None
    return claims


def prerouting(headers, body: bytes) -> tuple[int, dict, dict]:
    request_id = headers.get("x-request-id") or str(uuid.uuid4())
    tenant = headers.get("x-tenant", "")
    profile = TENANTS.get(tenant)
    # Passport Control: the gateway already validated the API key and supplied its tenant.
    if profile is None:
        return 403, {}, {"error": "unknown_tenant"}
    try:
        payload = json.loads(body or b"{}")
        max_tokens = int(payload.get("max_tokens") or 0)
    except (ValueError, TypeError, AttributeError):
        return 400, {}, {"error": "invalid_request"}
    model = str(payload.get("model", ""))
    base = {"request_id": request_id, "tenant": tenant, "tier": profile["tier"], "model": model}

    # Guardrails
    messages = payload.get("messages")
    messages = messages if isinstance(messages, list) else []
    text = " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
    for rule, pattern in GUARDRAILS:
        if pattern.search(text):
            publish("guardrail", {**base, "rule": rule, "decision": "reject"})
            return 403, {}, {"error": "guardrail_rejected", "rule": rule}

    # Router: choose the upstream family from the requested model.
    target = "vendor" if model in VENDOR_MODELS else "azure"

    # Policy
    reason = None
    if target not in profile["targets"]:
        reason = f"tier {profile['tier']} cannot use {target} models"
    elif max_tokens > profile["max_tokens"]:
        reason = f"max_tokens exceeds {profile['max_tokens']}"
    if reason:
        publish("policy", {**base, "target": target, "decision": "deny", "reason": reason})
        return 403, {}, {"error": "policy_denied", "reason": reason}
    publish("policy", {**base, "target": target, "decision": "allow"})

    passport = sign({**base, "target": target, "iat": int(time.time())})
    return (
        200,
        {
            "x-passport": passport,
            "x-tenant": tenant,
            "x-tier": profile["tier"],
            "x-route-target": target,
            "x-request-id": request_id,
        },
        {},
    )


def postrouting(headers) -> tuple[int, dict, dict]:
    claims = verify(headers.get("x-passport", ""))
    if claims is None or claims.get("target") != headers.get("x-route-target"):
        return 403, {}, {"error": "invalid_passport"}
    publish(
        "audit",
        {
            **{k: claims[k] for k in ("request_id", "tenant", "tier", "model", "target")},
            "phase": "postrouting",
            "at": time.time(),
        },
    )
    return 200, {}, {}


class Handler(BaseHTTPRequestHandler):
    def _handle(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        headers = {k.lower(): v for k, v in self.headers.items()}
        if self.path.startswith("/prerouting"):
            status, extra, payload = prerouting(headers, body)
        elif self.path.startswith("/postrouting"):
            status, extra, payload = postrouting(headers)
        else:
            status, extra, payload = 404, {}, {"error": "not_found"}
        data = json.dumps(payload).encode() if payload else b""
        self.send_response(status)
        for key, value in extra.items():
            self.send_header(key, value)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = _handle

    def log_message(self, fmt, *args):
        print(f"filters {self.command} {self.path} {args[1] if len(args) > 1 else ''}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9001), Handler).serve_forever()
