"""
미국 주식 테마별 종목 RSI(일봉/주봉) 과매도 텔레그램 알림.

기존 rsi_oversold_alert.py(국내 종목)는 전혀 건드리지 않고,
KIS 해외주식기간별시세 API(HHDFS76240000)를 사용하는 별도 스크립트로 구성했습니다.

워치리스트 형식 (기본: 바탕화면 "미국 주식 테마별 종목 티커.txt", 환경변수 US_WATCHLIST_PATH로 변경 가능):

    (우주항공)
    BETA
    ISSC
    ...

    (로봇)
    KE
    SERV

종목코드 줄 하나에 티커 하나. 거래소(NAS/NYS/AMS)는 자동으로 순서대로 시도하여 찾습니다.
"""

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import requests

import volume_profile as vp


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
TOKEN_CACHE_PATH = BASE_DIR / ".kis_token_cache_us.json"


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return {**env, **os.environ}


ENV = load_env(ENV_PATH)

KIS_APP_KEY = ENV.get("KIS_APP_KEY", "")
KIS_APP_SECRET = ENV.get("KIS_APP_SECRET", "")
KIS_BASE_URL = ENV.get("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443").rstrip("/")
TELEGRAM_BOT_TOKEN = ENV.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = ENV.get("TELEGRAM_CHAT_ID", "")
RSI_PERIOD = int(ENV.get("RSI_PERIOD", "14"))
RSI_OVERSOLD = float(ENV.get("RSI_OVERSOLD", "30"))
REQUEST_SLEEP_SEC = float(ENV.get("REQUEST_SLEEP_SEC", "0.25"))
DASHBOARD_URL = ENV.get("DASHBOARD_URL", "https://jsk930604-jpg.github.io/grgrgrgr/")
DASHBOARD_DATA_DIR = BASE_DIR / "docs" / "data"
US_WATCHLIST_PATH = Path(
    ENV.get(
        "US_WATCHLIST_PATH",
        str(Path.home() / "Desktop" / "미국 주식 테마별 종목 티커.txt"),
    )
).expanduser()

# 순서대로 시도할 거래소 코드 (나스닥 -> 뉴욕 -> 아멕스)
EXCHANGE_CANDIDATES = ("NAS", "NYS", "AMS")


@dataclass(frozen=True)
class WatchItem:
    theme: str
    ticker: str


def require_config() -> None:
    missing = [
        name
        for name, value in {
            "KIS_APP_KEY": KIS_APP_KEY,
            "KIS_APP_SECRET": KIS_APP_SECRET,
            "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
            "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(f".env(또는 시크릿)에 필수 값이 없습니다: {', '.join(missing)}")


def read_watchlist_text(path: Path) -> str:
    raw = path.read_bytes()
    encodings = ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16")
    candidates: list[tuple[int, str]] = []
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        badness = text.count("\ufffd") + text.count("?") // 8
        candidates.append((badness, text))
    if not candidates:
        return raw.decode("utf-8", errors="replace")
    return sorted(candidates, key=lambda item: item[0])[0][1]


def parse_watchlist(path: Path) -> list[WatchItem]:
    if not path.exists():
        raise SystemExit(f"미국 주식 종목코드 파일을 찾을 수 없습니다: {path}")

    current_theme = "미분류"
    found: dict[tuple[str, str], WatchItem] = {}
    for raw_line in read_watchlist_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        theme_match = re.fullmatch(r"[(\[<（].+?[)\]>）]", line)
        if theme_match:
            current_theme = re.sub(r"^[(\[<（]|[)\]>）]$", "", line).strip()
            continue

        ticker_match = re.fullmatch(r"[A-Za-z]{1,6}(?:\.[A-Za-z])?", line)
        if ticker_match:
            ticker = line.upper()
            found.setdefault((current_theme, ticker), WatchItem(current_theme, ticker))

    return list(found.values())


def get_kis_token() -> str:
    if TOKEN_CACHE_PATH.exists():
        try:
            cache = json.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
            if cache.get("access_token") and float(cache.get("expires_at", 0)) > time.time() + 300:
                return cache["access_token"]
        except (OSError, ValueError, TypeError):
            pass

    url = f"{KIS_BASE_URL}/oauth2/tokenP"
    response = requests.post(
        url,
        json={
            "grant_type": "client_credentials",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    token = data["access_token"]
    expires_in = int(data.get("expires_in", 86400))
    TOKEN_CACHE_PATH.write_text(
        json.dumps({"access_token": token, "expires_at": time.time() + expires_in}, ensure_ascii=False),
        encoding="utf-8",
    )
    return token


def _dailyprice_request(token: str, excd: str, symb: str, gubn: str, bymd: str) -> dict:
    url = f"{KIS_BASE_URL}/uapi/overseas-price/v1/quotations/dailyprice"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": "HHDFS76240000",
        "custtype": "P",
    }
    params = {
        "AUTH": "",
        "EXCD": excd,
        "SYMB": symb,
        "GUBN": gubn,
        "BYMD": bymd,
        "MODP": "1",
    }
    response = requests.get(url, headers=headers, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


# 티커별로 어느 거래소에서 조회에 성공했는지 캐싱 (일봉 조회 시 찾은 값을 주봉에도 재사용)
_EXCHANGE_CACHE: dict[str, str] = {}


def fetch_prices(token: str, ticker: str, period_code: str, pages: int = 2) -> list[float]:
    """period_code: '0'=일, '1'=주, '2'=월. 최대 100건/호출이라 pages만큼 과거로 이어붙임."""

    candidates = [_EXCHANGE_CACHE[ticker]] if ticker in _EXCHANGE_CACHE else list(EXCHANGE_CANDIDATES)

    last_error: Exception | None = None
    for excd in candidates:
        try:
            bymd = ""
            dated_prices: dict[str, float] = {}
            for _ in range(pages):
                data = _dailyprice_request(token, excd, ticker, period_code, bymd)
                if data.get("rt_cd") not in (None, "0"):
                    raise RuntimeError(f"{ticker}({excd}) 조회 실패: {data.get('msg1') or data}")

                rows = data.get("output2") or []
                if not rows:
                    break

                for row in rows:
                    date = row.get("xymd") or ""
                    close = row.get("clos")
                    if date and close not in (None, ""):
                        dated_prices[date] = float(str(close).replace(",", ""))

                oldest = min((row.get("xymd") for row in rows if row.get("xymd")), default="")
                if not oldest or oldest == bymd:
                    break
                bymd = oldest
                time.sleep(REQUEST_SLEEP_SEC)

            if dated_prices:
                _EXCHANGE_CACHE[ticker] = excd
                return [price for _, price in sorted(dated_prices.items())]
        except Exception as exc:  # noqa: BLE001 - 다음 거래소로 폴백
            last_error = exc
            continue

    if last_error:
        raise last_error
    return []


def calculate_rsi(prices: Iterable[float], period: int = 14) -> float | None:
    values = list(prices)
    if len(values) <= period:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values, values[1:]):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        timeout=20,
    )
    response.raise_for_status()


def format_alerts(alerts: list[tuple[WatchItem, float | None, float | None]]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not alerts:
        return f"미국 주식 RSI 과매도 알림 ({now})\n조건 충족 종목 없음\n기준: RSI {RSI_OVERSOLD:g} 이하"

    lines = [f"미국 주식 RSI 과매도 알림 ({now})", f"기준: RSI {RSI_OVERSOLD:g} 이하", ""]
    grouped: dict[str, list[str]] = {}
    for item, daily_rsi, weekly_rsi in alerts:
        flags = []
        if daily_rsi is not None and daily_rsi <= RSI_OVERSOLD:
            flags.append(f"일봉 {daily_rsi:.1f}")
        if weekly_rsi is not None and weekly_rsi <= RSI_OVERSOLD:
            flags.append(f"주봉 {weekly_rsi:.1f}")
        exchange = _EXCHANGE_CACHE.get(item.ticker, "")
        suffix = f" [{exchange}]" if exchange else ""
        grouped.setdefault(item.theme, []).append(f"- {item.ticker}{suffix}: {', '.join(flags)}")

    for theme, rows in grouped.items():
        lines.append(f"[{theme}]")
        lines.extend(rows)
        lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# 아래는 신규 추가: 주봉 매물대 요약 (기존 RSI 과매도 스캔/알림 로직은 변경하지 않음)
# 과매도 Telegram 알림이 "실제로 전송된 직후"에만, 그 알림에 포함된 종목만 대상으로 실행된다.
# ---------------------------------------------------------------------------

def fetch_ohlcv(token: str, ticker: str, period_code: str, pages: int = 2) -> list["vp.OhlcvBar"]:
    """20일 평균 거래량 / 주봉 매물대 계산용 전체 OHLCV.
    기존 fetch_prices와 같은 엔드포인트를 별도로 호출하며(기존 함수는 변경하지 않음),
    거래소 자동탐색 로직(NAS->NYS->AMS, 캐시 재사용)도 동일하게 적용한다."""

    candidates = [_EXCHANGE_CACHE[ticker]] if ticker in _EXCHANGE_CACHE else list(EXCHANGE_CANDIDATES)

    last_error: Exception | None = None
    for excd in candidates:
        try:
            bymd = ""
            dated_bars: dict[str, vp.OhlcvBar] = {}
            for _ in range(pages):
                data = _dailyprice_request(token, excd, ticker, period_code, bymd)
                if data.get("rt_cd") not in (None, "0"):
                    raise RuntimeError(f"{ticker}({excd}) 조회 실패: {data.get('msg1') or data}")

                rows = data.get("output2") or []
                if not rows:
                    break

                for row in rows:
                    date = row.get("xymd") or ""
                    close = row.get("clos")
                    if not date or close in (None, ""):
                        continue
                    dated_bars[date] = vp.OhlcvBar(
                        date=date,
                        open=float(str(row.get("open") or close).replace(",", "")),
                        high=float(str(row.get("high") or close).replace(",", "")),
                        low=float(str(row.get("low") or close).replace(",", "")),
                        close=float(str(close).replace(",", "")),
                        volume=float(str(row.get("tvol") or 0).replace(",", "")),
                    )

                oldest = min((row.get("xymd") for row in rows if row.get("xymd")), default="")
                if not oldest or oldest == bymd:
                    break
                bymd = oldest
                time.sleep(REQUEST_SLEEP_SEC)

            if dated_bars:
                _EXCHANGE_CACHE[ticker] = excd
                return [bar for _, bar in sorted(dated_bars.items())]
        except Exception as exc:  # noqa: BLE001 - 다음 거래소로 폴백
            last_error = exc
            continue

    if last_error:
        raise last_error
    return []


def build_us_volume_summary_candidates(
    token: str,
    alerts: list[tuple[WatchItem, float | None, float | None]],
    fetch_daily_fn=None,
    fetch_weekly_fn=None,
    log_fn=print,
) -> list["vp.VolumeSummaryCandidate"]:
    """방금 발송된 미국 주식 과매도 알림(alerts)에 포함된 종목만 대상으로 후속 요약 후보를 만든다."""
    fetch_daily_fn = fetch_daily_fn or (lambda ticker: fetch_ohlcv(token, ticker, "0", pages=2))
    fetch_weekly_fn = fetch_weekly_fn or (lambda ticker: fetch_ohlcv(token, ticker, "1", pages=1))

    candidates: list[vp.VolumeSummaryCandidate] = []
    for item, _daily_rsi, _weekly_rsi in alerts:
        try:
            daily_bars = fetch_daily_fn(item.ticker)
            time.sleep(REQUEST_SLEEP_SEC)
            weekly_bars = fetch_weekly_fn(item.ticker)

            if not daily_bars:
                log_fn(f"[매물대 요약 오류] {item.ticker} 일봉 데이터 없음, 건너뜀")
                continue

            current_price = daily_bars[-1].close
            today_volume = daily_bars[-1].volume

            candidates.append(
                vp.VolumeSummaryCandidate(
                    theme=item.theme,
                    label=item.ticker,
                    market="US",
                    daily_bars=daily_bars,
                    weekly_bars=weekly_bars,
                    current_price=current_price,
                    today_volume=today_volume,
                )
            )
        except Exception as exc:  # noqa: BLE001 - 개별 종목 오류가 전체 후속 처리를 중단시키지 않음
            log_fn(f"[매물대 요약 오류] {item.ticker} 데이터 조회 실패, 건너뜀: {exc}")
            continue
        time.sleep(REQUEST_SLEEP_SEC)

    return candidates


def export_us_dashboard_data(
    alerts: list[tuple[WatchItem, float | None, float | None]],
    candidates: list["vp.VolumeSummaryCandidate"],
    rows: list["vp.SummaryRow"],
    output_dir: Path | None = None,
) -> dict:
    """대시보드(GitHub Pages)에서 읽어갈 JSON 스냅샷을 만든다.
    alerts에 포함된 종목(=방금 전송된 과매도 알림 대상)만 사용하며,
    매물대 요약(rows)은 필터를 통과한 종목만 별도 필드로 붙는다."""

    output_dir = output_dir or DASHBOARD_DATA_DIR
    candidates_by_label = {c.label: c for c in candidates}
    rows_by_label = {r.label: r for r in rows}

    stocks = []
    for item, daily_rsi, weekly_rsi in alerts:
        candidate = candidates_by_label.get(item.ticker)
        if candidate is None:
            continue

        closes_full = [bar.close for bar in candidate.daily_bars]
        rsi_full = vp.rsi_series(closes_full, RSI_PERIOD)
        bars = list(candidate.daily_bars)[-90:]
        rsi_tail = rsi_full[-90:]
        daily_bars_json = [
            {
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "rsi": rsi_tail[i],
            }
            for i, bar in enumerate(bars)
        ]

        row = rows_by_label.get(item.ticker)
        volume_summary = None
        if row is not None:
            volume_summary = {
                "avg_volume": row.avg_volume,
                "today_volume": row.today_volume,
                "volume_ratio": row.volume_ratio,
                "position": row.profile.position,
                "poc_low": row.profile.poc_low,
                "poc_high": row.profile.poc_high,
                "resistance_price": row.profile.resistance_price,
                "resistance_distance_pct": row.profile.resistance_distance_pct,
                "support_price": row.profile.support_price,
                "support_distance_pct": row.profile.support_distance_pct,
            }

        stocks.append(
            {
                "theme": item.theme,
                "code": item.ticker,
                "name": item.ticker,
                "label": item.ticker,
                "market_type": candidate.market,
                "close": candidate.current_price,
                "daily_rsi": daily_rsi,
                "weekly_rsi": weekly_rsi,
                "daily_bars": daily_bars_json,
                "volume_summary": volume_summary,
            }
        )

    payload = {
        "market": "US",
        "generated_at": datetime.now().astimezone().isoformat(),
        "stocks": stocks,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "us_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def run_us_volume_summary(
    token: str,
    alerts: list[tuple[WatchItem, float | None, float | None]],
    send_fn=None,
    log_fn=print,
    candidate_builder=None,
    dashboard_output_dir: Path | None = None,
) -> str:
    """미국 주식 RSI 과매도 알림 전송 '직후'에만 호출한다.

    - alerts(방금 전송된 과매도 알림 대상)에 포함된 종목만 사용한다.
    - 20일 평균 거래량 필터(US 기준)를 통과한 종목이 1개 이상이면 [주봉 매물대 요약] 메시지 1개를 보낸다.
    - 통과 종목이 0개면 아무것도 보내지 않는다(빈 문자열 반환).
    - 이 단계에서 발생하는 오류는 이미 전송된 과매도 알림에 영향을 주지 않는다.
    """
    send_fn = send_fn or send_telegram
    candidate_builder = candidate_builder or (lambda: build_us_volume_summary_candidates(token, alerts, log_fn=log_fn))

    try:
        candidates = candidate_builder()
        rows = vp.build_summary_rows(candidates, log_fn=log_fn)

        try:
            export_us_dashboard_data(alerts, candidates, rows, output_dir=dashboard_output_dir)
        except Exception as exc:  # noqa: BLE001 - 대시보드 export 실패가 알림 자체에 영향을 주지 않음
            log_fn(f"[대시보드 오류] 데이터 내보내기 실패: {exc}")

        message = vp.format_volume_summary("미국 종목", rows)
        if message:
            send_fn(message)
        return message
    except Exception as exc:  # noqa: BLE001 - 매물대 요약 실패가 과매도 알림 자체를 되돌리지 않음
        log_fn(f"[매물대 요약 오류] 후속 요약 처리 중 예외 발생, 건너뜀: {exc}")
        return ""


def main() -> int:
    require_config()
    items = parse_watchlist(US_WATCHLIST_PATH)
    if not items:
        raise SystemExit(f"미국 주식 종목코드가 없습니다: {US_WATCHLIST_PATH}")

    token = get_kis_token()
    alerts: list[tuple[WatchItem, float | None, float | None]] = []
    errors: list[str] = []

    for index, item in enumerate(items, start=1):
        try:
            daily_rsi = calculate_rsi(fetch_prices(token, item.ticker, "0", pages=2), RSI_PERIOD)
            time.sleep(REQUEST_SLEEP_SEC)
            weekly_rsi = calculate_rsi(fetch_prices(token, item.ticker, "1", pages=1), RSI_PERIOD)
            if (daily_rsi is not None and daily_rsi <= RSI_OVERSOLD) or (
                weekly_rsi is not None and weekly_rsi <= RSI_OVERSOLD
            ):
                alerts.append((item, daily_rsi, weekly_rsi))
        except Exception as exc:
            errors.append(f"{item.ticker} {exc}")
        time.sleep(REQUEST_SLEEP_SEC)
        print(f"[{index}/{len(items)}] {item.ticker} 완료", flush=True)

    message = format_alerts(alerts)
    if errors:
        message += "\n\n조회 실패 일부 있음:\n" + "\n".join(f"- {error}" for error in errors[:10])
        if len(errors) > 10:
            message += f"\n- 외 {len(errors) - 10}건"
    message += f"\n\n📊 대시보드: {DASHBOARD_URL}"

    send_telegram(message)
    print(message)

    # 과매도 알림이 실제로 전송된 직후에만, 그 알림에 포함된 종목만 대상으로 실행
    run_us_volume_summary(token, alerts)

    return 0


if __name__ == "__main__":
    sys.exit(main())
