from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from .indicators import orderbook_imbalance, score_technicals
from .market_sources import NewsItem


@dataclass(slots=True)
class AgentReport:
    agent: str
    title: str
    summary: str
    bullets: list[str]
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.{digits}f}{suffix}"
    return "N/A"


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def market_data_agent(
    inst_id: str,
    ticker: dict[str, Any],
    candles: Sequence[dict[str, float]],
    book: dict[str, Any],
) -> AgentReport:
    imbalance = orderbook_imbalance(book)
    last = _float(ticker.get("last")) or (candles[-1]["close"] if candles else None)
    change_24h = _float(ticker.get("priceChangePercent"))
    high_24h = _float(ticker.get("high24h"))
    low_24h = _float(ticker.get("low24h"))
    volume_24h = _float(ticker.get("volCcy24h"))
    ratio = imbalance.get("ratio")
    summary = (
        f"{inst_id} 最新价 {last}，24 小时涨跌 {change_24h}%，"
        f"盘口买卖量比 {ratio}。"
    )
    bullets = [
        f"24 小时最高/最低：{high_24h} / {low_24h}",
        f"24 小时成交额：{volume_24h}",
        f"盘口买量：{imbalance.get('bid_volume')}，卖量：{imbalance.get('ask_volume')}",
        f"最近一根 K 线收盘：{candles[-1]['close'] if candles else 'N/A'}",
    ]
    return AgentReport(
        agent="MarketDataAgent",
        title="市场数据报告",
        summary=summary,
        bullets=bullets,
        data={"ticker": ticker, "orderbook_imbalance": imbalance},
    )


def technical_agent(snapshot: dict[str, Any]) -> AgentReport:
    score, reasons = score_technicals(snapshot)
    macd_data = snapshot.get("macd", {})
    summary = (
        f"技术面综合分 {score:+d}；RSI {_fmt(snapshot.get('rsi14'), 1)}，"
        f"ATR {_fmt(snapshot.get('atr14'), 6)}，"
        f"10 期变化 {_fmt(snapshot.get('change_10'), 2, '%')}。"
    )
    bullets = [
        f"EMA20：{_fmt(snapshot.get('ema20'), 6)}",
        f"EMA50：{_fmt(snapshot.get('ema50'), 6)}",
        f"SMA200：{_fmt(snapshot.get('sma200'), 6)}",
        f"MACD/Signal：{_fmt(macd_data.get('macd'), 6)} / {_fmt(macd_data.get('signal'), 6)}",
        f"Bollinger 上/中/下轨：{_fmt(snapshot.get('bollinger20', {}).get('upper'), 6)} / "
        f"{_fmt(snapshot.get('bollinger20', {}).get('middle'), 6)} / "
        f"{_fmt(snapshot.get('bollinger20', {}).get('lower'), 6)}",
    ]
    bullets.extend(f"信号：{reason}" for reason in reasons)
    return AgentReport(
        agent="TechnicalAgent",
        title="技术面报告",
        summary=summary,
        bullets=bullets,
        data={"score": score, "signals": reasons, **snapshot},
    )


def derivatives_agent(
    funding_rate: dict[str, Any] | None,
    open_interest: dict[str, Any] | None,
    book: dict[str, Any],
) -> AgentReport:
    imbalance = orderbook_imbalance(book)
    funding = _float(funding_rate.get("fundingRate") if funding_rate else None)
    next_funding = _float(funding_rate.get("nextFundingRate") if funding_rate else None)
    oi = _float(open_interest.get("oi") if open_interest else None)
    oi_ccy = open_interest.get("oiCcy", "") if open_interest else ""
    score = 0
    if funding is not None:
        if funding > 0.0005:
            score -= 1
        elif funding < -0.0005:
            score += 1
    summary = (
        f"衍生品面：资金费率 {_fmt(funding, 6)}，下一期 {_fmt(next_funding, 6)}，"
        f"持仓量 {_fmt(oi, 2)} {oi_ccy}。"
    )
    bullets = [
        f"订单簿买卖量比：{imbalance.get('ratio')}",
        "资金费率明显为正时，多头拥挤，回落风险更高。",
        "资金费率明显为负时，空头拥挤，反弹概率相对提高。",
    ]
    if funding_rate is None:
        bullets.append("未获取到资金费率，可能不是永续合约。")
    if open_interest is None:
        bullets.append("未获取到持仓量。")
    return AgentReport(
        agent="DerivativesAgent",
        title="衍生品报告",
        summary=summary,
        bullets=bullets,
        data={
            "funding_rate": funding,
            "next_funding_rate": next_funding,
            "open_interest": oi,
            "orderbook_imbalance": imbalance,
            "score": score,
        },
    )


def sentiment_agent(fear_greed: dict[str, Any] | None) -> AgentReport:
    if not fear_greed:
        return AgentReport(
            agent="SentimentAgent",
            title="情绪报告",
            summary="未获取到 Fear & Greed Index。",
            bullets=["情绪数据缺失，置信度降低。"],
            data={"score": 0},
        )
    value = fear_greed.get("value")
    classification = fear_greed.get("classification", "Neutral")
    average = fear_greed.get("average_7d")
    score = 0
    if isinstance(value, (int, float)):
        if value <= 25:
            score = 2
        elif value <= 45:
            score = 1
        elif value >= 80:
            score = -2
        elif value >= 70:
            score = -1
    summary = (
        f"Fear & Greed Index 为 {value}，分类 {classification}，7 日均值 {_fmt(average, 1)}。"
    )
    bullets = [
        "低于 25 通常代表极度恐惧，历史上更接近逆向关注区。",
        "高于 80 通常代表极度贪婪，需要警惕拥挤交易。",
    ]
    return AgentReport(
        agent="SentimentAgent",
        title="情绪报告",
        summary=summary,
        bullets=bullets,
        data={"score": score, **fear_greed},
    )


def news_agent(items: Sequence[NewsItem]) -> AgentReport:
    if not items:
        return AgentReport(
            agent="NewsAgent",
            title="新闻报告",
            summary="未获取到新闻标题。",
            bullets=["新闻源不可用时，不应强行给出方向性结论。"],
            data={"score": 0, "items": []},
        )
    score = sum(item.score for item in items)
    summary = f"抓取到 {len(items)} 条新闻，关键词净分 {score:+d}。"
    bullets = [f"[{item.source}] {item.title}" for item in items[:8]]
    return AgentReport(
        agent="NewsAgent",
        title="新闻报告",
        summary=summary,
        bullets=bullets,
        data={"score": score, "items": [asdict(item) for item in items]},
    )


def bull_agent(
    technical: AgentReport,
    derivatives: AgentReport,
    sentiment: AgentReport,
    news: AgentReport,
) -> AgentReport:
    score = (
        technical.data.get("score", 0)
        + derivatives.data.get("score", 0)
        + sentiment.data.get("score", 0)
        + news.data.get("score", 0)
    )
    positives = list(technical.data.get("signals", []))
    if sentiment.data.get("score", 0) > 0:
        positives.append("市场情绪从低位改善")
    if news.data.get("score", 0) > 0:
        positives.append("新闻关键词偏向利好")
    if not positives:
        positives = ["尚缺乏强力的正向证据"]
    return AgentReport(
        agent="BullResearcher",
        title="多头研究员",
        summary=f"多头论据强度 {max(score, 0)}。",
        bullets=positives[:8],
        data={"score": score},
    )


def bear_agent(
    technical: AgentReport,
    derivatives: AgentReport,
    sentiment: AgentReport,
    news: AgentReport,
) -> AgentReport:
    score = -(
        technical.data.get("score", 0)
        + derivatives.data.get("score", 0)
        + sentiment.data.get("score", 0)
        + news.data.get("score", 0)
    )
    negatives: list[str] = []
    for signal in technical.data.get("signals", []):
        if any(word in signal for word in ("超买", "偏空", "低于", "跌破", "上轨", "异常")):
            negatives.append(signal)
    if sentiment.data.get("score", 0) < 0:
        negatives.append("情绪过热或贪婪，存在拥挤风险")
    if news.data.get("score", 0) < 0:
        negatives.append("新闻关键词偏向利空")
    if not negatives:
        negatives = ["尚缺乏强力的负向证据"]
    return AgentReport(
        agent="BearResearcher",
        title="空头研究员",
        summary=f"空头论据强度 {max(score, 0)}。",
        bullets=negatives[:8],
        data={"score": score},
    )


def risk_manager(
    price: float | None,
    snapshot: dict[str, Any],
    balance: list[dict[str, Any]] | None = None,
    positions: list[dict[str, Any]] | None = None,
) -> AgentReport:
    atr_value = snapshot.get("atr14")
    atr_pct = None
    stop_distance_pct = None
    stop_loss = None
    recommended_position_pct = None
    if isinstance(price, (int, float)) and isinstance(atr_value, (int, float)) and price:
        atr_pct = atr_value / price * 100
        stop_distance_pct = min(max(atr_pct * 1.5, 1.0), 10.0)
        stop_loss = price * (1 - stop_distance_pct / 100)
        risk_per_trade = 1.0
        recommended_position_pct = min(risk_per_trade / stop_distance_pct * 100, 5.0)
    bullets = [
        f"ATR 占价格比例：{_fmt(atr_pct, 2, '%')}",
        f"建议止损距离：{_fmt(stop_distance_pct, 2, '%')}",
        f"参考止损价：{_fmt(stop_loss, 6)}",
        f"单笔建议仓位：{_fmt(recommended_position_pct, 2, '%')}",
        "以上仓位基于 1% 单笔风险、1.5 倍 ATR 止损距离，并限制在 5% 以内。",
    ]
    if balance is not None:
        bullets.append(f"已读取账户余额接口，账户数据组数：{len(balance)}。")
    if positions is not None:
        bullets.append(f"当前持仓记录数：{len(positions)}。")
    return AgentReport(
        agent="RiskManager",
        title="风险管理报告",
        summary="以波动率和止损距离约束单笔风险。",
        bullets=bullets,
        data={
            "atr_pct": atr_pct,
            "stop_distance_pct": stop_distance_pct,
            "stop_loss": stop_loss,
            "recommended_position_pct": recommended_position_pct,
            "balance_present": balance is not None,
            "positions_present": positions is not None,
        },
    )
