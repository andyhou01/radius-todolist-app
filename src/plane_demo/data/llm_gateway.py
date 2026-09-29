"""Render the data plane's agentgateway configuration from applied tenant ConfigMaps.

The data reconciler owns this configuration: it is derived only from the tenant
configuration that the reconciler has already applied locally, so the gateway
keeps serving its last configuration while the parent control plane is down.
"""

import json
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from plane_demo.shared.models import AppliedConfiguration, Message

CONFIG_MAP = "agentgateway-config"
CONFIG_KEY = "config.yaml"
GATEWAY_PORT = 4000
CHAT_PATH = "/v1/chat/completions"
TENANT_HEADER = "x-plane-demo-tenant"
ONBOARDING_HEADER = "x-plane-demo-onboarding"
TIER_HEADER = "x-plane-demo-tier"
PAIR_HEADER = "x-plane-demo-pair"
# Issued by the PreRouting filter and verified by the PostRouting filter.
PASSPORT_HEADER = "x-plane-demo-passport"
TIERS = ("small", "large")
GUARDRAIL_CODE = "guardrail_rejected"
POLICY_CODE = "llm_policy_denied"


def usage_key(onboarding_id: object, tenant_id: str) -> str:
    """Redis hash of requests per tier, metered by the PostRouting filter."""
    return f"plane-demo:{onboarding_id}:{tenant_id}:llm-requests"


Tier = Literal["small", "large"]

# Deterministic request guards: synthetic PII, credentials, and prompt-injection phrases.
REQUEST_GUARD_RULES = [
    {"builtin": "ssn"},
    {"builtin": "creditCard"},
    {"pattern": r"(?i)(password|api[_-]?key|secret|token)\s*[=:]\s*\S+"},
    {"pattern": r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions"},
    {"pattern": r"(?i)(reveal|print|show)\s+(your\s+)?(system|hidden)\s+prompt"},
]
RESPONSE_MASK_RULES = [{"builtin": "email"}, {"builtin": "phoneNumber"}, {"builtin": "creditCard"}]
# Credentials must never reach the gateway; the data API strips them before forwarding.
FORBIDDEN_HEADERS = ("x-demo-key", "authorization", "cookie")


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: Message


def _route(
    item: AppliedConfiguration,
    tier: str,
    *,
    backend_host: str,
    model: str,
    requests_per_minute: int,
    tokens_per_minute: int,
    filters_host: str,
) -> dict:
    name = f"tenant-{item.tenant_id}-{tier}"
    postrouting = {"extAuthz": _ext_authz(filters_host, "/postrouting")} if filters_host else {}
    return {
        "name": name,
        "matches": [
            {
                "path": {"pathPrefix": CHAT_PATH},
                "headers": [
                    {"name": TENANT_HEADER, "value": {"exact": item.tenant_id}},
                    {"name": ONBOARDING_HEADER, "value": {"exact": str(item.onboarding_id)}},
                    {"name": TIER_HEADER, "value": {"exact": tier}},
                ],
            }
        ],
        "policies": {
            **postrouting,
            "authorization": {
                "rules": [
                    {"require": 'request.method == "POST"'},
                    *({"deny": f'"{header}" in request.headers'} for header in FORBIDDEN_HEADERS),
                ]
            },
            "localRateLimit": [
                {
                    "maxTokens": requests_per_minute,
                    "tokensPerFill": requests_per_minute,
                    "fillInterval": "60s",
                    "type": "requests",
                },
                {
                    "maxTokens": tokens_per_minute,
                    "tokensPerFill": tokens_per_minute,
                    "fillInterval": "60s",
                    "type": "tokens",
                },
            ],
        },
        "backends": [
            {
                "ai": {
                    "name": name,
                    "hostOverride": backend_host,
                    "provider": {"openAI": {"model": model}},
                },
                "policies": {
                    "ai": {
                        "promptGuard": {
                            "request": [
                                {
                                    "regex": {"action": "reject", "rules": REQUEST_GUARD_RULES},
                                    "rejection": {
                                        "status": 400,
                                        "headers": {"set": {"content-type": "application/json"}},
                                        "body": json.dumps({"error": {"code": GUARDRAIL_CODE}}),
                                    },
                                }
                            ],
                            "response": [
                                {"regex": {"action": "mask", "rules": RESPONSE_MASK_RULES}}
                            ],
                        }
                    }
                },
            }
        ],
    }


def _ext_authz(filters_host: str, path: str) -> dict:
    """Call the data plane filters service; any filter failure denies the request."""
    identity = [TENANT_HEADER, ONBOARDING_HEADER, TIER_HEADER]
    if path == "/prerouting":
        return {
            "host": filters_host,
            "failureMode": "deny",
            "protocol": {
                "http": {"path": f'"{path}"', "includeResponseHeaders": [PASSPORT_HEADER]}
            },
            "includeRequestHeaders": [*identity, PAIR_HEADER],
        }
    return {
        "host": filters_host,
        "failureMode": "deny",
        "protocol": {"http": {"path": f'"{path}"'}},
        "includeRequestHeaders": [*identity, PASSPORT_HEADER],
    }


def _tracing(otlp_host: str) -> dict:
    return {
        "tracing": {
            "host": otlp_host,
            "randomSampling": True,
            "resources": {"service.name": '"plane-demo-agentgateway"'},
            "attributes": {
                "plane_demo.tenant": f'request.headers["{TENANT_HEADER}"]',
                "plane_demo.onboarding": f'request.headers["{ONBOARDING_HEADER}"]',
                "plane_demo.tier": f'request.headers["{TIER_HEADER}"]',
            },
        }
    }


def render(
    applied: Iterable[AppliedConfiguration],
    *,
    backend_host: str,
    models: dict[str, str],
    requests_per_minute: int,
    tokens_per_minute: int,
    otlp_host: str = "",
    filters_host: str = "",
) -> str:
    """Return deterministic agentgateway YAML (JSON is valid YAML), one route per tenant tier.

    With filters_host, PreRouting (gateway) and PostRouting (route) extAuthz policies call
    the data plane filters service before route selection and before the model backend.
    """
    if set(models) != set(TIERS):
        raise ValueError("a model is required for every tier")
    routes = [
        _route(
            item,
            tier,
            backend_host=backend_host,
            model=models[tier],
            requests_per_minute=requests_per_minute,
            tokens_per_minute=tokens_per_minute,
            filters_host=filters_host,
        )
        for item in sorted(applied, key=lambda config: config.tenant_id)
        for tier in TIERS
    ]
    gateway: dict = {"port": GATEWAY_PORT}
    if filters_host:
        gateway["extAuthz"] = _ext_authz(filters_host, "/prerouting")
    document = {"gateways": {"default": gateway}, "routes": routes}
    if otlp_host:
        document["frontendPolicies"] = _tracing(otlp_host)
    return json.dumps(document, indent=2, sort_keys=True) + "\n"
