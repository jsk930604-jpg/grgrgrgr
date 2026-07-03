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
TOKEN_CACHE_PATH = BASE_DIR / ".kis_token_cache.json"


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
WATCHLIST_PATH = Path(
    ENV.get("WATCHLIST_PATH", str(Path.home() / "Desktop" / "테마별 종목코드.txt"))
).expanduser()


@dataclass(frozen=True)
class WatchItem:
    theme: str
    code: str
    name: str


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
        raise SystemExit(f".env에 필수 값이 없습니다: {', '.join(missing)}")


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
        raise SystemExit(f"종목코드 파일을 찾을 수 없습니다: {path}")

    current_theme = "미분류"
    found: dict[tuple[str, str], WatchItem] = {}
    for raw_line in read_watchlist_text(path).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        theme_match = re.fullmatch(r"\((.+?)\)", line)
        if theme_match:
            current_theme = theme_match.group(1).strip()
            continue

        for code in re.findall(r"(?<!\d)(\d{6})(?!\d)", line):
            name = re.sub(r"(?<!\d)\d{6}(?!\d)", "", line)
            name = re.sub(r"\b(코스피|코스닥|KOSPI|KOSDAQ)\b", "", name, flags=re.IGNORECASE)
            name = re.sub(r"\s+", " ", name).strip(" -\t")
            if not name:
                name = code
            found.setdefault((current_theme, code), WatchItem(current_theme, code, name))

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


def fetch_prices(token: str, code: str, period_code: str) -> list[float]:
    end = datetime.now()
    start = end - timedelta(days=500 if period_code == "D" else 1200)
    url = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": "FHKST03010100",
        "custtype": "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE": period_code,
        "FID_ORG_ADJ_PRC": "0",
    }
    response = requests.get(url, headers=headers, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()
    if data.get("rt_cd") not in (None, "0"):
        raise RuntimeError(f"{code} 조회 실패: {data.get('msg1') or data}")

    rows = data.get("output2") or []
    dated_prices: list[tuple[str, float]] = []
    for row in rows:
        close = row.get("stck_clpr")
        date = row.get("stck_bsop_date") or ""
        if close:
            dated_prices.append((date, float(str(close).replace(",", ""))))

    return [price for _, price in sorted(dated_prices, key=lambda item: item[0])]


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
        return f"RSI 과매도 알림 ({now})\n조건 충족 종목 없음\n기준: RSI {RSI_OVERSOLD:g} 이하"

    lines = [f"RSI 과매도 알림 ({now})", f"기준: RSI {RSI_OVERSOLD:g} 이하", ""]
    grouped: dict[str, list[str]] = {}
    for item, daily_rsi, weekly_rsi in alerts:
        flags = []
        if daily_rsi is not None and daily_rsi <= RSI_OVERSOLD:
            flags.append(f"일봉 {daily_rsi:.1f}")
        if weekly_rsi is not None and weekly_rsi <= RSI_OVERSOLD:
            flags.append(f"주봉 {weekly_rsi:.1f}")
        grouped.setdefault(item.theme, []).append(f"- {item.name} ({item.code}): {', '.join(flags)}")

    for theme, rows in grouped.items():
        lines.append(f"[{theme}]")
        lines.extend(rows)
        lines.append("")
    return "\n".join(lines).strip()


def main() -> int:
    require_config()
    items = parse_watchlist(WATCHLIST_PATH)
    if not items:
        raise SystemExit(f"종목코드가 없습니다: {WATCHLIST_PATH}")

    token = get_kis_token()
    alerts: list[tuple[WatchItem, float | None, float | None]] = []
    errors: list[str] = []

    for index, item in enumerate(items, start=1):
        try:
            daily_rsi = calculate_rsi(fetch_prices(token, item.code, "D"), RSI_PERIOD)
            time.sleep(REQUEST_SLEEP_SEC)
            weekly_rsi = calculate_rsi(fetch_prices(token, item.code, "W"), RSI_PERIOD)
            if (daily_rsi is not None and daily_rsi <= RSI_OVERSOLD) or (
                weekly_rsi is not None and weekly_rsi <= RSI_OVERSOLD
            ):
                alerts.append((item, daily_rsi, weekly_rsi))
        except Exception as exc:
            errors.append(f"{item.name}({item.code}) {exc}")
        time.sleep(REQUEST_SLEEP_SEC)
        print(f"[{index}/{len(items)}] {item.code} 완료", flush=True)

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
