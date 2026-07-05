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

    send_telegram(message)
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
