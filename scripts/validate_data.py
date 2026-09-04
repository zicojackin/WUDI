"""OHLCV 数据完整性校验脚本。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


class DataValidator:
    """检查 OHLCV 数据缺失、重复、异常值和时间连续性。"""

    def __init__(self, expected_freq: str = "1D"):
        self.expected_freq = expected_freq

    def validate(self, frame: pd.DataFrame, symbol: str = "UNKNOWN") -> dict:
        issues: list[str] = []
        warnings: list[str] = []
        normalized = self._normalize(frame)

        missing_columns = REQUIRED_COLUMNS - set(normalized.columns)
        if missing_columns:
            issues.append(f"缺少必要列: {sorted(missing_columns)}")
            return self._result(symbol, normalized, issues, warnings)

        issues.extend(self._check_index(normalized))
        warnings.extend(self._check_missing_bars(normalized))
        warnings.extend(self._check_duplicates(normalized))
        issues.extend(self._check_prices(normalized))
        warnings.extend(self._check_volume(normalized))
        warnings.extend(self._check_gaps(normalized))

        return self._result(symbol, normalized, issues, warnings)

    def _normalize(self, frame: pd.DataFrame) -> pd.DataFrame:
        normalized = frame.copy()
        normalized.columns = [str(column).lower().strip() for column in normalized.columns]
        if "date" in normalized.columns:
            normalized["date"] = pd.to_datetime(normalized["date"], utc=True, errors="coerce")
            normalized = normalized.set_index("date")
        elif "timestamp" in normalized.columns:
            normalized["timestamp"] = pd.to_datetime(
                normalized["timestamp"],
                unit="ms",
                utc=True,
                errors="coerce",
            )
            normalized = normalized.set_index("timestamp")
        else:
            normalized.index = pd.to_datetime(normalized.index, utc=True, errors="coerce")
        return normalized.sort_index()

    def _result(
        self,
        symbol: str,
        frame: pd.DataFrame,
        issues: list[str],
        warnings: list[str],
    ) -> dict:
        return {
            "symbol": symbol,
            "passed": not issues,
            "issues": issues,
            "warnings": warnings,
            "stats": {
                "total_rows": len(frame),
                "start": str(frame.index[0]) if len(frame) else None,
                "end": str(frame.index[-1]) if len(frame) else None,
                "days": int((frame.index[-1] - frame.index[0]).days) if len(frame) > 1 else 0,
            },
        }

    def _check_index(self, frame: pd.DataFrame) -> list[str]:
        issues = []
        if not isinstance(frame.index, pd.DatetimeIndex):
            issues.append(f"索引不是 DatetimeIndex: {type(frame.index).__name__}")
        elif frame.index.hasnans:
            issues.append("索引中存在无效日期")
        return issues

    def _check_missing_bars(self, frame: pd.DataFrame) -> list[str]:
        if not isinstance(frame.index, pd.DatetimeIndex) or len(frame) < 2:
            return []
        expected = pd.date_range(frame.index[0], frame.index[-1], freq=self.expected_freq)
        missing = expected.difference(frame.index)
        if missing.empty:
            return []
        return [
            f"疑似缺失 {len(missing)} 根 K 线，例如 {missing[:5].strftime('%Y-%m-%d').tolist()}"
        ]

    def _check_duplicates(self, frame: pd.DataFrame) -> list[str]:
        duplicates = int(frame.index.duplicated().sum())
        return [f"存在 {duplicates} 个重复时间戳"] if duplicates else []

    def _check_prices(self, frame: pd.DataFrame) -> list[str]:
        issues = []
        for column in ["open", "high", "low", "close"]:
            non_positive = int((frame[column] <= 0).sum())
            invalid_values = int(frame[column].isna().sum())
            if non_positive:
                issues.append(f"{column} 存在 {non_positive} 个非正值")
            if invalid_values:
                issues.append(f"{column} 存在 {invalid_values} 个 NaN")
        invalid_range = int((frame["high"] < frame["low"]).sum())
        if invalid_range:
            issues.append(f"存在 {invalid_range} 根 high < low 的 K 线")
        invalid_high = int(
            (
                (frame["high"] < frame[["open", "close"]].max(axis=1))
                | (frame["low"] > frame[["open", "close"]].min(axis=1))
            ).sum()
        )
        if invalid_high:
            issues.append(f"存在 {invalid_high} 根 high/low 与 open/close 不一致的 K 线")
        extreme_move = int(frame["close"].pct_change().abs().gt(0.5).sum())
        if extreme_move:
            issues.append(f"存在 {extreme_move} 个单日涨跌幅超过 50% 的可疑点")
        return issues

    def _check_volume(self, frame: pd.DataFrame) -> list[str]:
        warnings = []
        zero_volume = int((frame["volume"] <= 0).sum())
        if zero_volume:
            warnings.append(f"存在 {zero_volume} 根成交量为零或负值的 K 线")
        mean_volume = float(frame["volume"].mean())
        if mean_volume > 0:
            extreme_volume = int(frame["volume"].gt(100 * mean_volume).sum())
            if extreme_volume:
                warnings.append(f"存在 {extreme_volume} 根成交量超过 100 倍均值的 K 线")
        return warnings

    def _check_gaps(self, frame: pd.DataFrame) -> list[str]:
        open_to_prev_close = (
            (frame["open"] - frame["close"].shift(1)) / frame["close"].shift(1)
        ).abs()
        large_gaps = int(open_to_prev_close.gt(0.20).sum())
        if large_gaps:
            return [f"存在 {large_gaps} 个开盘价与前收盘价差距超过 20% 的缺口"]
        return []


def load_csv(path: str | Path) -> pd.DataFrame:
    """加载 CSV 并标准化日期索引。"""
    frame = pd.read_csv(path)
    validator = DataValidator()
    return validator._normalize(frame)


def validate_ohlcv_frame(
    frame: pd.DataFrame,
    symbol: str = "UNKNOWN",
    expected_freq: str = "1D",
) -> dict:
    """供回测脚本直接调用的数据校验入口。"""
    return DataValidator(expected_freq=expected_freq).validate(frame, symbol)


def print_report(result: dict) -> None:
    """打印人类可读校验报告。"""
    print(f"[{result['symbol']}] {'PASS' if result['passed'] else 'FAIL'}")
    print(f"  rows={result['stats']['total_rows']}")
    print(f"  range={result['stats']['start']} ~ {result['stats']['end']}")
    for issue in result["issues"]:
        print(f"  ISSUE: {issue}")
    for warning in result["warnings"]:
        print(f"  WARN: {warning}")


def main() -> None:
    parser = argparse.ArgumentParser(description="校验 OHLCV 数据完整性")
    parser.add_argument("--file")
    parser.add_argument("--data-dir")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--freq", default="1D")
    args = parser.parse_args()

    if args.file:
        paths = [Path(args.file)]
    elif args.data_dir:
        directory = Path(args.data_dir)
        paths = sorted(directory.glob("*.csv"))
        if args.symbols:
            lower = {symbol.lower() for symbol in args.symbols}
            paths = [path for path in paths if any(item in path.stem.lower() for item in lower)]
    else:
        parser.error("必须提供 --file 或 --data-dir")
        return

    results = []
    for path in paths:
        if not path.exists():
            print(f"文件不存在: {path}")
            continue
        frame = load_csv(path)
        result = DataValidator(args.freq).validate(frame, path.stem)
        print_report(result)
        results.append(result)

    if not results:
        sys.exit(1)
    if any(not result["passed"] for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
