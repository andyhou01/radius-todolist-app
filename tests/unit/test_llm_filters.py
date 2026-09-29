"""PreRouting / PostRouting extAuthz filters and their agentgateway wiring."""

import json
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from plane_demo.data import api as data_api
from plane_demo.data import filters, llm_gateway
from plane_demo.shared.models import AppliedConfiguration
from plane_demo.shared.settings import Settings

KEY = "unit-test-demo-key-with-32-characters"
MODELS = {"small": "demo-small", "large": "demo-large"}


def applied(tenant="alpha"):
    return AppliedConfiguration(tenant_id=tenant, onboarding_id=uuid4(), message="m", version=1)


def identity_headers(config, tier="small", pair="shared"):
    return {
        llm_gateway.TENANT_HEADER: config.tenant_id,
        llm_gateway.ONBOARDING_HEADER: str(config.onboarding_id),
        llm_gateway.TIER_HEADER: tier,
        llm_gateway.PAIR_HEADER: pair,
    }


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def filters_client(store=None, clock=None):
    passports = filters.Passports(secret=b"k" * 32, clock=clock or Clock())
    store = store if store is not None else Mock()
    return TestClient(filters.create_app(Settings(), store=store, passports=passports)), store


def test_render_wires_prerouting_on_gateway_and_postrouting_on_every_route():
    document = json.loads(
        llm_gateway.render(
            [applied()],
            backend_host="mock-llm:8088",
            models=MODELS,
            requests_per_minute=5,
            tokens_per_minute=100,
            filters_host="llm-filters:8088",
        )
    )
    pre = document["gateways"]["default"]["extAuthz"]
    assert pre["host"] == "llm-filters:8088" and pre["failureMode"] == "deny"
    assert pre["protocol"]["http"]["path"] == '"/prerouting"'
    assert pre["protocol"]["http"]["includeResponseHeaders"] == [llm_gateway.PASSPORT_HEADER]
    assert llm_gateway.PAIR_HEADER in pre["includeRequestHeaders"]
    for route in document["routes"]:
        post = route["policies"]["extAuthz"]
        assert post["failureMode"] == "deny"
        assert post["protocol"]["http"]["path"] == '"/postrouting"'
        assert llm_gateway.PASSPORT_HEADER in post["includeRequestHeaders"]
        # Existing built-in guardrails stay on the backend.
        assert route["backends"][0]["policies"]["ai"]["promptGuard"]["request"]


def test_render_without_filters_host_keeps_previous_config():
    document = json.loads(
        llm_gateway.render(
            [applied()],
            backend_host="h:1",
            models=MODELS,
            requests_per_minute=5,
            tokens_per_minute=9,
        )
    )
    assert document["gateways"] == {"default": {"port": 4000}}
    assert all("extAuthz" not in route["policies"] for route in document["routes"])


def test_prerouting_issues_passport_for_allowed_tier_and_records_decision():
    config = applied()
    client, store = filters_client()
    response = client.post("/prerouting", headers=identity_headers(config))
    assert response.status_code == 200
    assert response.headers[llm_gateway.PASSPORT_HEADER]
    event = store.xadd.call_args.args[1]
    assert event["kind"] == "policy"
    assert json.loads(event["data"])["decision"] == "allow"


@pytest.mark.parametrize(("pair", "status"), [("shared", 403), ("isolated-1", 200)])
def test_prerouting_policy_limits_large_tier_to_dedicated_pairs(pair, status):
    client, store = filters_client()
    response = client.post("/prerouting", headers=identity_headers(applied(), "large", pair))
    assert response.status_code == status
    if status == 403:
        assert response.json()["error"]["code"] == llm_gateway.POLICY_CODE
        assert llm_gateway.PASSPORT_HEADER not in response.headers
        assert json.loads(store.xadd.call_args.args[1]["data"])["decision"] == "deny"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {llm_gateway.TENANT_HEADER: "Bad Tenant"},
        {llm_gateway.ONBOARDING_HEADER: "not-a-uuid"},
        {llm_gateway.TIER_HEADER: "huge"},
        {llm_gateway.PAIR_HEADER: "../x"},
    ],
)
def test_prerouting_rejects_missing_or_malformed_identity(headers):
    client, _ = filters_client()
    base = identity_headers(applied())
    response = client.post("/prerouting", headers={**base, **headers} if headers else {})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "llm_passport_denied"


def test_prerouting_decision_survives_event_stream_outage():
    store = Mock()
    store.xadd.side_effect = RedisError()
    client, _ = filters_client(store)
    assert client.post("/prerouting", headers=identity_headers(applied())).status_code == 200


def test_postrouting_verifies_passport_then_meters_and_audits():
    config = applied()
    client, store = filters_client()
    headers = identity_headers(config)
    passport = client.post("/prerouting", headers=headers).headers[llm_gateway.PASSPORT_HEADER]
    response = client.post(
        "/postrouting", headers={**headers, llm_gateway.PASSPORT_HEADER: passport}
    )
    assert response.status_code == 200
    store.hincrby.assert_called_once_with(
        llm_gateway.usage_key(config.onboarding_id, "alpha"), "small", 1
    )
    assert store.xadd.call_args.args[1]["kind"] == "audit"


def test_postrouting_rejects_forged_expired_or_mismatched_passports():
    config = applied()
    clock = Clock()
    client, store = filters_client(clock=clock)
    headers = identity_headers(config)
    passport = client.post("/prerouting", headers=headers).headers[llm_gateway.PASSPORT_HEADER]

    def post(extra):
        return client.post("/postrouting", headers={**headers, **extra}).status_code

    assert post({llm_gateway.PASSPORT_HEADER: "forged.signature"}) == 403
    assert post({llm_gateway.PASSPORT_HEADER: passport, llm_gateway.TIER_HEADER: "large"}) == 403
    clock.now += filters.PASSPORT_TTL_SECONDS + 1
    assert post({llm_gateway.PASSPORT_HEADER: passport}) == 403
    store.hincrby.assert_not_called()


def test_postrouting_fails_closed_when_usage_cannot_be_metered():
    config = applied()
    store = Mock()
    store.hincrby.side_effect = RedisError()
    client, _ = filters_client(store)
    headers = identity_headers(config)
    passport = client.post("/prerouting", headers=headers).headers[llm_gateway.PASSPORT_HEADER]
    response = client.post(
        "/postrouting", headers={**headers, llm_gateway.PASSPORT_HEADER: passport}
    )
    assert response.status_code == 503


def data_client(handler, maps, counters):
    llm = httpx.Client(base_url="http://agentgateway:4000", transport=httpx.MockTransport(handler))
    app = data_api.create_app(
        Settings(demo_key=KEY, pair_id="shared"),
        config_maps=maps,
        counter_store=counters,
        llm_client=llm,
    )
    return TestClient(app)


def test_data_api_forwards_pair_and_maps_policy_denial():
    maps = Mock()
    maps.read.return_value = applied()
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(403, json={"error": {"code": llm_gateway.POLICY_CODE}})

    response = data_client(handler, maps, Mock()).post(
        "/tenants/alpha/chat/completions",
        json={"tier": "large", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Demo-Key": KEY},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == llm_gateway.POLICY_CODE
    assert seen[0].headers[llm_gateway.PAIR_HEADER] == "shared"


def test_data_api_reports_metered_usage_for_current_onboarding():
    config = applied()
    maps = Mock()
    maps.read.return_value = config
    counters = Mock()
    counters.hgetall.return_value = {"small": "3"}
    client = data_client(lambda _request: httpx.Response(200), maps, counters)
    assert client.get("/tenants/alpha/llm/usage").status_code == 401
    response = client.get("/tenants/alpha/llm/usage", headers={"X-Demo-Key": KEY})
    assert response.status_code == 200
    assert response.json()["requests"] == {"small": 3, "large": 0}
    counters.hgetall.assert_called_once_with(llm_gateway.usage_key(config.onboarding_id, "alpha"))


def test_reconciler_settings_accept_only_host_port_filters(monkeypatch):
    for name, value in {
        "CONTROL_DSN": "postgresql://x",
        "PAIR_ID": "shared",
        "PROJECT_ID": "radplanes",
        "KUBE_NAMESPACE": "data",
        "LLM_FILTERS_HOST": "llm-filters:8088",
    }.items():
        monkeypatch.setenv(name, value)
    assert Settings.from_env("data_reconciler").llm_filters_host == "llm-filters:8088"
    monkeypatch.setenv("LLM_FILTERS_HOST", "http://llm-filters:8088")
    with pytest.raises(ValueError):
        Settings.from_env("data_reconciler")
