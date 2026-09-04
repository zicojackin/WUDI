from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .binance import BinanceClient

from .agents import (
    AgentReport,
    bear_agent,
    bull_agent,
    derivatives_agent,
    market_data_agent,
    news_agent,
    risk_manager,
    sentiment_agent,
    technical_agent,
)
from .config import Settings
from .indicators import technical_snapshot
from .market_sources import fetch_fear_greed, fetch_news, news_as_dicts
from .okx import OkxClient
from .portfolio import llm_decision, rule_based_decision
from .report import write_report


def run_analysis(
    inst_id: str,
    bar: str = "4H",
    limit: int = 200,
    swap: bool = False,
    account: bool = False,
    include_news: bool = True,
    include_sentiment: bool = True,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    spot_client = BinanceClient(
        base_url=settings.binance_base_url,
        timeout=settings.binance_timeout,
    )

    ticker = spot_client.ticker(inst_id)
    candles = spot_client.candles(inst_id, bar=bar, limit=limit)
    book = spot_client.orderbook(inst_id)

    okx_client = OkxClient(
        base_url=settings.okx_base_url,
        timeout=settings.okx_timeout,
        config_path=settings.okx_config_path,
    )

    funding_rate = None
    open_interest = None
    if swap:
        swap_inst_id = inst_id if inst_id.endswith("-SWAP") else f"{inst_id}-SWAP"
        funding_rate = okx_client.funding_rate(swap_inst_id)
        open_interest = okx_client.open_interest(swap_inst_id)

    balance = okx_client.balance() if account else None
    positions = okx_client.positions(inst_id) if account else None

    snapshot = technical_snapshot(candles)
    fear_greed = fetch_fear_greed() if include_sentiment else None
    news_items = fetch_news() if include_news else []

    market_report = market_data_agent(inst_id, ticker, candles, book)
    technical_report = technical_agent(snapshot)
    derivatives_report = derivatives_agent(funding_rate, open_interest, book)
    sentiment_report = sentiment_agent(fear_greed)
    news_report = news_agent(news_items)
    bull_report = bull_agent(technical_report, derivatives_report, sentiment_report, news_report)
    bear_report = bear_agent(technical_report, derivatives_report, sentiment_report, news_report)
    risk_report = risk_manager(snapshot.get("price"), snapshot, balance, positions)

    reports = [
        market_report,
        technical_report,
        derivatives_report,
        sentiment_report,
        news_report,
        bull_report,
        bear_report,
        risk_report,
    ]

    price = snapshot.get("price")
    if settings.llm_api_key:
        decision = llm_decision(
            reports,
            price,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    else:
        decision = rule_based_decision(reports, price)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state: dict[str, Any] = {
        "bar": bar,
        "limit": limit,
        "spot_provider": "binance",
        "swap": swap,
        "account": account,
        "price": price,
        "snapshot": snapshot,
        "funding_rate": funding_rate,
        "open_interest": open_interest,
        "fear_greed": fear_greed,
        "news": news_as_dicts(news_items),
    }
    markdown_path, json_path = write_report(
        reports_dir=settings.reports_dir,
        inst_id=inst_id,
        generated_at=generated_at,
        reports=reports,
        decision=decision,
        state=state,
    )
    return {
        "instrument": inst_id,
        "generated_at": generated_at,
        "price": price,
        "decision": decision.to_dict(),
        "reports": [report.to_dict() for report in reports],
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "state": state,
    }
