from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    binance_base_url: str = "https://data-api.binance.vision"
    binance_timeout: int = 20
    okx_base_url: str = "https://www.okx.com"
    okx_timeout: int = 20
    okx_config_path: Path = Path(".okx_config.json")
    reports_dir: Path = Path("reports")

    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-5.6"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1400

    @classmethod
    def from_env(cls) -> "Settings":
        config_path = Path(
            os.getenv(
                "OKX_CONFIG_PATH",
                Path(__file__).resolve().parent.parent.parent / ".okx_config.json",
            )
        )
        return cls(
            binance_base_url=os.getenv(
                "BINANCE_BASE_URL",
                "https://data-api.binance.vision",
            ).rstrip("/"),
            binance_timeout=int(os.getenv("BINANCE_TIMEOUT", "20")),
            okx_base_url=os.getenv("OKX_BASE_URL", "https://www.okx.com").rstrip("/"),
            okx_timeout=int(os.getenv("OKX_TIMEOUT", "20")),
            okx_config_path=config_path,
            reports_dir=Path(os.getenv("CRYPTO_TRADING_AGENTS_REPORTS_DIR", "reports")),
            llm_api_key=os.getenv("CRYPTO_TRADING_AGENTS_LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY"),
            llm_base_url=os.getenv(
                "CRYPTO_TRADING_AGENTS_LLM_BASE_URL",
                "https://api.openai.com/v1",
            ).rstrip("/"),
            llm_model=os.getenv("CRYPTO_TRADING_AGENTS_LLM_MODEL", "gpt-5.6"),
            llm_temperature=float(os.getenv("CRYPTO_TRADING_AGENTS_LLM_TEMPERATURE", "0.2")),
            llm_max_tokens=int(os.getenv("CRYPTO_TRADING_AGENTS_LLM_MAX_TOKENS", "1400")),
        )
