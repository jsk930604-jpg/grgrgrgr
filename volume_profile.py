"""
20일 평균 거래량 필터 + 주봉 매물대(거래량 프로파일) 계산 공용 유틸리티.

이 모듈은 기존 RSI 과매도 스캔/알림 로직(rsi_oversold_alert.py, us_stock_rsi_alert.py의
기존 함수들)과 완전히 독립적입니다. 두 스크립트에서 "과매도 Telegram 알림을 실제로
전송한 직후" 후속 단계로만 import해서 사용합니다.

거래대금은 계산하지 않으며, 당일 거래량/평균 대비 배수는 필터 조건이 아니라
요약 메시지의 참고 정보로만 사용됩니다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# 환경변수/설정 (요청하신 기본값 그대로)
KOSPI_MIN_AVG_20D_VOLUME = _env_float("KOSPI_MIN_AVG_20D_VOLUME", 1_000_000)
KOSDAQ_MIN_AVG_20D_VOLUME = _env_float("KOSDAQ_MIN_AVG_20D_VOLUME", 200_000)
US_MIN_AVG_20D_VOLUME = _env_float("US_MIN_AVG_20D_VOLUME", 5_000_000)

MIN_VOLUME_BY_MARKET = {
    "KOSPI": KOSPI_MIN_AVG_20D_VOLUME,
    "KOSDAQ": KOSDAQ_MIN_AVG_20D_VOLUME,
    "US": US_MIN_AVG_20D_VOLUME,
}


def rsi_series(closes: Sequence[float], period: int = 14) -> list[float | None]:
    """차트 표시용 구간별 RSI 값 리스트. 각 스크립트의 기존 calculate_rsi(단일 최신값)와는
    별개의 새 함수이며, 앞의 period개 구간은 계산 불가하므로 None으로 채운다."""
    values = list(closes)
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values, values[1:]):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

    idx = period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        idx += 1
        result[idx] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

    return result


@dataclass(frozen=True)
class OhlcvBar:
    date: str  # YYYYMMDD
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class VolumeFilterResult:
    passed: bool
    avg_volume: float | None
    threshold: float | None
    reason: str | None  # 통과 시 None, 제외 시 사유


def average_volume_20d(bars: Sequence[OhlcvBar]) -> float | None:
    """최근 20거래일 일별 거래량 합계 / 20 (실제 거래일 수).

    20거래일 데이터가 없으면(부족하면) None을 반환한다 — 이 경우 호출 측에서
    해당 종목을 후속 요약에서 제외해야 한다.
    """
    if len(bars) < 20:
        return None
    recent = sorted(bars, key=lambda bar: bar.date)[-20:]
    return sum(bar.volume for bar in recent) / 20


def evaluate_volume_filter(market: str | None, bars: Sequence[OhlcvBar]) -> VolumeFilterResult:
    """시장 구분 + 20일 평균 거래량 기준으로 후속 요약 포함 여부를 판정한다."""
    if not market or market not in MIN_VOLUME_BY_MARKET:
        return VolumeFilterResult(False, None, None, "시장 구분 확인 불가")

    avg_volume = average_volume_20d(bars)
    threshold = MIN_VOLUME_BY_MARKET[market]
    if avg_volume is None:
        return VolumeFilterResult(False, None, threshold, "최근 20거래일 데이터 부족")

    if avg_volume < threshold:
        return VolumeFilterResult(False, avg_volume, threshold, "평균 거래량 기준 미달")

    return VolumeFilterResult(True, avg_volume, threshold, None)


@dataclass(frozen=True)
class VolumeProfile:
    poc_low: float
    poc_high: float
    resistance_price: float | None
    resistance_distance_pct: float | None
    support_price: float | None
    support_distance_pct: float | None
    position: str


def build_weekly_volume_profile(
    weekly_bars: Sequence[OhlcvBar], current_price: float, bins: int = 20
) -> VolumeProfile | None:
    """주봉 OHLCV로 거래량 프로파일(매물대)을 계산한다.

    - 가격 구간을 bins개로 나눠 각 구간에 (고가+저가+종가)/3 기준으로 거래량을 누적한다.
    - 거래량이 가장 많이 몰린 구간을 핵심 매물대(POC)로 본다.
    - 중앙값 이상 거래량이 몰린 구간 중 현재가 위/아래에서 가장 가까운 구간을
      각각 저항/지지 매물대로 본다.
    """
    if len(weekly_bars) < 10:
        return None

    lows = [bar.low for bar in weekly_bars]
    highs = [bar.high for bar in weekly_bars]
    price_min = min(lows)
    price_max = max(highs)
    if price_max <= price_min:
        return None

    bin_size = (price_max - price_min) / bins
    volume_by_bin = [0.0] * bins

    def bin_index(price: float) -> int:
        idx = int((price - price_min) / bin_size)
        return max(0, min(bins - 1, idx))

    for bar in weekly_bars:
        typical_price = (bar.high + bar.low + bar.close) / 3
        volume_by_bin[bin_index(typical_price)] += bar.volume

    bin_mids = [price_min + (i + 0.5) * bin_size for i in range(bins)]

    poc_idx = max(range(bins), key=lambda i: volume_by_bin[i])
    poc_low = price_min + poc_idx * bin_size
    poc_high = poc_low + bin_size

    nonzero_volumes = sorted(v for v in volume_by_bin if v > 0)
    significance_threshold = nonzero_volumes[len(nonzero_volumes) // 2] if nonzero_volumes else 0.0

    resistance_price = next(
        (
            bin_mids[i]
            for i in range(bins)
            if bin_mids[i] > current_price and volume_by_bin[i] >= significance_threshold and volume_by_bin[i] > 0
        ),
        None,
    )
    support_price = next(
        (
            bin_mids[i]
            for i in range(bins - 1, -1, -1)
            if bin_mids[i] < current_price and volume_by_bin[i] >= significance_threshold and volume_by_bin[i] > 0
        ),
        None,
    )

    resistance_distance_pct = (
        (resistance_price - current_price) / current_price * 100 if resistance_price else None
    )
    support_distance_pct = (
        (current_price - support_price) / current_price * 100 if support_price else None
    )

    if poc_low <= current_price <= poc_high:
        position = "핵심 매물대 내부"
    elif current_price > poc_high:
        position = "상단 매물대 돌파" if resistance_price and current_price >= resistance_price else "핵심 매물대 상단"
    else:
        position = "하단 매물대 이탈" if support_price and current_price <= support_price else "핵심 매물대 하단"

    return VolumeProfile(
        poc_low=poc_low,
        poc_high=poc_high,
        resistance_price=resistance_price,
        resistance_distance_pct=resistance_distance_pct,
        support_price=support_price,
        support_distance_pct=support_distance_pct,
        position=position,
    )


@dataclass(frozen=True)
class SummaryRow:
    theme: str
    label: str  # 예: "삼성전자(005930)" 또는 "RKLB"
    market: str  # KOSPI / KOSDAQ / US
    close: float
    avg_volume: float
    today_volume: float | None
    volume_ratio: float | None  # 당일 거래량 / 20일 평균 (참고 정보 전용, 필터 아님)
    profile: VolumeProfile


@dataclass(frozen=True)
class ExclusionLogEntry:
    label: str
    market: str | None
    avg_volume: float | None
    threshold: float | None
    reason: str


def format_exclusion_log(entry: ExclusionLogEntry) -> str:
    market_text = entry.market or "확인불가"
    avg_text = f"{entry.avg_volume:,.0f}" if entry.avg_volume is not None else "N/A"
    threshold_text = f"{entry.threshold:,.0f}" if entry.threshold is not None else "N/A"
    return (
        f"[매물대 요약 제외] {entry.label} | 시장: {market_text} | "
        f"20일 평균 거래량: {avg_text} | 기준값: {threshold_text} | 사유: {entry.reason}"
    )


def format_volume_summary(market_label: str, rows: Sequence[SummaryRow]) -> str:
    """[주봉 매물대 요약] Telegram 메시지 1개를 만든다. rows가 비어있으면 빈 문자열."""
    if not rows:
        return ""

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"[주봉 매물대 요약] {market_label} ({now})", ""]

    grouped: dict[str, list[SummaryRow]] = {}
    for row in rows:
        grouped.setdefault(row.theme, []).append(row)

    for theme, theme_rows in grouped.items():
        lines.append(f"[{theme}]")
        for row in theme_rows:
            lines.append(f"- {row.label} ({row.market})")
            lines.append(f"  종가: {row.close:,.2f}")
            lines.append(f"  20일 평균 거래량: {row.avg_volume:,.0f}")
            if row.today_volume is not None:
                lines.append(f"  당일 거래량: {row.today_volume:,.0f}")
            if row.volume_ratio is not None:
                lines.append(f"  평균 대비 거래량: {row.volume_ratio:.2f}배")
            lines.append(f"  현재 위치: {row.profile.position}")
            lines.append(f"  핵심 매물대: {row.profile.poc_low:,.2f} ~ {row.profile.poc_high:,.2f}")
            if row.profile.resistance_price is not None:
                lines.append(
                    f"  상단 저항 매물대: {row.profile.resistance_price:,.2f} "
                    f"(+{row.profile.resistance_distance_pct:.1f}%)"
                )
            else:
                lines.append("  상단 저항 매물대: 없음")
            if row.profile.support_price is not None:
                lines.append(
                    f"  하단 지지 매물대: {row.profile.support_price:,.2f} "
                    f"(-{row.profile.support_distance_pct:.1f}%)"
                )
            else:
                lines.append("  하단 지지 매물대: 없음")
        lines.append("")

    return "\n".join(lines).strip()


@dataclass(frozen=True)
class VolumeSummaryCandidate:
    """알림 후속 처리 대상 1건에 대한 입력 데이터 모음 (시장 무관 공통 형태)."""

    theme: str
    label: str
    market: str | None
    daily_bars: Sequence[OhlcvBar]
    weekly_bars: Sequence[OhlcvBar]
    current_price: float
    today_volume: float | None


def build_summary_rows(
    candidates: Sequence[VolumeSummaryCandidate],
    log_fn: Callable[[str], None] = print,
) -> list[SummaryRow]:
    """후보 목록에 20일 평균 거래량 필터 + 매물대 계산을 적용해 요약 대상 rows를 만든다.

    - 개별 종목 처리 중 예외가 발생해도 전체 처리를 중단하지 않고 해당 종목만 건너뛴다.
    - 제외된 종목은 log_fn으로 사유를 남긴다.
    """
    rows: list[SummaryRow] = []
    for candidate in candidates:
        try:
            filter_result = evaluate_volume_filter(candidate.market, candidate.daily_bars)
            if not filter_result.passed:
                log_fn(
                    format_exclusion_log(
                        ExclusionLogEntry(
                            label=candidate.label,
                            market=candidate.market,
                            avg_volume=filter_result.avg_volume,
                            threshold=filter_result.threshold,
                            reason=filter_result.reason or "제외",
                        )
                    )
                )
                continue

            profile = build_weekly_volume_profile(candidate.weekly_bars, candidate.current_price)
            if profile is None:
                log_fn(
                    format_exclusion_log(
                        ExclusionLogEntry(
                            label=candidate.label,
                            market=candidate.market,
                            avg_volume=filter_result.avg_volume,
                            threshold=filter_result.threshold,
                            reason="주봉 매물대 계산 불가(데이터 부족)",
                        )
                    )
                )
                continue

            volume_ratio = (
                candidate.today_volume / filter_result.avg_volume
                if candidate.today_volume is not None and filter_result.avg_volume
                else None
            )

            rows.append(
                SummaryRow(
                    theme=candidate.theme,
                    label=candidate.label,
                    market=candidate.market or "UNKNOWN",
                    close=candidate.current_price,
                    avg_volume=filter_result.avg_volume,
                    today_volume=candidate.today_volume,
                    volume_ratio=volume_ratio,
                    profile=profile,
                )
            )
        except Exception as exc:  # noqa: BLE001 - 개별 종목 오류가 전체를 중단시키지 않음
            log_fn(f"[매물대 요약 오류] {candidate.label} 처리 중 예외 발생, 건너뜀: {exc}")
            continue

    return rows
