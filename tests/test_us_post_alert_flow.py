import volume_profile as vp
import us_stock_rsi_alert as us


def make_item(theme="인공지능", ticker="AAAA"):
    return us.WatchItem(theme=theme, ticker=ticker)


def make_daily_bars(volume, count=20, price=50.0):
    return [
        vp.OhlcvBar(date=f"202401{str(i+1).zfill(2)}", open=price, high=price + 1, low=price - 1, close=price, volume=volume)
        for i in range(count)
    ]


def make_weekly_bars(count=15, price=50.0):
    return [
        vp.OhlcvBar(date=f"2023{str(i+1).zfill(2)}01", open=price, high=price + 5, low=price - 5, close=price, volume=800_000)
        for i in range(count)
    ]


def test_run_us_volume_summary_sends_nothing_when_zero_pass(tmp_path):
    item = make_item()
    alerts = [(item, 20.0, None)]

    def fake_daily(ticker):
        return make_daily_bars(volume=4_999_999)  # US 기준(5,000,000) 미달

    def fake_weekly(ticker):
        return make_weekly_bars()

    sent = []
    message = us.run_us_volume_summary(
        token="dummy",
        alerts=alerts,
        send_fn=sent.append,
        log_fn=lambda _msg: None,
        candidate_builder=lambda: us.build_us_volume_summary_candidates(
            "dummy", alerts, fetch_daily_fn=fake_daily, fetch_weekly_fn=fake_weekly
        ),
        dashboard_output_dir=tmp_path,
    )
    assert message == ""
    assert sent == []


def test_run_us_volume_summary_sends_exactly_one_message_for_multiple_passes(tmp_path):
    alerts = [
        (make_item(ticker="AAAA"), 20.0, None),
        (make_item(ticker="BBBB"), 18.0, None),
    ]

    def fake_daily(ticker):
        return make_daily_bars(volume=6_000_000)  # 기준(5,000,000) 통과

    def fake_weekly(ticker):
        return make_weekly_bars()

    sent = []
    message = us.run_us_volume_summary(
        token="dummy",
        alerts=alerts,
        send_fn=sent.append,
        log_fn=lambda _msg: None,
        candidate_builder=lambda: us.build_us_volume_summary_candidates(
            "dummy", alerts, fetch_daily_fn=fake_daily, fetch_weekly_fn=fake_weekly
        ),
        dashboard_output_dir=tmp_path,
    )
    assert message != ""
    assert len(sent) == 1
    assert "AAAA" in sent[0]
    assert "BBBB" in sent[0]


def test_run_us_volume_summary_data_error_does_not_raise(tmp_path):
    item = make_item(ticker="CCCC")
    alerts = [(item, 20.0, None)]

    def raising_daily(ticker):
        raise RuntimeError("API 오류")

    def fake_weekly(ticker):
        return make_weekly_bars()

    sent = []
    message = us.run_us_volume_summary(
        token="dummy",
        alerts=alerts,
        send_fn=sent.append,
        log_fn=lambda _msg: None,
        candidate_builder=lambda: us.build_us_volume_summary_candidates(
            "dummy", alerts, fetch_daily_fn=raising_daily, fetch_weekly_fn=fake_weekly
        ),
        dashboard_output_dir=tmp_path,
    )
    assert message == ""
    assert sent == []


def test_main_sends_rsi_alert_before_volume_summary(monkeypatch):
    call_log = []

    monkeypatch.setattr(us, "KIS_APP_KEY", "key")
    monkeypatch.setattr(us, "KIS_APP_SECRET", "secret")
    monkeypatch.setattr(us, "TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(us, "TELEGRAM_CHAT_ID", "chat")

    item = make_item(ticker="DDDD")
    monkeypatch.setattr(us, "parse_watchlist", lambda path: [item])
    monkeypatch.setattr(us, "get_kis_token", lambda: "dummy-token")
    monkeypatch.setattr(us, "fetch_prices", lambda token, ticker, period, pages=1: [100.0])

    calls = {"n": 0}

    def fake_calculate_rsi(prices, period=14):
        calls["n"] += 1
        return 20.0 if calls["n"] == 1 else 50.0

    monkeypatch.setattr(us, "calculate_rsi", fake_calculate_rsi)

    def fake_send_telegram(text):
        call_log.append(("telegram", text))

    monkeypatch.setattr(us, "send_telegram", fake_send_telegram)

    def fake_run_us_volume_summary(token, alerts, **kwargs):
        call_log.append(("volume_summary", None))
        return ""

    monkeypatch.setattr(us, "run_us_volume_summary", fake_run_us_volume_summary)

    def fake_export_all(rows, fetch_daily_fn, **kwargs):
        call_log.append(("all_data", [r[0].ticker for r in rows]))
        return {}

    monkeypatch.setattr(us, "export_us_all_data", fake_export_all)

    exit_code = us.main()

    assert exit_code == 0
    assert len(call_log) == 3
    assert call_log[0][0] == "telegram"
    assert "RSI 과매도 알림" in call_log[0][1]
    assert call_log[1][0] == "volume_summary"
    assert call_log[2][0] == "all_data"



def test_export_us_all_data_merges_themes_and_skips_failures(tmp_path):
    a = us.WatchItem(theme="우주항공", ticker="LUNR")
    b = us.WatchItem(theme="UAM", ticker="LUNR")
    c = us.WatchItem(theme="원자력", ticker="SMR")
    d = us.WatchItem(theme="로봇", ticker="BAD")
    bars = [
        vp.OhlcvBar(date=f"2024{str(1 + k // 28).zfill(2)}{str(1 + k % 28).zfill(2)}", open=10 + k * 0.1, high=10.5 + k * 0.1, low=9.8 + k * 0.1, close=10.2 + k * 0.1, volume=1000 + k)
        for k in range(40)
    ]

    def fetch(t):
        if t == "BAD":
            raise RuntimeError("조회 실패")
        return list(reversed(bars))  # 순서가 뒤집혀 와도 날짜순으로 정리돼야 함

    payload = us.export_us_all_data([(a, 25.0, 40.0), (b, 25.0, 40.0), (c, 55.0, 60.0), (d, None, None)], fetch, output_dir=tmp_path, log_fn=lambda m: None, sleep_sec=0)

    assert (tmp_path / "us_all.json").exists()
    by = {s["code"]: s for s in payload["stocks"]}
    assert by["LUNR"]["themes"] == ["우주항공", "UAM"]
    assert by["LUNR"]["oversold"] is True
    assert by["SMR"]["daily_bars"][0]["date"] < by["SMR"]["daily_bars"][-1]["date"]
    assert by["SMR"]["daily_bars"][-1]["rsi"] is not None
    assert payload["failed"] == ["BAD"]


def test_get_kis_token_retries_once_after_403(tmp_path, monkeypatch):
    calls = {"n": 0}

    class R:
        def __init__(self, code):
            self.status_code = code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

        def json(self):
            return {"access_token": "tok", "expires_in": 86400}

    def fake_post(*a, **k):
        calls["n"] += 1
        return R(403 if calls["n"] == 1 else 200)

    monkeypatch.setattr(us, "TOKEN_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(us.requests, "post", fake_post)
    assert us.get_kis_token() == "tok"
    assert calls["n"] == 2
