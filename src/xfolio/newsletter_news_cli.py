"""T03 수동 진단. 기본 무통신, 유료 요약은 명시 옵션/가격/예산 DB가 필요하다."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.exc import SQLAlchemyError

from xfolio.newsletter_news import NewsError, collect, summarize
from xfolio.newsletter_news_store import NewsletterNewsStore


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    finnhub_api_key: SecretStr
    openai_api_key: SecretStr | None = None


def execute(args):
    if not args.run:
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "network_requests": 0,
                    "database_writes": 0,
                    "providers": ["Finnhub", "BLS", "BEA", "Board"],
                    "maximum_selected": 3,
                    "summary_enabled": args.summarize,
                    "can_send": False,
                }
            )
        )
        return
    db = None
    try:
        settings = Settings(_env_file=args.env_file)
        now = datetime.now(UTC)
        as_of = args.as_of or now
        if as_of.utcoffset() is None or as_of > now:
            raise NewsError("invalid_as_of")
        if args.save or args.summarize:
            url = os.environ.get("XFOLIO_API_DATABASE_URL", "")
            if not url:
                raise NewsError("explicit_api_database_url_required")
            db = NewsletterNewsStore.from_url(url)
        summary, model_client = None, None
        if args.summarize:
            if not args.limits_file or not settings.openai_api_key:
                raise NewsError("summary_limits_and_key_required")
            from openai import OpenAI

            from xfolio.news_generation import OpenAIGenerationClient
            from xfolio.news_workflow import GenerationLimits, SQLWorkflowStore

            limits = GenerationLimits.model_validate_json(
                Path(args.limits_file).read_text(encoding="utf-8")
            )
            if limits.prices_valid_until <= now:
                raise NewsError("prices_expired")
            model_client = OpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                base_url="https://api.openai.com/v1",
                timeout=30,
                max_retries=0,
            )
            adapter = OpenAIGenerationClient(model_client)
            usage = SQLWorkflowStore(db.engine)
            summary = lambda item: summarize(
                item, client=adapter, store=usage, limits=limits, now=datetime.now(UTC)
            )
        try:
            seen = db.seen_keys(recipient_scope="self", now=now) if db else ()
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                result = collect(
                    client,
                    api_key=settings.finnhub_api_key.get_secret_value(),
                    as_of=as_of,
                    seen_keys=seen,
                    last_success=args.last_success,
                    summary=summary,
                )
            if args.save:
                db.save_result(result, now=datetime.now(UTC))
            print(json.dumps(result.report(), ensure_ascii=False, indent=2))
            if result.status != "complete":
                raise SystemExit(1)
        finally:
            if model_client:
                model_client.close()
    except (NewsError, ValueError, OSError, SQLAlchemyError) as exc:
        code = (
            str(exc)
            if isinstance(exc, NewsError)
            else "configuration_or_database_error"
        )
        print(json.dumps({"status": "failed", "reason": code, "can_send": False}))
        raise SystemExit(1) from None
    finally:
        if db:
            db.engine.dispose()
