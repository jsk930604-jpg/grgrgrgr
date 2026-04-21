#!/usr/bin/env python3
"""금리차/VIX/DXY/WTI/MOVE 기반 한글 텔레그램 알림 스크립트."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib import error, parse, request


KST = dt.timezone(dt.timedelta(hours=9))
RSI_PERIOD = 14
RSI_OVERSOLD_THRESHOLD = 30.0

THEME_TICKERS: dict[str, list[str]] = {
    "우주": [
        "RKLB",
        "LUNR",
        "ASTS",
        "RDW",
        "PL",
        "SPIR",
        "SATS",
        "BKSY",
        "LLAP",
        "MNTS",
        "SPCE",
        "VSAT",
        "IRDM",
        "GILT",
        "SATL",
        "BA",
        "LMT",
        "NOC",
        "RTX",
        "GD",
        "LHX",
        "HII",
        "TXT",
        "GE",
        "HEI",
        "MRCY",
        "UFO",
        "ROKT",
        "ITA",
        "AVAV",
        "KTOS",
        "LDOS",
        "TDG",
        "HWM",
        "CW",
        "SPR",
        "AIR",
        "JOBY",
        "ACHR",
        "EH",
        "EVTL",
        "BLDE",
        "UAVS",
        "ARKX",
        "XAR",
        "PPA",
        "DFEN",
        "CACI",
        "SAIC",
        "DRS",
    ],
    "양자": [
        "IONQ",
        "RGTI",
        "QBTS",
        "QUBT",
        "ARQQ",
        "IBM",
        "GOOGL",
        "MSFT",
        "HON",
        "INTC",
        "NVDA",
        "AMD",
        "AMZN",
        "META",
        "AAPL",
        "ORCL",
        "TSM",
        "ASML",
        "MU",
        "ANET",
        "SMCI",
        "DELL",
        "HPQ",
        "CDNS",
        "SNPS",
        "ADI",
        "TXN",
        "MRVL",
        "QTUM",
        "ACN",
        "AVGO",
        "QCOM",
        "AMAT",
        "KLAC",
        "LRCX",
        "ON",
        "MCHP",
        "NXPI",
        "WDC",
        "STX",
        "CSCO",
        "HPE",
        "ADBE",
        "CRM",
        "NOW",
        "PANW",
        "CRWD",
        "NET",
        "DOCN",
        "SNOW",
    ],
    "원자력": [
        "CCJ",
        "UEC",
        "UUUU",
        "LEU",
        "SMR",
        "OKLO",
        "NNE",
        "BWXT",
        "LTBR",
        "URA",
        "URNM",
        "NLR",
        "DNN",
        "NXE",
        "UROY",
        "EU",
        "CEG",
        "VST",
        "DUK",
        "SO",
        "EXC",
        "AEP",
        "NEE",
        "FE",
        "ETR",
        "PPL",
        "PCG",
        "XEL",
        "FLR",
        "GEV",
        "SRE",
        "ED",
        "EIX",
        "PEG",
        "D",
        "WEC",
        "ES",
        "AEE",
        "CMS",
        "CNP",
        "DTE",
        "ATO",
        "NI",
        "LNT",
        "EVRG",
        "NRG",
        "TLN",
        "PNW",
        "UGI",
        "IDA",
    ],
}


@dataclass
class Snapshot:
    y10: float
    y2: float
    y10_prev: float
    y2_prev: float
    vix: float
    vix_prev: float
    dxy: float
    dxy_prev: float
    wti: float
    wti_prev: float
    move: float
    move_prev: float
    nas100: float | None = None
    nas100_prev: float | None = None

    @property
    def spread(self) -> float:
        return self.y10 - self.y2

    @property
    def spread_prev(self) -> float:
        return self.y10_prev - self.y2_prev


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def fetch_yahoo_chart_result(symbol: str, interval: str, range_: str) -> dict:
    encoded_symbol = parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"
        f"?interval={interval}&range={range_}"
    )
    req = request.Request(url=url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except error.URLError as exc:
        raise RuntimeError(f"{symbol} 조회 실패: {exc}") from exc

    payload = json.loads(raw)
    chart = payload.get("chart", {})
    result_list = chart.get("result") or []
    if not result_list:
        raise RuntimeError(f"{symbol} 조회 실패: 응답에 시세 데이터가 없습니다.")
    return result_list[0]


def extract_close_list(chart_result: dict) -> list[float]:
    quotes = chart_result.get("indicators", {}).get("quote", [])
    closes = quotes[0].get("close", []) if quotes else []
    return [float(v) for v in closes if isinstance(v, (int, float))]


def is_open_market_state(state: str | None) -> bool:
    if not state:
        return False
    return state.upper() in {"PRE", "PREPRE", "REGULAR", "POST", "POSTPOST"}


def fetch_yahoo_quote(symbol: str) -> tuple[float, float, int | None]:
    result = fetch_yahoo_chart_result(symbol=symbol, interval="1d", range_="5d")
    meta = result.get("meta", {})
    valid_closes = extract_close_list(result)
    if not valid_closes:
        raise RuntimeError(f"{symbol} 조회 실패: 종가 데이터가 비어 있습니다.")

    current = meta.get("regularMarketPrice")
    if not isinstance(current, (int, float)):
        current = valid_closes[-1]

    previous = meta.get("previousClose")
    if not isinstance(previous, (int, float)):
        previous = valid_closes[-2] if len(valid_closes) >= 2 else valid_closes[-1]

    market_time = meta.get("regularMarketTime")
    if not isinstance(market_time, int):
        timestamps = result.get("timestamp", [])
        market_time = timestamps[-1] if timestamps else None
    if market_time is not None and not isinstance(market_time, int):
        market_time = None

    return float(current), float(previous), market_time


def fetch_first_available(symbols: list[str], label: str) -> tuple[float, float, str, int | None]:
    errors: list[str] = []
    for symbol in symbols:
        try:
            current, previous, market_time = fetch_yahoo_quote(symbol)
            return current, previous, symbol, market_time
        except Exception as exc:  # pylint: disable=broad-except
            errors.append(str(exc))
    error_text = " | ".join(errors) if errors else "unknown"
    raise RuntimeError(f"{label} 자동조회 실패: {error_text}")


def normalize_yield(value: float) -> float:
    # Yahoo의 일부 금리 지표(^TNX 등)는 실제 금리의 10배 값으로 전달됨.
    return value / 10.0 if value > 20.0 else value


def fetch_realtime_snapshot() -> tuple[Snapshot, str]:
    y10, y10_prev, _y10_symbol, t1 = fetch_first_available(["^TNX"], "10년물 금리")
    y2, y2_prev, _y2_symbol, t2 = fetch_first_available(["^UST2Y", "^IRX"], "2년물 금리")
    vix, vix_prev, _vix_symbol, t3 = fetch_first_available(["^VIX"], "VIX")
    dxy, dxy_prev, _dxy_symbol, t4 = fetch_first_available(["DX-Y.NYB", "DX=F"], "DXY")
    wti, wti_prev, _wti_symbol, t5 = fetch_first_available(["CL=F"], "WTI")
    move, move_prev, _move_symbol, t6 = fetch_first_available(["^MOVE"], "MOVE")
    nas100, nas100_prev, _nas100_symbol, t7 = fetch_first_available(
        ["^NDX", "NQ=F"], "NAS100"
    )

    y10 = normalize_yield(y10)
    y10_prev = normalize_yield(y10_prev)
    y2 = normalize_yield(y2)
    y2_prev = normalize_yield(y2_prev)

    latest_epoch = max(
        [t for t in [t1, t2, t3, t4, t5, t6, t7] if t is not None], default=None
    )
    if latest_epoch is not None:
        updated_at = dt.datetime.fromtimestamp(latest_epoch, tz=dt.timezone.utc).astimezone(KST)
        updated_text = updated_at.strftime("%Y-%m-%d %H:%M KST")
    else:
        updated_text = "시간 정보 없음"

    source_note = f"Yahoo Finance 자동조회 ({updated_text})"

    snapshot = Snapshot(
        y10=y10,
        y2=y2,
        y10_prev=y10_prev,
        y2_prev=y2_prev,
        vix=vix,
        vix_prev=vix_prev,
        dxy=dxy,
        dxy_prev=dxy_prev,
        wti=wti,
        wti_prev=wti_prev,
        move=move,
        move_prev=move_prev,
        nas100=nas100,
        nas100_prev=nas100_prev,
    )
    return snapshot, source_note


def calc_rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    if len(closes) <= period:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def closed_price_from_daily_result(result: dict) -> float:
    closes = extract_close_list(result)
    if not closes:
        raise RuntimeError("종가 데이터 없음")

    meta = result.get("meta", {})
    market_state = meta.get("marketState")
    prev_close = meta.get("previousClose")
    if is_open_market_state(market_state) and isinstance(prev_close, (int, float)):
        return float(prev_close)
    return closes[-1]


def closes_for_rsi(result: dict) -> list[float]:
    closes = extract_close_list(result)
    if not closes:
        return []
    meta = result.get("meta", {})
    market_state = meta.get("marketState")
    # 장중에는 마지막 캔들이 완성되지 않았을 수 있어 RSI 계산에서 제외한다.
    if is_open_market_state(market_state) and len(closes) > 1:
        return closes[:-1]
    return closes


def analyze_theme_rsi() -> tuple[dict[str, list[dict]], str]:
    all_results: dict[str, list[dict]] = {}
    latest_epoch: int | None = None

    for theme, symbols in THEME_TICKERS.items():
        theme_rows: list[dict] = []
        for symbol in symbols:
            try:
                daily_result = fetch_yahoo_chart_result(symbol=symbol, interval="1d", range_="1y")
                weekly_result = fetch_yahoo_chart_result(symbol=symbol, interval="1wk", range_="5y")

                daily_closes = closes_for_rsi(daily_result)
                weekly_closes = closes_for_rsi(weekly_result)
                daily_rsi = calc_rsi(daily_closes)
                weekly_rsi = calc_rsi(weekly_closes)

                is_daily_oversold = daily_rsi is not None and daily_rsi <= RSI_OVERSOLD_THRESHOLD
                is_weekly_oversold = weekly_rsi is not None and weekly_rsi <= RSI_OVERSOLD_THRESHOLD
                close_price = closed_price_from_daily_result(daily_result)

                market_time = daily_result.get("meta", {}).get("regularMarketTime")
                if isinstance(market_time, int):
                    latest_epoch = max(latest_epoch, market_time) if latest_epoch else market_time

                theme_rows.append(
                    {
                        "symbol": symbol,
                        "close": close_price,
                        "daily_rsi": daily_rsi,
                        "weekly_rsi": weekly_rsi,
                        "daily_oversold": is_daily_oversold,
                        "weekly_oversold": is_weekly_oversold,
                        "oversold": is_daily_oversold or is_weekly_oversold,
                        "error": None,
                    }
                )
            except Exception as exc:  # pylint: disable=broad-except
                theme_rows.append(
                    {
                        "symbol": symbol,
                        "close": None,
                        "daily_rsi": None,
                        "weekly_rsi": None,
                        "daily_oversold": False,
                        "weekly_oversold": False,
                        "oversold": False,
                        "error": str(exc),
                    }
                )
        all_results[theme] = theme_rows

    if latest_epoch is not None:
        updated_at = dt.datetime.fromtimestamp(latest_epoch, tz=dt.timezone.utc).astimezone(KST)
        updated_text = updated_at.strftime("%Y-%m-%d %H:%M KST")
    else:
        updated_text = "시간 정보 없음"

    source_note = f"Yahoo Finance 자동조회 ({updated_text})"
    return all_results, source_note


def build_theme_rsi_message(theme_rows: dict[str, list[dict]], source_note: str) -> str:
    now_kst = dt.datetime.now(KST)
    total_count = sum(len(rows) for rows in theme_rows.values())
    lines = [
        f"🎯 테마 RSI 과매도 알림 ({now_kst.strftime('%Y-%m-%d %H:%M KST')})",
        f"데이터 기준: {source_note}",
        f"기준: 총 {total_count}종목(테마별 50) / 장마감 종가 기준 / RSI14",
        f"조건: 일봉 RSI ≤ {RSI_OVERSOLD_THRESHOLD:.0f} 또는 주봉 RSI ≤ {RSI_OVERSOLD_THRESHOLD:.0f}",
        "",
    ]

    total_oversold = 0
    for theme, rows in theme_rows.items():
        oversold_rows = [row for row in rows if row["oversold"]]
        total_oversold += len(oversold_rows)
        lines.append(f"[{theme}] 과매도 {len(oversold_rows)}/{len(rows)}")
        if not oversold_rows:
            lines.append("- 과매도 종목 없음")
        else:
            for row in oversold_rows:
                tags: list[str] = []
                if row["daily_oversold"]:
                    tags.append("일봉 과매도")
                if row["weekly_oversold"]:
                    tags.append("주봉 과매도")
                tag_text = ", ".join(tags) if tags else "확인 필요"
                daily_text = f"{row['daily_rsi']:.1f}" if row["daily_rsi"] is not None else "-"
                weekly_text = f"{row['weekly_rsi']:.1f}" if row["weekly_rsi"] is not None else "-"
                close_text = f"{row['close']:.2f}" if row["close"] is not None else "-"
                lines.append(
                    f"- {row['symbol']} | 종가 {close_text} | 일봉 {daily_text} / 주봉 {weekly_text} | {tag_text}"
                )

        error_symbols = [row["symbol"] for row in rows if row["error"]]
        if error_symbols:
            lines.append(f"- 조회 실패: {', '.join(error_symbols)}")
        lines.append("")

    lines.append(f"총 과매도 종목 수: {total_oversold}개")
    lines.append("※ 참고: RSI 과매도는 반등 보장이 아니며, 분할/리스크 관리가 필요합니다.")
    return "\n".join(lines)


def clip_telegram_text(text: str, limit: int = 3900) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 80] + "\n...(메시지 길이로 일부 종목이 생략되었습니다)"


def detect_trend(current: float, previous: float, threshold: float) -> str:
    diff = current - previous
    if diff > threshold:
        return "up"
    if diff < -threshold:
        return "down"
    return "flat"


def detect_pct_trend(current: float, previous: float, pct_threshold: float) -> str:
    if previous == 0:
        return "flat"
    change_pct = ((current - previous) / previous) * 100.0
    if change_pct > pct_threshold:
        return "up"
    if change_pct < -pct_threshold:
        return "down"
    return "flat"


def trend_arrow(trend: str) -> str:
    return {"up": "↑", "down": "↓", "flat": "→"}.get(trend, "?")


def spread_zone(spread: float) -> str:
    if spread >= 1.0:
        return "과열 후반"
    if spread >= 0.3:
        return "정상 상승"
    if spread > 0:
        return "초입/둔화"
    return "역전(위험)"


def vix_zone(vix: float) -> str:
    if vix < 13:
        return "과열(주의)"
    if vix < 18:
        return "정상(좋음)"
    if vix < 25:
        return "불안"
    return "공포(기회)"


def move_zone(move: float) -> str:
    if move <= 100:
        return "안정"
    if move <= 120:
        return "주의"
    return "위험"


def oil_state(wti: float, wti_prev: float) -> tuple[str, float]:
    if wti_prev == 0:
        return "안정", 0.0
    change_pct = ((wti - wti_prev) / wti_prev) * 100.0
    if change_pct >= 2.0:
        return "급등", change_pct
    if change_pct <= -2.0:
        return "급락", change_pct
    return "안정", change_pct


def pattern_and_strategy(spread: float, spread_trend: str, vix_trend: str) -> tuple[str, str]:
    if spread <= 0 and vix_trend == "up":
        return "하락 직전", "방어"
    if spread <= 0 and vix_trend == "down":
        return "후반 상승", "단타"
    if spread_trend == "up" and vix_trend == "down":
        return "상승장 초입", "적극"
    if spread_trend == "up" and vix_trend == "up":
        return "흔들리는 상승장", "눌림 매수"
    if spread_trend == "down" and vix_trend == "up":
        return "하락장", "회피"
    if spread_trend == "down" and vix_trend == "down":
        return "후반 상승(위험)", "짧게"
    return "혼조", "중립"


def evaluate(snapshot: Snapshot) -> dict:
    spread = snapshot.spread
    spread_prev = snapshot.spread_prev
    spread_trend = detect_trend(spread, spread_prev, threshold=0.03)
    vix_trend = detect_trend(snapshot.vix, snapshot.vix_prev, threshold=0.30)
    dxy_trend = detect_trend(snapshot.dxy, snapshot.dxy_prev, threshold=0.15)
    move_trend = detect_trend(snapshot.move, snapshot.move_prev, threshold=1.5)
    nas100_trend = "flat"
    if snapshot.nas100 is not None and snapshot.nas100_prev is not None:
        nas100_trend = detect_pct_trend(snapshot.nas100, snapshot.nas100_prev, pct_threshold=0.2)

    oil_label, oil_change_pct = oil_state(snapshot.wti, snapshot.wti_prev)

    attack_ok = spread_trend == "up" and vix_trend == "down" and dxy_trend == "down"
    defend_ok = spread_trend == "down" and vix_trend == "up" and dxy_trend == "up"

    bull_score = 0
    risk_score = 0

    if spread > 0 and spread_trend == "up":
        bull_score += 1
    if vix_trend == "down":
        bull_score += 1
    if dxy_trend == "down":
        bull_score += 1
    if oil_label == "안정":
        bull_score += 1
    if snapshot.move <= 100 and move_trend != "up":
        bull_score += 1

    if spread <= 0:
        risk_score += 2
    if spread_trend == "down":
        risk_score += 1
    if vix_trend == "up":
        risk_score += 1
    if dxy_trend == "up":
        risk_score += 1
    if oil_label == "급등":
        risk_score += 1
    if snapshot.move > 120 or move_trend == "up":
        risk_score += 1

    pattern, strategy = pattern_and_strategy(spread, spread_trend, vix_trend)

    if risk_score >= 4 or (spread <= 0 and vix_trend == "up"):
        market_state = "⚠️ 위험 장"
        stance = "방어"
    elif bull_score >= 4 and oil_label != "급등" and snapshot.move <= 120:
        market_state = "🔥 좋은 장"
        stance = "공격"
    else:
        market_state = "➖ 중립/혼조"
        stance = strategy

    if attack_ok:
        stance = "공격"
    if defend_ok:
        stance = "방어"

    return {
        "spread": spread,
        "spread_prev": spread_prev,
        "spread_trend": spread_trend,
        "vix_trend": vix_trend,
        "dxy_trend": dxy_trend,
        "move_trend": move_trend,
        "nas100_trend": nas100_trend,
        "oil_label": oil_label,
        "oil_change_pct": oil_change_pct,
        "attack_ok": attack_ok,
        "defend_ok": defend_ok,
        "bull_score": bull_score,
        "risk_score": risk_score,
        "market_state": market_state,
        "pattern": pattern,
        "strategy": strategy,
        "stance": stance,
    }


def build_message(snapshot: Snapshot, result: dict, source_note: str | None = None) -> str:
    now_kst = dt.datetime.now(KST)
    lines = [
        f"📊 시장 종합 알림 ({now_kst.strftime('%Y-%m-%d %H:%M KST')})",
        f"종합 판정: {result['market_state']}",
        f"매매 스탠스: {result['stance']}",
        "",
        "[핵심 조건]",
        f"- 공격 조건(금리차↑ + VIX↓ + DXY↓): {'충족' if result['attack_ok'] else '미충족'}",
        f"- 방어 조건(금리차↓ + VIX↑ + DXY↑): {'충족' if result['defend_ok'] else '미충족'}",
        "",
        "[추가 지표 요약]",
        f"- VIX: {snapshot.vix:.2f}점 ({vix_zone(snapshot.vix)}) {trend_arrow(result['vix_trend'])}",
        (
            f"- 금리차(10Y-2Y): {result['spread']:.2f} ({spread_zone(result['spread'])}) "
            f"{trend_arrow(result['spread_trend'])}"
        ),
        f"- DXY: {snapshot.dxy:.2f} {trend_arrow(result['dxy_trend'])}",
        f"- MOVE: {snapshot.move:.2f} ({move_zone(snapshot.move)}) {trend_arrow(result['move_trend'])}",
        f"- WTI: {snapshot.wti:.2f}달러 ({result['oil_label']}, {result['oil_change_pct']:+.2f}%)",
    ]
    if snapshot.nas100 is not None:
        if snapshot.nas100_prev is not None and snapshot.nas100_prev != 0:
            nas100_change = ((snapshot.nas100 - snapshot.nas100_prev) / snapshot.nas100_prev) * 100.0
            lines.append(
                f"- NAS100: {snapshot.nas100:.2f} ({nas100_change:+.2f}%) "
                f"{trend_arrow(result['nas100_trend'])}"
            )
        else:
            lines.append(f"- NAS100: {snapshot.nas100:.2f}")
    lines.extend(
        [
            "",
        f"[패턴] {result['pattern']} → 전략: {result['strategy']}",
        f"[점수] 상승 {result['bull_score']}점 / 위험 {result['risk_score']}점",
        "",
        "[점수/패턴 가이드]",
        "- 상승 점수: 4~5 우호, 2~3 중립, 0~1 약세",
        "- 위험 점수: 0~1 안정, 2~3 주의, 4+ 위험",
        "- 패턴: 상승장 초입=적극, 흔들리는 상승장=눌림 매수, 하락 직전/하락장=방어",
        "",
        "※ 참고: 본 알림은 보조 지표 해석용이며 투자 책임은 본인에게 있습니다.",
        ]
    )
    if source_note:
        lines.insert(1, f"데이터 기준: {source_note}")
    return "\n".join(lines)


def send_telegram_message(token: str, chat_id: str, text: str) -> dict:
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    safe_text = clip_telegram_text(text)
    payload = {
        "chat_id": chat_id,
        "text": safe_text,
        "disable_web_page_preview": True,
    }
    encoded = parse.urlencode(payload).encode("utf-8")
    req = request.Request(api_url, data=encoded, method="POST")
    try:
        with request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
    except error.URLError as exc:
        raise RuntimeError(f"텔레그램 전송 실패: {exc}") from exc

    data = json.loads(body)
    if not data.get("ok"):
        raise RuntimeError(f"텔레그램 API 오류: {data}")
    return data


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="금리차/VIX/DXY/WTI/MOVE 기반 한글 텔레그램 알림"
    )
    parser.add_argument("--y10", type=float, help="미국채 10년물 금리")
    parser.add_argument("--y2", type=float, help="미국채 2년물 금리")
    parser.add_argument("--vix", type=float, help="VIX 현재값")
    parser.add_argument("--dxy", type=float, help="DXY 현재값")
    parser.add_argument("--wti", type=float, help="WTI 현재값")
    parser.add_argument("--move", type=float, help="MOVE 현재값")
    parser.add_argument("--nas100", type=float, help="NAS100 현재값(선택)")

    parser.add_argument("--y10-prev", type=float, help="이전 10년물 금리")
    parser.add_argument("--y2-prev", type=float, help="이전 2년물 금리")
    parser.add_argument("--vix-prev", type=float, help="이전 VIX")
    parser.add_argument("--dxy-prev", type=float, help="이전 DXY")
    parser.add_argument("--wti-prev", type=float, help="이전 WTI")
    parser.add_argument("--move-prev", type=float, help="이전 MOVE")
    parser.add_argument("--nas100-prev", type=float, help="이전 NAS100(선택)")

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="텔레그램 전송 없이 콘솔에 메시지만 출력",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Yahoo Finance에서 지표를 자동조회해 알림 생성",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dotenv_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path)

    source_note = "수동 입력값"
    if args.auto:
        try:
            snapshot, source_note = fetch_realtime_snapshot()
        except Exception as exc:  # pylint: disable=broad-except
            print(f"실시간 자동조회 실패: {exc}")
            return 1
    else:
        required_values = [args.y10, args.y2, args.vix, args.dxy, args.wti, args.move]
        if any(v is None for v in required_values):
            print("수동 모드에서는 --y10 --y2 --vix --dxy --wti --move가 필요합니다. (또는 --auto)")
            return 1
        snapshot = Snapshot(
            y10=float(args.y10),
            y2=float(args.y2),
            y10_prev=args.y10_prev if args.y10_prev is not None else float(args.y10),
            y2_prev=args.y2_prev if args.y2_prev is not None else float(args.y2),
            vix=float(args.vix),
            vix_prev=args.vix_prev if args.vix_prev is not None else float(args.vix),
            dxy=float(args.dxy),
            dxy_prev=args.dxy_prev if args.dxy_prev is not None else float(args.dxy),
            wti=float(args.wti),
            wti_prev=args.wti_prev if args.wti_prev is not None else float(args.wti),
            move=float(args.move),
            move_prev=args.move_prev if args.move_prev is not None else float(args.move),
            nas100=float(args.nas100) if args.nas100 is not None else None,
            nas100_prev=(
                args.nas100_prev
                if args.nas100_prev is not None
                else (float(args.nas100) if args.nas100 is not None else None)
            ),
        )

    result = evaluate(snapshot)
    market_message = build_message(snapshot, result, source_note=source_note)
    print(market_message)

    try:
        theme_rows, theme_source_note = analyze_theme_rsi()
        theme_message = build_theme_rsi_message(theme_rows, theme_source_note)
    except Exception as exc:  # pylint: disable=broad-except
        now_kst = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        theme_message = (
            f"🎯 테마 RSI 과매도 알림 ({now_kst})\n"
            f"생성 실패: {exc}\n"
            "※ 시장 종합 알림은 정상 전송됩니다."
        )
    print("\n" + theme_message)

    if args.dry_run:
        print("\n[dry-run] 텔레그램 전송은 생략했습니다.")
        return 0

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        print("텔레그램 전송을 위해 .env의 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 필요합니다.")
        return 1

    try:
        send_telegram_message(token=token, chat_id=chat_id, text=market_message)
        send_telegram_message(token=token, chat_id=chat_id, text=theme_message)
    except Exception as exc:  # pylint: disable=broad-except
        print(str(exc))
        return 1

    print("\n텔레그램 전송 완료 (2건: 시장 종합 + 테마 RSI)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
