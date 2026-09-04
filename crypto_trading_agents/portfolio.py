from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

import requests

from .agents import AgentReport


@dataclass(slots=True)
class PortfolioDecision:
    action: str
    confidence: int
    summary: str
    reasons: list[str]
    risks: list[str]
    position_size_pct: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    time_horizon: str = "短线到中线"
    generated_by: str = "rule-engine"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rule_based_decision(
    reports: list[AgentReport],
    price: float | None,
) -> PortfolioDecision:
    by_agent = {report.agent: report for report in reports}
    technical_score = by_agent.get("TechnicalAgent", AgentReport("TechnicalAgent", "", "", [], {})).data.get("score", 0)
    derivatives_score = by_agent.get("DerivativesAgent", AgentReport("DerivativesAgent", "", "", [], {})).data.get("score", 0)
    sentiment_score = by_agent.get("SentimentAgent", AgentReport("SentimentAgent", "", "", [], {})).data.get("score", 0)
    news_score = by_agent.get("NewsAgent", AgentReport("NewsAgent", "", "", [], {})).data.get("score", 0)
    combined = technical_score + derivatives_score + sentiment_score + news_score

    if combined >= 4:
        action = "BUY"
        confidence = min(85, 55 + combined * 3)
        summary = "多数信号偏多，可以考虑分批建立多头敞口。"
    elif combined >= 2:
        action = "BUY"
        confidence = 60
        summary = "正向证据略占优，但还不够强，建议小额试探。"
    elif combined <= -4:
        action = "SELL"
        confidence = min(85, 55 + abs(combined) * 3)
        summary = "多数信号偏空，应降低敞口或避免新建多头。"
    elif combined <= -2:
        action = "SELL"
        confidence = 60
        summary = "负向证据略占优，建议保守处理。"
    else:
        action = "HOLD"
        confidence = 55
        summary = "多空证据互相抵消，维持观望更合适。"

    risk_report = by_agent.get("RiskManager", AgentReport("RiskManager", "", "", [], {})).data
    technical_signals = by_agent.get("TechnicalAgent", AgentReport("TechnicalAgent", "", "", [], {})).data.get("signals", [])
    reasons = list(technical_signals)[:5]
    if derivatives_score:
        reasons.append("资金费率或订单簿压力提供辅助证据。")
    if sentiment_score:
        reasons.append("Fear & Greed Index 提供情绪上下文。")
    if news_score:
        reasons.append("新闻关键词净分为决策提供辅助参考。")
    risks = [
        "加密资产波动极大，实际止损可能被跳空或插针穿越。",
        "RSS 和情绪源可能滞后或不完整。",
        "规则引擎不包含链上数据和事件驱动建模。",
    ]
    return PortfolioDecision(
        action=action,
        confidence=confidence,
        summary=summary,
        reasons=reasons,
        risks=risks,
        position_size_pct=risk_report.get("recommended_position_pct"),
        stop_loss=risk_report.get("stop_loss"),
        take_profit=price * 1.04 if isinstance(price, (int, float)) else None,
    )


def llm_decision(
    reports: list[AgentReport],
    price: float | None,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 1400,
) -> PortfolioDecision:
    fallback = rule_based_decision(reports, price)
    report_lines: list[str] = []
    for report in reports:
        report_lines.append(
            f"## {report.title}\n{report.summary}\n" + "\n".join(f"- {item}" for item in report.bullets)
        )
    prompt = f"""你是 crypto-trading-agents 的 Portfolio Manager。
请基于以下结构化 agent 报告，输出严格的 JSON，不要使用 Markdown 代码块。

当前价格: {price}

可用字段:
- action: "BUY" / "HOLD" / "SELL"
- confidence: 0-100 的整数
- summary: 2 到 4 句中文结论
- reasons: 2 到 6 条中文理由
- risks: 2 到 5 条中文风险提示
- position_size_pct: 数字或 null，单笔仓位百分比
- stop_loss: 数字或 null
- take_profit: 数字或 null
- time_horizon: 中文时间范围

Agent 报告:
{chr(10).join(report_lines)}
"""
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": "You are a disciplined crypto portfolio manager. Respond only with valid JSON."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in LLM output.")
        parsed = json.loads(match.group())
        action = str(parsed.get("action", fallback.action)).upper()
        if action not in {"BUY", "HOLD", "SELL"}:
            action = fallback.action
        confidence = int(parsed.get("confidence", fallback.confidence))
        confidence = max(0, min(confidence, 100))
        return PortfolioDecision(
            action=action,
            confidence=confidence,
            summary=str(parsed.get("summary", fallback.summary)),
            reasons=list(parsed.get("reasons", fallback.reasons)),
            risks=list(parsed.get("risks", fallback.risks)),
            position_size_pct=parsed.get("position_size_pct", fallback.position_size_pct),
            stop_loss=parsed.get("stop_loss", fallback.stop_loss),
            take_profit=parsed.get("take_profit", fallback.take_profit),
            time_horizon=str(parsed.get("time_horizon", fallback.time_horizon)),
            generated_by=f"llm:{model}",
        )
    except Exception:
        return fallback
