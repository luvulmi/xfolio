"""서버 환경/단가·live실행 조립을 외부 요청 없이 검사."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from xfolio.domestic.kis import KisSettings
from xfolio.jobs.collection import CollectionError, LiveCollectionSettings
from xfolio.jobs.worker import MorningWorker, main
from xfolio.news_workflow import GenerationLimits


def config(now=None, **changes):
    now = now or datetime.now(UTC)
    return replace(
        LiveCollectionSettings(
            kis=KisSettings("test-key", "test-secret"),
            finnhub_key="test-finnhub",
            openai_key="test-openai",
            limits=GenerationLimits(
                input_krw_per_million=Decimal(10),
                output_krw_per_million=Decimal(20),
                price_basis="test-prices",
                prices_valid_until=now + timedelta(days=1),
            ),
        ),
        **changes,
    )


def test_config_keys_and_prices_fail_closed_without_secret_values():
    now = datetime.now(UTC)
    cases = [
        config(finnhub_key=""),
        config(openai_key=""),
        config(monthly_limit=Decimal("NaN")),
        config(monthly_limit=Decimal(50001)),
        config(recipient_scope="self,other"),
        replace(
            config(),
            limits=config().limits.model_copy(update={"prices_valid_until": now}),
        ),
    ]
    for value in cases:
        with pytest.raises(CollectionError) as exc:
            value.validate(now)
        assert "test-key" not in str(exc.value) and "test-openai" not in str(exc.value)
    assert "test-openai" not in repr(config())


def test_env_requires_explicit_limits_and_does_not_read_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FINNHUB_API_KEY=do-not-read\n", encoding="utf-8")
    monkeypatch.delenv("XFOLIO_GENERATION_LIMITS_FILE", raising=False)
    with pytest.raises(CollectionError, match="generation_limits_file_required"):
        LiveCollectionSettings.from_env()
    path = tmp_path / "limits.json"
    path.write_text(config().limits.model_dump_json(), encoding="utf-8")
    for name, value in {
        "XFOLIO_GENERATION_LIMITS_FILE": str(path),
        "KIS_APP_KEY": "test-key",
        "KIS_APP_SECRET": "test-secret",
        "FINNHUB_API_KEY": "test-finnhub",
        "OPENAI_API_KEY": "test-openai",
    }.items():
        monkeypatch.setenv(name, value)
    result = LiveCollectionSettings.from_env()
    assert result.finnhub_key == "test-finnhub"


def test_preparation_service_is_used_before_generic_collection():
    class Preparation:
        def prepare(self):
            return {"status": "ready", "edition_id": "test"}

    worker = MorningWorker(
        calendar=None,
        collect_inputs=None,
        newsletter_store=None,
        outbox_store=None,
        transport=None,
        preparation=Preparation(),
    )
    assert worker.prepare() == {"status": "ready", "edition_id": "test"}


@pytest.mark.parametrize(
    "arguments", [["--live", "--phase", "prepare"], ["--live", "--schedule"]]
)
def test_live_collection_is_assembled_with_server_resources(
    monkeypatch, capsys, arguments
):
    import xfolio.jobs.worker as worker_module
    from xfolio.jobs import collection

    calls = []
    preparation = type(
        "Preparation",
        (),
        {"prepare": lambda self: {"status": "ready"}, "calendar": lambda *_: True},
    )()

    class Resources:
        def __init__(self, engine, **kwargs):
            calls.append("resources")
            self.preparation = preparation

        def close(self):
            calls.append("resources_closed")

    db = type(
        "DB",
        (),
        {
            "engine": type(
                "Engine", (), {"dispose": lambda _: calls.append("db_closed")}
            )()
        },
    )()
    monkeypatch.setattr(worker_module.NewsletterNewsStore, "from_url", lambda _: db)
    from xfolio.newsletter_store import NewsletterStore

    monkeypatch.setattr(NewsletterStore, "__init__", lambda *_: None)
    monkeypatch.setattr(
        worker_module, "TelegramOutboxStore", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        worker_module,
        "TelegramTransport",
        lambda **_: type(
            "Transport", (), {"close": lambda _: calls.append("transport_closed")}
        )(),
    )
    monkeypatch.setattr(collection.LiveCollectionSettings, "from_env", lambda: config())
    monkeypatch.setattr(collection, "LiveCollectionResources", Resources)

    def scheduler(worker):
        assert worker.preparation is preparation
        return type("Scheduler", (), {"start": lambda _: calls.append("scheduler")})()

    monkeypatch.setattr(worker_module, "create_scheduler", scheduler)
    monkeypatch.setenv("XFOLIO_WORKER_LIVE_ACCEPTED", "true")
    monkeypatch.setenv("XFOLIO_WORKER_DATABASE_URL", "test-only")
    assert main(arguments) == 0
    if "--schedule" in arguments:
        assert "scheduler" in calls
    else:
        assert json.loads(capsys.readouterr().out)["status"] == "ready"
    assert set(calls) >= {
        "resources",
        "resources_closed",
        "db_closed",
        "transport_closed",
    }
