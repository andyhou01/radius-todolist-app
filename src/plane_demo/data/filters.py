"""agentgateway extAuthz filters for the data plane.

/prerouting  runs on the gateway before route selection (PreRouting phase):
    Passport Control -> Policy. Allowed requests receive a signed passport.
/postrouting runs on the selected tenant route before the model (PostRouting phase):
    verify the passport, then meter usage and append an audit event in local Redis.

Request guardrails and response masking stay in agentgateway's own promptGuard policies.
The filters only read gateway-supplied headers and local Redis; they never call Control.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from redis.exceptions import RedisError

from plane_demo.data import llm_gateway
from plane_demo.shared.http import base_app
from plane_demo.shared.settings import TENANT_PATTERN, Settings, redis_client

logger = logging.getLogger(__name__)

PASSPORT_TTL_SECONDS = 60
AUDIT_STREAM = "plane-demo:llm:audit"
AUDIT_LENGTH = 1000
# Placement decides the plan: the shared pair serves the small tier only.
PLAN_TIERS = {"shared": {"small"}, "dedicated": set(llm_gateway.TIERS)}
PAIR_PATTERN = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"


def plan_for(pair_id: str) -> str:
    return "shared" if pair_id == "shared" else "dedicated"


def identity(headers) -> dict | None:
    tenant = headers.get(llm_gateway.TENANT_HEADER, "")
    onboarding = headers.get(llm_gateway.ONBOARDING_HEADER, "")
    tier = headers.get(llm_gateway.TIER_HEADER, "")
    if not re.fullmatch(TENANT_PATTERN, tenant) or tier not in llm_gateway.TIERS:
        return None
    try:
        onboarding = str(UUID(onboarding))
    except ValueError:
        return None
    return {"tenant": tenant, "onboarding": onboarding, "tier": tier}


def deny(status: int, code: str, reason: str = "") -> JSONResponse:
    error = {"code": code, **({"reason": reason} if reason else {})}
    return JSONResponse({"error": error}, status_code=status)


class Passports:
    """HMAC passports shared by the two phases of one filters process."""

    def __init__(self, secret: bytes | None = None, clock=time.time):
        self.secret = secret or secrets.token_bytes(32)
        self.clock = clock

    def issue(self, claims: dict) -> str:
        body = base64.urlsafe_b64encode(
            json.dumps({**claims, "iat": int(self.clock())}, sort_keys=True).encode()
        ).decode()
        return f"{body}.{hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()}"

    def verify(self, passport: str) -> dict | None:
        body, _, mac = passport.partition(".")
        expected = hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()
        if not mac or not hmac.compare_digest(mac, expected):
            return None
        try:
            claims = json.loads(base64.urlsafe_b64decode(body))
        except ValueError:
            return None
        if not isinstance(claims, dict):
            return None
        if not 0 <= self.clock() - claims.get("iat", -1) <= PASSPORT_TTL_SECONDS:
            return None
        return claims


def create_app(settings: Settings, *, store=None, passports: Passports | None = None):
    app = base_app(settings)
    events = store if store is not None else redis_client(settings)
    signer = passports or Passports()

    def publish(kind: str, data: dict) -> None:
        fields = {"kind": kind, "data": json.dumps(data, sort_keys=True), "at": str(time.time())}
        events.xadd(AUDIT_STREAM, fields, maxlen=AUDIT_LENGTH, approximate=True)

    @app.api_route("/prerouting", methods=["GET", "POST"])
    def prerouting(request: Request):
        # Passport Control: the data API is the only caller and sets these from its
        # authenticated path and local tenant configuration.
        claims = identity(request.headers)
        pair = request.headers.get(llm_gateway.PAIR_HEADER, "")
        if claims is None or not re.fullmatch(PAIR_PATTERN, pair):
            return deny(403, "llm_passport_denied")
        plan = plan_for(pair)
        allowed = claims["tier"] in PLAN_TIERS[plan]
        reason = "" if allowed else f"{plan} plan cannot use the {claims['tier']} tier"
        try:
            publish("policy", {**claims, "plan": plan, "decision": "allow" if allowed else "deny"})
        except RedisError:
            # Policy decisions are advisory events; metering in PostRouting fails closed.
            logger.warning("llm_policy_event_failed")
        if not allowed:
            return deny(403, llm_gateway.POLICY_CODE, reason)
        passport = signer.issue({**claims, "plan": plan})
        return Response(status_code=200, headers={llm_gateway.PASSPORT_HEADER: passport})

    @app.api_route("/postrouting", methods=["GET", "POST"])
    def postrouting(request: Request):
        claims = identity(request.headers)
        passport = signer.verify(request.headers.get(llm_gateway.PASSPORT_HEADER, ""))
        if (
            claims is None
            or passport is None
            or any(passport.get(key) != value for key, value in claims.items())
        ):
            return deny(403, "llm_passport_denied")
        try:
            events.hincrby(
                llm_gateway.usage_key(claims["onboarding"], claims["tenant"]), claims["tier"], 1
            )
            publish("audit", {**claims, "plan": passport.get("plan")})
        except RedisError:
            logger.warning("llm_usage_unavailable")
            return deny(503, "llm_usage_unavailable")
        return Response(status_code=200)

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env("data_filters")
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.listen_port, access_log=False)


if __name__ == "__main__":
    main()
