import json
from contextlib import contextmanager
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from kubernetes.client.exceptions import ApiException

from plane_demo.data import api as data_api
from plane_demo.data import llm_gateway, mock_llm
from plane_demo.data import reconciler as data_reconciler
from plane_demo.shared.kube import ConfigMaps, ConfigurationInvalid
from plane_demo.shared.models import AppliedConfiguration
from plane_demo.shared.settings import Settings

KEY = "unit-test-demo-key-with-32-characters"
HEADERS = {"X-Demo-Key": KEY}
MESSAGES = {"messages": [{"role": "user", "content": "hello"}]}


def applied(tenant="alpha", version=1):
    return AppliedConfiguration(
        tenant_id=tenant, onboarding_id=uuid4(), message="m", version=version
    )


MODELS = {"small": "demo-small", "large": "demo-large"}


def render(items, **overrides):
    options = {
        "backend_host": "mock-llm:8088",
        "models": MODELS,
        "requests_per_minute": 5,
        "tokens_per_minute": 100,
    }
    return json.loads(llm_gateway.render(items, **{**options, **overrides}))


def test_render_is_deterministic_and_routes_by_tenant_onboarding_and_tier():
    beta, alpha = applied("beta"), applied("alpha")
    options = dict(backend_host="h:1", models=MODELS, requests_per_minute=5, tokens_per_minute=9)
    assert llm_gateway.render([beta, alpha], **options) == llm_gateway.render(
        [alpha, beta], **options
    )
    document = render([beta, alpha])
    assert document["gateways"] == {"default": {"port": 4000}}
    assert "frontendPolicies" not in document
    assert [route["name"] for route in document["routes"]] == [
        "tenant-alpha-small",
        "tenant-alpha-large",
        "tenant-beta-small",
        "tenant-beta-large",
    ]
    small, large = document["routes"][:2]
    assert small["matches"][0]["headers"] == [
        {"name": llm_gateway.TENANT_HEADER, "value": {"exact": "alpha"}},
        {"name": llm_gateway.ONBOARDING_HEADER, "value": {"exact": str(alpha.onboarding_id)}},
        {"name": llm_gateway.TIER_HEADER, "value": {"exact": "small"}},
    ]
    assert small["backends"][0]["ai"]["provider"] == {"openAI": {"model": "demo-small"}}
    assert large["backends"][0]["ai"]["provider"] == {"openAI": {"model": "demo-large"}}
    assert small["backends"][0]["ai"]["hostOverride"] == "mock-llm:8088"


def test_render_applies_policy_limits_and_guardrails_to_every_route():
    for route in render([applied()])["routes"]:
        rules = route["policies"]["authorization"]["rules"]
        assert {"require": 'request.method == "POST"'} in rules
        for header in ("x-demo-key", "authorization", "cookie"):
            assert {"deny": f'"{header}" in request.headers'} in rules
        limits = {
            limit["type"]: limit["maxTokens"] for limit in route["policies"]["localRateLimit"]
        }
        assert limits == {"requests": 5, "tokens": 100}
        guard = route["backends"][0]["policies"]["ai"]["promptGuard"]
        request = guard["request"][0]
        assert request["regex"]["action"] == "reject"
        assert {"builtin": "ssn"} in request["regex"]["rules"]
        assert json.loads(request["rejection"]["body"]) == {
            "error": {"code": llm_gateway.GUARDRAIL_CODE}
        }
        assert guard["response"][0]["regex"]["action"] == "mask"


def test_render_adds_tenant_attributed_tracing_only_when_configured():
    tracing = render([applied()], otlp_host="otel-collector:4317")["frontendPolicies"]["tracing"]
    assert tracing["host"] == "otel-collector:4317"
    assert tracing["randomSampling"] is True
    assert tracing["attributes"]["plane_demo.tenant"] == (
        f'request.headers["{llm_gateway.TENANT_HEADER}"]'
    )


def test_render_requires_a_model_for_every_tier():
    with pytest.raises(ValueError):
        render([], models={"small": "demo-small"})


def test_render_without_tenants_is_a_valid_empty_route_table():
    assert render([])["routes"] == []


def config_maps(existing=None):
    maps = ConfigMaps.__new__(ConfigMaps)
    maps.settings = Settings(project_id="radplanes", pair_id="default", namespace="data")
    maps.api = Mock()
    if existing is None:
        maps.api.read_namespaced_config_map.side_effect = ApiException(status=404)
    else:
        maps.api.read_namespaced_config_map.return_value = existing
    return maps


def existing_map(labels, data):
    return Mock(metadata=Mock(labels=labels, resource_version="41"), data=data)


LABELS = {
    "plane-demo/project": "radplanes",
    "plane-demo/pair": "default",
    "plane-demo/component": "agentgateway",
}


def test_write_document_creates_updates_and_skips_unchanged():
    maps = config_maps()
    assert maps.write_document("agentgateway-config", {"k": "v"}, "agentgateway")
    body = maps.api.create_namespaced_config_map.call_args.kwargs["body"]
    assert body.metadata.labels == LABELS and body.data == {"k": "v"}

    maps = config_maps(existing_map(LABELS, {"k": "v"}))
    assert not maps.write_document("agentgateway-config", {"k": "v"}, "agentgateway")
    maps.api.patch_namespaced_config_map.assert_not_called()

    maps = config_maps(existing_map(LABELS, {"k": "old"}))
    assert maps.write_document("agentgateway-config", {"k": "v"}, "agentgateway")
    body = maps.api.patch_namespaced_config_map.call_args.kwargs["body"]
    assert body.metadata.resource_version == "41"


def test_write_document_refuses_to_adopt_unowned_configmap():
    maps = config_maps(existing_map({"plane-demo/project": "other"}, {}))
    with pytest.raises(ConfigurationInvalid):
        maps.write_document("agentgateway-config", {"k": "v"}, "agentgateway")
    maps.api.patch_namespaced_config_map.assert_not_called()


def reconcile(monkeypatch, rows, maps, **settings):
    @contextmanager
    def connect(*_args):
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = rows
        yield connection

    monkeypatch.setattr(data_reconciler, "connect", connect)
    monkeypatch.setattr(data_reconciler, "report", Mock())
    return data_reconciler.run_once(Settings(**settings), config_maps=maps)


def test_reconciler_publishes_gateway_config_only_when_enabled(monkeypatch):
    desired = applied("alpha")
    maps = Mock()
    maps.apply.return_value = desired
    result = reconcile(monkeypatch, [desired.model_dump()], maps)
    assert result.succeeded == 1
    maps.write_document.assert_not_called()

    result = reconcile(monkeypatch, [desired.model_dump()], maps, llm_backend_host="mock-llm:8088")
    assert (result.succeeded, result.failed) == (1, 0)
    name, data, component = maps.write_document.call_args.args
    assert (name, component) == ("agentgateway-config", "agentgateway")
    assert str(desired.onboarding_id) in data["config.yaml"]


def test_reconciler_keeps_previous_route_when_tenant_write_fails(monkeypatch):
    previous, desired = applied("alpha", 1), applied("alpha", 2)
    maps = Mock()
    maps.apply.side_effect = ApiException(status=500)
    maps.read.return_value = previous
    result = reconcile(monkeypatch, [desired.model_dump()], maps, llm_backend_host="m:8088")
    assert result.failed == 1
    config = maps.write_document.call_args.args[1]["config.yaml"]
    assert str(previous.onboarding_id) in config
    assert str(desired.onboarding_id) not in config


def test_reconciler_counts_gateway_publication_failure(monkeypatch):
    desired = applied("alpha")
    maps = Mock()
    maps.apply.return_value = desired
    maps.write_document.side_effect = ConfigurationInvalid()
    result = reconcile(monkeypatch, [desired.model_dump()], maps, llm_backend_host="m:8088")
    assert (result.succeeded, result.failed) == (1, 1)


def chat_client(handler, maps):
    transport = httpx.MockTransport(handler)
    llm = httpx.Client(base_url="http://agentgateway:4000", transport=transport)
    app = data_api.create_app(
        Settings(demo_key=KEY), config_maps=maps, counter_store=Mock(), llm_client=llm
    )
    return TestClient(app)


def completion(model="demo-small"):
    return {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_chat_is_disabled_without_gateway_url():
    client = TestClient(
        data_api.create_app(Settings(demo_key=KEY), config_maps=Mock(), counter_store=Mock())
    )
    assert client.post("/tenants/alpha/chat/completions", json=MESSAGES).status_code == 401
    response = client.post("/tenants/alpha/chat/completions", json=MESSAGES, headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["detail"] == "llm_gateway_disabled"


def test_chat_forwards_authenticated_tenant_identity_only():
    config = applied("alpha")
    maps = Mock()
    maps.read.return_value = config
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=completion())

    client = chat_client(handler, maps)
    trace = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    response = client.post(
        "/tenants/alpha/chat/completions",
        json={**MESSAGES, "tier": "large"},
        headers={**HEADERS, llm_gateway.TENANT_HEADER: "beta", "traceparent": trace},
    )
    assert response.status_code == 200
    assert response.json()["tier"] == "large"
    assert response.json()["message"] == {"role": "assistant", "content": "hi"}
    assert response.json()["usage"]["total_tokens"] == 2
    request = seen[0]
    assert request.url.path == llm_gateway.CHAT_PATH
    assert request.headers[llm_gateway.TENANT_HEADER] == "alpha"
    assert request.headers[llm_gateway.ONBOARDING_HEADER] == str(config.onboarding_id)
    assert request.headers[llm_gateway.TIER_HEADER] == "large"
    assert request.headers["traceparent"] == trace
    assert "x-demo-key" not in request.headers
    assert json.loads(request.content) == MESSAGES


@pytest.mark.parametrize(
    "trace", ["bogus", "00-" + "0" * 32 + "-00f067aa0ba902b7-01", "00-ABC-00f067aa0ba902b7-01"]
)
def test_chat_drops_malformed_traceparent(trace):
    maps = Mock()
    maps.read.return_value = applied()
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=completion())

    response = chat_client(handler, maps).post(
        "/tenants/alpha/chat/completions", json=MESSAGES, headers={**HEADERS, "traceparent": trace}
    )
    assert response.status_code == 200
    assert "traceparent" not in seen[0].headers
    assert seen[0].headers[llm_gateway.TIER_HEADER] == "small"


def test_chat_rejects_unknown_tier():
    maps = Mock()
    maps.read.return_value = applied()
    client = chat_client(lambda _request: httpx.Response(200, json=completion()), maps)
    response = client.post(
        "/tenants/alpha/chat/completions", json={**MESSAGES, "tier": "huge"}, headers=HEADERS
    )
    assert response.status_code == 422


def test_chat_rejects_caller_selected_model():
    maps = Mock()
    maps.read.return_value = applied()
    client = chat_client(lambda _request: httpx.Response(200, json=completion()), maps)
    response = client.post(
        "/tenants/alpha/chat/completions", json={**MESSAGES, "model": "big"}, headers=HEADERS
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("upstream", "status", "detail"),
    [
        (httpx.Response(429), 429, "llm_rate_limited"),
        (httpx.Response(404), 503, "llm_route_not_ready"),
        (
            httpx.Response(400, json={"error": {"code": "guardrail_rejected"}}),
            400,
            "llm_guardrail_rejected",
        ),
        (httpx.Response(400, text="bad"), 502, "llm_gateway_rejected"),
        (httpx.Response(403), 502, "llm_gateway_rejected"),
        (httpx.Response(500), 502, "llm_gateway_rejected"),
        (httpx.Response(200, text="not json"), 502, "llm_gateway_invalid_response"),
        (httpx.Response(200, json={"choices": []}), 502, "llm_gateway_invalid_response"),
    ],
)
def test_chat_maps_gateway_failures(upstream, status, detail):
    maps = Mock()
    maps.read.return_value = applied()
    client = chat_client(lambda _request: upstream, maps)
    response = client.post("/tenants/alpha/chat/completions", json=MESSAGES, headers=HEADERS)
    assert (response.status_code, response.json()["detail"]) == (status, detail)


def test_chat_gateway_transport_failure_is_unavailable():
    maps = Mock()
    maps.read.return_value = applied()

    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    response = chat_client(handler, maps).post(
        "/tenants/alpha/chat/completions", json=MESSAGES, headers=HEADERS
    )
    assert (response.status_code, response.json()["detail"]) == (503, "llm_gateway_unavailable")


def test_mock_llm_returns_openai_shaped_completion():
    client = TestClient(mock_llm.create_app(Settings()))
    response = client.post("/v1/chat/completions", json={"model": "demo-small", **MESSAGES})
    body = response.json()
    assert body["model"] == "demo-small"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["usage"]["total_tokens"] > 0
    assert client.post("/v1/chat/completions", json=MESSAGES).status_code == 422


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("LLM_GATEWAY_URL", "https://agentgateway:4000"),
        ("LLM_GATEWAY_URL", "http://agentgateway:4000/path"),
        ("LLM_SMALL_MODEL", "bad model"),
        ("LLM_LARGE_MODEL", ""),
        ("LLM_REQUESTS_PER_MINUTE", "0"),
        ("LLM_TOKENS_PER_MINUTE", "0"),
    ],
)
def test_llm_settings_are_validated(monkeypatch, variable, value):
    monkeypatch.setenv("DEMO_KEY", KEY)
    monkeypatch.setenv("PAIR_ID", "default")
    monkeypatch.setenv("PROJECT_ID", "radplanes")
    monkeypatch.setenv("KUBE_NAMESPACE", "data")
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError):
        Settings.from_env("data_api")


def test_llm_settings_are_scoped_to_their_role(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://agentgateway:4000")
    monkeypatch.setenv("LLM_BACKEND_HOST", "mock-llm:8088")
    monkeypatch.setenv("LLM_OTLP_HOST", "otel-collector:4317")
    settings = Settings.from_env("mock_llm")
    assert (settings.llm_gateway_url, settings.llm_backend_host, settings.llm_otlp_host) == (
        "",
        "",
        "",
    )


def test_invalid_otlp_host_is_rejected_for_reconciler(monkeypatch):
    monkeypatch.setenv("CONTROL_DSN", "postgresql://unused")
    monkeypatch.setenv("PAIR_ID", "default")
    monkeypatch.setenv("PROJECT_ID", "radplanes")
    monkeypatch.setenv("KUBE_NAMESPACE", "data")
    monkeypatch.setenv("LLM_OTLP_HOST", "http://collector:4317")
    with pytest.raises(ValueError):
        Settings.from_env("data_reconciler")
