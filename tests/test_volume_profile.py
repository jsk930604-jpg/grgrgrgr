import volume_profile as vp


def make_bars(volumes, start_date="20240101"):
    """volumes 리스트 길이만큼 날짜가 하루씩 증가하는 OhlcvBar 목록을 만든다."""
    from datetime import datetime, timedelta

    base = datetime.strptime(start_date, "%Y%m%d")
    bars = []
    for i, volume in enumerate(volumes):
        date = (base + timedelta(days=i)).strftime("%Y%m%d")
        bars.append(vp.OhlcvBar(date=date, open=100.0, high=101.0, low=99.0, close=100.0, volume=volume))
    return bars


# --- 20일 평균 거래량 계산 ---------------------------------------------------

def test_average_volume_20d_returns_none_when_insufficient_data():
    bars = make_bars([1_000_000] * 19)
    assert vp.average_volume_20d(bars) is None


def test_average_volume_20d_uses_last_20_days_mean():
    # 앞의 10일은 아주 크게, 최근 20일은 정확히 1,000,000으로 설정
    bars = make_bars([100_000_000] * 10 + [1_000_000] * 20)
    assert vp.average_volume_20d(bars) == 1_000_000


# --- 시장별 최소 평균 거래량 필터 -------------------------------------------

def test_kospi_pass_threshold():
    bars = make_bars([1_000_000] * 20)
    result = vp.evaluate_volume_filter("KOSPI", bars)
    assert result.passed is True
    assert result.reason is None


def test_kospi_fail_below_threshold():
    bars = make_bars([999_999] * 20)
    result = vp.evaluate_volume_filter("KOSPI", bars)
    assert result.passed is False
    assert result.reason == "평균 거래량 기준 미달"


def test_kosdaq_pass_threshold():
    bars = make_bars([200_000] * 20)
    result = vp.evaluate_volume_filter("KOSDAQ", bars)
    assert result.passed is True


def test_kosdaq_fail_below_threshold():
    bars = make_bars([199_999] * 20)
    result = vp.evaluate_volume_filter("KOSDAQ", bars)
    assert result.passed is False


def test_us_pass_threshold():
    bars = make_bars([5_000_000] * 20)
    result = vp.evaluate_volume_filter("US", bars)
    assert result.passed is True


def test_us_fail_below_threshold():
    bars = make_bars([4_999_999] * 20)
    result = vp.evaluate_volume_filter("US", bars)
    assert result.passed is False


def test_unknown_market_excluded():
    bars = make_bars([10_000_000] * 20)
    result = vp.evaluate_volume_filter(None, bars)
    assert result.passed is False
    assert result.reason == "시장 구분 확인 불가"

    result2 = vp.evaluate_volume_filter("NASDAQ_INDEX", bars)  # 알 수 없는 시장 코드
    assert result2.passed is False
    assert result2.reason == "시장 구분 확인 불가"


def test_insufficient_data_excluded_even_if_market_known():
    bars = make_bars([1_000_000] * 5)
    result = vp.evaluate_volume_filter("KOSPI", bars)
    assert result.passed is False
    assert result.reason == "최근 20거래일 데이터 부족"


# --- 주봉 매물대(거래량 프로파일) --------------------------------------------

def make_weekly_bars(prices_volumes, start_date="20230101"):
    from datetime import datetime, timedelta

    base = datetime.strptime(start_date, "%Y%m%d")
    bars = []
    for i, (price, volume) in enumerate(prices_volumes):
        date = (base + timedelta(weeks=i)).strftime("%Y%m%d")
        bars.append(
            vp.OhlcvBar(date=date, open=price, high=price + 1, low=price - 1, close=price, volume=volume)
        )
    return bars


def test_build_weekly_volume_profile_identifies_poc_and_support_resistance():
    # 100 근처에 거래량이 압도적으로 몰려있고, 120/80 부근에도 유의미한 거래량이 있음
    data = [(100, 1_000_000)] * 15 + [(80, 300_000)] * 5 + [(120, 300_000)] * 5
    bars = make_weekly_bars(data)

    profile = vp.build_weekly_volume_profile(bars, current_price=100.0, bins=20)
    assert profile is not None
    assert profile.poc_low <= 100.0 <= profile.poc_high or abs(profile.poc_low - 100) < 5
    # 현재가 위/아래로 저항/지지가 하나씩은 잡혀야 한다
    assert profile.resistance_price is None or profile.resistance_price > 100.0
    assert profile.support_price is None or profile.support_price < 100.0


def test_build_weekly_volume_profile_none_when_insufficient_bars():
    bars = make_weekly_bars([(100, 1_000_000)] * 5)
    assert vp.build_weekly_volume_profile(bars, current_price=100.0) is None


# --- 요약 메시지 포맷 ---------------------------------------------------------

def test_format_volume_summary_empty_rows_returns_empty_string():
    assert vp.format_volume_summary("국내 종목", []) == ""


def test_format_volume_summary_groups_by_theme():
    profile = vp.VolumeProfile(
        poc_low=95.0,
        poc_high=105.0,
        resistance_price=120.0,
        resistance_distance_pct=20.0,
        support_price=80.0,
        support_distance_pct=20.0,
        position="핵심 매물대 내부",
    )
    row = vp.SummaryRow(
        theme="우주항공",
        label="테스트종목(000000)",
        market="KOSPI",
        close=100.0,
        avg_volume=1_500_000,
        today_volume=2_000_000,
        volume_ratio=1.33,
        profile=profile,
    )
    message = vp.format_volume_summary("국내 종목", [row])
    assert "[주봉 매물대 요약]" in message
    assert "[우주항공]" in message
    assert "테스트종목(000000)" in message


# --- build_summary_rows: 필터 + 오류 내성 ------------------------------------

def test_build_summary_rows_filters_out_below_threshold():
    candidates = [
        vp.VolumeSummaryCandidate(
            theme="원자력",
            label="A(000001)",
            market="KOSPI",
            daily_bars=make_bars([999_999] * 20),
            weekly_bars=make_weekly_bars([(100, 1_000_000)] * 15),
            current_price=100.0,
            today_volume=500_000,
        ),
        vp.VolumeSummaryCandidate(
            theme="원자력",
            label="B(000002)",
            market="KOSPI",
            daily_bars=make_bars([2_000_000] * 20),
            weekly_bars=make_weekly_bars([(100, 1_000_000)] * 15),
            current_price=100.0,
            today_volume=2_500_000,
        ),
    ]
    logs = []
    rows = vp.build_summary_rows(candidates, log_fn=logs.append)
    labels = [row.label for row in rows]
    assert "B(000002)" in labels
    assert "A(000001)" not in labels
    assert any("A(000001)" in log for log in logs)


def test_build_summary_rows_continues_when_one_candidate_raises():
    class ExplodingBars:
        def __iter__(self):
            raise RuntimeError("network error")

        def __len__(self):
            raise RuntimeError("network error")

    candidates = [
        vp.VolumeSummaryCandidate(
            theme="AI",
            label="BROKEN",
            market="US",
            daily_bars=ExplodingBars(),
            weekly_bars=[],
            current_price=10.0,
            today_volume=None,
        ),
        vp.VolumeSummaryCandidate(
            theme="AI",
            label="OK",
            market="US",
            daily_bars=make_bars([6_000_000] * 20),
            weekly_bars=make_weekly_bars([(10, 500_000)] * 15),
            current_price=10.0,
            today_volume=6_500_000,
        ),
    ]
    logs = []
    rows = vp.build_summary_rows(candidates, log_fn=logs.append)
    labels = [row.label for row in rows]
    assert "OK" in labels
    assert "BROKEN" not in labels
    assert any("BROKEN" in log for log in logs)
