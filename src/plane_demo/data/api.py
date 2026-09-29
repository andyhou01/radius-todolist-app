import logging
import re
from typing import Annotated

import httpx
from fastapi import Depends, Header, HTTPException
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError
from urllib3.exceptions import HTTPError

from plane_demo.data import llm_gateway
from plane_demo.data.llm_gateway import ChatMessage
from plane_demo.shared.auth import authenticate
from plane_demo.shared.http import base_app
from plane_demo.shared.kube import ConfigMaps, ConfigurationInvalid, ConfigurationMissing
from plane_demo.shared.models import TenantId
from plane_demo.shared.settings import Settings, redis_client

logger = logging.getLogger(__name__)


class TenantChatRequest(BaseModel):
    """Tenants choose a tier and send messages; the gateway maps the tier to a model."""

    model_config = ConfigDict(extra="forbid")
    tier: llm_gateway.Tier = "small"
    messages: Annotated[list[ChatMessage], Field(min_length=1, max_length=32)]


TRACEPARENT = re.compile(r"[0-9a-f]{2}-(?!0{32})[0-9a-f]{32}-(?!0{16})[0-9a-f]{16}-[0-9a-f]{2}")


def create_app(settings: Settings, *, config_maps=None, counter_store=None, llm_client=None):
    app = base_app(settings)
    authenticated = [Depends(authenticate(settings.demo_key))]
    maps = config_maps if config_maps is not None else ConfigMaps(settings)
    counters = counter_store if counter_store is not None else redis_client(settings)
    llm = llm_client
    if llm is None and settings.llm_gateway_url:
        llm = httpx.Client(
            base_url=settings.llm_gateway_url, timeout=settings.timeout_seconds, trust_env=False
        )

    def applied_configuration(tenant_id: str):
        try:
            return maps.read(tenant_id)
        except ConfigurationMissing:
            raise HTTPException(404, "tenant_config_not_applied") from None
        except ConfigurationInvalid:
            raise HTTPException(503, "tenant_config_invalid") from None
        except (ApiException, HTTPError, OSError):
            logger.warning("local_configuration_unavailable")
            raise HTTPException(503, "local_configuration_unavailable") from None

    def serve(tenant_id: str, increment: bool):
        applied = applied_configuration(tenant_id)
        key = f"plane-demo:{applied.onboarding_id}:{tenant_id}:counter"
        try:
            value = counters.incr(key) if increment else counters.get(key)
            counter = int(value) if value is not None else 0
        except (RedisError, ValueError, TypeError):
            logger.warning("local_counter_unavailable")
            raise HTTPException(503, "local_counter_unavailable") from None
        return {
            "tenant_id": tenant_id,
            "onboarding_id": applied.onboarding_id,
            "message": applied.message,
            "applied_version": applied.version,
            "counter": counter,
        }

    @app.get("/tenants/{tenant_id}", dependencies=authenticated)
    def read_tenant(tenant_id: TenantId):
        return serve(tenant_id, False)

    @app.post("/tenants/{tenant_id}/counter", dependencies=authenticated)
    def increment_counter(tenant_id: TenantId):
        return serve(tenant_id, True)

    @app.get("/tenants/{tenant_id}/llm/usage", dependencies=authenticated)
    def llm_usage(tenant_id: TenantId):
        """Requests metered by the PostRouting filter for the current onboarding."""
        applied = applied_configuration(tenant_id)
        key = llm_gateway.usage_key(applied.onboarding_id, tenant_id)
        try:
            counts = counters.hgetall(key) or {}
            requests = {tier: int(counts.get(tier, 0)) for tier in llm_gateway.TIERS}
        except (RedisError, ValueError, TypeError):
            logger.warning("local_usage_unavailable")
            raise HTTPException(503, "local_usage_unavailable") from None
        return {
            "tenant_id": tenant_id,
            "onboarding_id": applied.onboarding_id,
            "requests": requests,
        }

    @app.post("/tenants/{tenant_id}/chat/completions", dependencies=authenticated)
    def chat_completion(
        tenant_id: TenantId,
        request: TenantChatRequest,
        traceparent: Annotated[str | None, Header()] = None,
    ):
        if llm is None:
            raise HTTPException(404, "llm_gateway_disabled")
        applied = applied_configuration(tenant_id)
        # Tenant identity comes from the authenticated path, never from caller headers.
        headers = {
            llm_gateway.TENANT_HEADER: tenant_id,
            llm_gateway.ONBOARDING_HEADER: str(applied.onboarding_id),
            llm_gateway.TIER_HEADER: request.tier,
            # Placement is the plan input for the PreRouting policy filter.
            llm_gateway.PAIR_HEADER: settings.pair_id,
        }
        # Continue a caller's W3C trace so gateway spans join it; drop malformed values.
        if traceparent and TRACEPARENT.fullmatch(traceparent):
            headers["traceparent"] = traceparent
        try:
            response = llm.post(
                llm_gateway.CHAT_PATH,
                json={"messages": [message.model_dump() for message in request.messages]},
                headers=headers,
            )
        except httpx.HTTPError:
            logger.warning("llm_gateway_unavailable")
            raise HTTPException(503, "llm_gateway_unavailable") from None
        if response.status_code == 429:
            raise HTTPException(429, "llm_rate_limited")
        if response.status_code == 404:
            # The gateway has not loaded this tenant's current onboarding route yet.
            raise HTTPException(503, "llm_route_not_ready")
        if response.status_code == 400 and guardrail_rejected(response):
            raise HTTPException(400, "llm_guardrail_rejected")
        if response.status_code == 403 and error_code(response) == llm_gateway.POLICY_CODE:
            raise HTTPException(403, llm_gateway.POLICY_CODE)
        if response.status_code != 200:
            logger.warning("llm_gateway_rejected status=%d", response.status_code)
            raise HTTPException(502, "llm_gateway_rejected")
        try:
            completion = response.json()
            choice = completion["choices"][0]
            return {
                "tenant_id": tenant_id,
                "onboarding_id": applied.onboarding_id,
                "tier": request.tier,
                "model": str(completion["model"]),
                "message": {
                    "role": "assistant",
                    "content": str(choice["message"]["content"]),
                },
                "usage": {
                    key: int(completion["usage"][key])
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                },
            }
        except (ValueError, KeyError, IndexError, TypeError):
            logger.warning("llm_gateway_invalid_response")
            raise HTTPException(502, "llm_gateway_invalid_response") from None

    return app


def error_code(response: httpx.Response) -> str | None:
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


def guardrail_rejected(response: httpx.Response) -> bool:
    return error_code(response) == llm_gateway.GUARDRAIL_CODE


def main() -> None:
    import uvicorn

    settings = Settings.from_env("data_api")
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.listen_port, access_log=False)


if __name__ == "__main__":
    main()
