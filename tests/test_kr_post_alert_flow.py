import volume_profile as vp
import rsi_oversold_alert as kr


def make_item(theme="원자력", code="000001", name="테스트종목"):
    return kr.WatchItem(theme=theme, code=code, name=name)


def make_daily_bars(volume, count=20):
    return [
        vp.OhlcvBar(date=f"202401{str(i+1).zfill(2)}", open=100, high=101, low=99, close=100, volume=volume)
        for i in range(count)
    ]


def make_weekly_bars(count=15):
    return [
        vp.OhlcvBar(date=f"2023{str(i+1).zfill(2)}01", open=100, high=105, low=95, close=100, volume=500_000)
        for i in range(count)
    ]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_kr_market_snapshot_recognizes_english_market_name(monkeypatch):
    # 실제 KIS API는 rprs_mrkt_kor_name을 "코스피"가 아니라 "KOSPI200" 같은 영문으로 주기도 한다.
    payload = {
        "rt_cd": "0",
        "output": {"rprs_mrkt_kor_name": "KOSPI200", "stck_prpr": "70000", "acml_vol": "12345678"},
    }
    monkeypatch.setattr(kr.requests, "get", lambda *a, **k: _FakeResponse(payload))
    market, price, volume = kr.fetch_kr_market_snapshot("dummy-token", "005930")
    assert market == "KOSPI"
    assert price == 70000.0
    assert volume == 12345678.0


def test_fetch_kr_market_snapshot_recognizes_kosdaq_english_name(monkeypatch):
    payload = {
        "rt_cd": "0",
        "output": {"rprs_mrkt_kor_name": "KOSDAQ", "stck_prpr": "5000", "acml_vol": "999999"},
    }
    monkeypatch.setattr(kr.requests, "get", lambda *a, **k: _FakeResponse(payload))
    market, price, volume = kr.fetch_kr_market_snapshot("dummy-token", "000002")
    assert market == "KOSDAQ"


def test_fetch_kr_market_snapshot_recognizes_korean_market_name(monkeypatch):
    payload = {
        "rt_cd": "0",
        "output": {"rprs_mrkt_kor_name": "코스닥", "stck_prpr": "5000", "acml_vol": "999999"},
    }
    monkeypatch.setattr(kr.requests, "get", lambda *a, **k: _FakeResponse(payload))
    market, _price, _volume = kr.fetch_kr_market_snapshot("dummy-token", "000003")
    assert market == "KOSDAQ"


def test_run_kr_volume_summary_sends_nothing_when_zero_pass(monkeypatch):
    item = make_item()
    alerts = [(item, 20.0, None)]

    def fake_snapshot(code):
        return "KOSPI", 100.0, 500_000

    def fake_daily(code):
        return make_daily_bars(volume=500_000)  # KOSPI 기준(1,000,000) 미달

    def fake_weekly(code):
        return make_weekly_bars()

    sent = []
    message = kr.run_kr_volume_summary(
        token="dummy",
        alerts=alerts,
        send_fn=sent.append,
        log_fn=lambda _msg: None,
        candidate_builder=lambda: kr.build_kr_volume_summary_candidates(
            "dummy", alerts, fetch_daily_fn=fake_daily, fetch_weekly_fn=fake_weekly, fetch_snapshot_fn=fake_snapshot
        ),
    )
    assert message == ""
    assert sent == []


def test_run_kr_volume_summary_sends_exactly_one_message_for_multiple_passes(monkeypatch):
    items = [
        (make_item(code="000001", name="A"), 20.0, None),
        (make_item(code="000002", name="B"), 18.0, None),
    ]

    def fake_snapshot(code):
        return "KOSPI", 100.0, 2_000_000

    def fake_daily(code):
        return make_daily_bars(volume=2_000_000)  # 기준(1,000,000) 통과

    def fake_weekly(code):
        return make_weekly_bars()

    sent = []
    message = kr.run_kr_volume_summary(
        token="dummy",
        alerts=items,
        send_fn=sent.append,
        log_fn=lambda _msg: None,
        candidate_builder=lambda: kr.build_kr_volume_summary_candidates(
            "dummy", items, fetch_daily_fn=fake_daily, fetch_weekly_fn=fake_weekly, fetch_snapshot_fn=fake_snapshot
        ),
    )
    assert message != ""
    assert len(sent) == 1  # 통과 종목이 여러 개여도 요약 메시지는 최대 1개
    assert "A(000001)" in sent[0]
    assert "B(000002)" in sent[0]


def test_run_kr_volume_summary_excludes_unknown_market(monkeypatch):
    item = make_item(code="000003", name="C")
    alerts = [(item, 20.0, None)]
    logs = []

    def fake_snapshot(code):
        return None, 100.0, 2_000_000  # 시장 구분 실패

    def fake_daily(code):
        return make_daily_bars(volume=2_000_000)

    def fake_weekly(code):
        return make_weekly_bars()

    message = kr.run_kr_volume_summary(
        token="dummy",
        alerts=alerts,
        send_fn=lambda _m: None,
        log_fn=logs.append,
        candidate_builder=lambda: kr.build_kr_volume_summary_candidates(
            "dummy", alerts, fetch_daily_fn=fake_daily, fetch_weekly_fn=fake_weekly, fetch_snapshot_fn=fake_snapshot
        ),
    )
    assert message == ""
    assert any("시장 구분 확인 불가" in log for log in logs)


def test_run_kr_volume_summary_data_error_does_not_raise(monkeypatch):
    item = make_item(code="000004", name="D")
    alerts = [(item, 20.0, None)]

    def raising_daily(code):
        raise RuntimeError("API 오류")

    def fake_weekly(code):
        return make_weekly_bars()

    def fake_snapshot(code):
        return "KOSPI", 100.0, 2_000_000

    sent = []
    # 예외가 발생해도 run_kr_volume_summary 자체는 예외를 던지지 않는다.
    message = kr.run_kr_volume_summary(
        token="dummy",
        alerts=alerts,
        send_fn=sent.append,
        log_fn=lambda _msg: None,
        candidate_builder=lambda: kr.build_kr_volume_summary_candidates(
            "dummy", alerts, fetch_daily_fn=raising_daily, fetch_weekly_fn=fake_weekly, fetch_snapshot_fn=fake_snapshot
        ),
    )
    assert message == ""
    assert sent == []


def test_main_sends_rsi_alert_before_volume_summary(monkeypatch, tmp_path):
    # main() 실행 시: RSI 과매도 알림이 항상 먼저 전송되고, 그 다음 매물대 요약이 시도된다.
    call_log = []

    monkeypatch.setattr(kr, "KIS_APP_KEY", "key")
    monkeypatch.setattr(kr, "KIS_APP_SECRET", "secret")
    monkeypatch.setattr(kr, "TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(kr, "TELEGRAM_CHAT_ID", "chat")

    item = make_item(code="000005", name="E")
    monkeypatch.setattr(kr, "parse_watchlist", lambda path: [item])
    monkeypatch.setattr(kr, "get_kis_token", lambda: "dummy-token")

    # 첫 번째 fetch_prices 호출(일봉)은 과매도(RSI<=30)로 판정되도록 낮은 값을 주고,
    # calculate_rsi를 직접 스텁 처리해 단순/결정적으로 만든다.
    monkeypatch.setattr(kr, "fetch_prices", lambda token, code, period: [100.0])

    calls = {"n": 0}

    def fake_calculate_rsi(prices, period=14):
        calls["n"] += 1
        return 20.0 if calls["n"] == 1 else 50.0

    monkeypatch.setattr(kr, "calculate_rsi", fake_calculate_rsi)

    def fake_send_telegram(text):
        call_log.append(("telegram", text))

    monkeypatch.setattr(kr, "send_telegram", fake_send_telegram)

    def fake_run_kr_volume_summary(token, alerts, **kwargs):
        call_log.append(("volume_summary", None))
        return ""

    monkeypatch.setattr(kr, "run_kr_volume_summary", fake_run_kr_volume_summary)

    exit_code = kr.main()

    assert exit_code == 0
    assert len(call_log) == 2
    assert call_log[0][0] == "telegram"
    assert "RSI 과매도 알림" in call_log[0][1]
    assert call_log[1][0] == "volume_summary"
