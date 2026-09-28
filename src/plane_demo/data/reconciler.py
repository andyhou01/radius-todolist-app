import logging
import time

import psycopg
from kubernetes.client.exceptions import ApiException
from urllib3.exceptions import HTTPError

from plane_demo.data import llm_gateway
from plane_demo.shared.db import connect
from plane_demo.shared.kube import ConfigMaps, ConfigurationInvalid, ConfigurationMissing
from plane_demo.shared.models import AppliedConfiguration, ReconcileResult
from plane_demo.shared.settings import Settings

logger = logging.getLogger(__name__)


def report(settings: Settings, desired: AppliedConfiguration, success: bool):
    with connect(settings.control_dsn, settings.timeout_seconds) as connection:
        connection.execute(
            "SELECT control.report_data(%s,%s,%s,%s,%s)",
            (
                desired.tenant_id,
                desired.onboarding_id,
                desired.version,
                "config_applied" if success else "config_apply_failed",
                None if success else "config_write_failed",
            ),
        )


def run_once(settings: Settings, *, config_maps=None) -> ReconcileResult:
    result = ReconcileResult()
    try:
        with connect(settings.control_dsn, settings.timeout_seconds) as connection:
            rows = connection.execute(
                "SELECT tenant_id,onboarding_id,message,version FROM control.tenant_config "
                "WHERE pair_id=%s ORDER BY tenant_id",
                (settings.pair_id,),
            ).fetchall()
    except psycopg.Error as error:
        logger.warning("control_poll_failed sqlstate=%s", error.sqlstate or "unavailable")
        result.failed += 1
        return result
    maps = config_maps if config_maps is not None else ConfigMaps(settings)
    applied_configurations = []
    for row in rows:
        result.examined += 1
        desired = AppliedConfiguration(**row)
        try:
            applied = maps.apply(desired)
            # A second poller may have already applied a newer desired version.
            if applied.version > desired.version:
                applied_configurations.append(applied)
                continue
            if applied != desired:
                raise ConfigurationInvalid
        except (ApiException, HTTPError, ConfigurationInvalid, ConfigurationMissing, OSError):
            logger.warning("config_write_failed")
            result.failed += 1
            try:
                report(settings, desired, False)
            except psycopg.Error as error:
                logger.warning("data_report_failed sqlstate=%s", error.sqlstate or "unavailable")
            previous = last_applied(maps, desired.tenant_id)
            if previous is not None:
                applied_configurations.append(previous)
            continue
        applied_configurations.append(applied)
        try:
            report(settings, applied, True)
            result.succeeded += 1
        except psycopg.Error as error:
            logger.warning("data_report_failed sqlstate=%s", error.sqlstate or "unavailable")
            result.failed += 1
    if settings.llm_backend_host and not publish_llm_gateway(
        settings, maps, applied_configurations
    ):
        result.failed += 1
    return result


def last_applied(maps, tenant_id: str) -> AppliedConfiguration | None:
    """Keep a tenant's previously applied gateway route when a newer write fails."""
    try:
        return maps.read(tenant_id)
    except (ApiException, HTTPError, ConfigurationInvalid, ConfigurationMissing, OSError):
        return None


def publish_llm_gateway(settings: Settings, maps, applied: list[AppliedConfiguration]) -> bool:
    document = llm_gateway.render(
        applied,
        backend_host=settings.llm_backend_host,
        models={"small": settings.llm_small_model, "large": settings.llm_large_model},
        requests_per_minute=settings.llm_requests_per_minute,
        tokens_per_minute=settings.llm_tokens_per_minute,
        otlp_host=settings.llm_otlp_host,
    )
    try:
        changed = maps.write_document(
            llm_gateway.CONFIG_MAP, {llm_gateway.CONFIG_KEY: document}, "agentgateway"
        )
    except (ApiException, HTTPError, ConfigurationInvalid, OSError):
        logger.warning("llm_gateway_config_failed")
        return False
    if changed:
        logger.info("llm_gateway_config_applied routes=%d", len(applied))
    return True


def main() -> None:
    settings = Settings.from_env("data_reconciler")
    maps = ConfigMaps(settings)
    logging.basicConfig(level=logging.INFO)
    while True:
        result = run_once(settings, config_maps=maps)
        logger.info(
            "data_poll examined=%d succeeded=%d failed=%d",
            result.examined,
            result.succeeded,
            result.failed,
        )
        time.sleep(settings.poll_interval)


if __name__ == "__main__":
    main()
