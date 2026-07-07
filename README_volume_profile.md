# 주봉 매물대 요약 (신규 기능)

기존 국내/미국 RSI 과매도 Telegram 알림(`rsi_oversold_alert.py`, `us_stock_rsi_alert.py`)의
RSI 조건, 테마 분류, 스캔 로직, 과매도 알림 메시지 포맷은 **전혀 변경되지 않았습니다.**

이 기능은 각 스크립트의 `main()` 마지막에서, **과매도 알림이 실제로 Telegram으로 전송된 직후**에만
실행되는 후속 단계입니다.

## 동작 순서

1. 기존 방식 그대로 RSI 과매도 Telegram 알림을 먼저 전송한다.
2. 방금 전송한 알림에 포함된 종목만 후속 처리 대상으로 삼는다(전체 워치리스트 재스캔 아님).
3. 최근 20거래일 평균 거래량 필터를 적용한다.
   - KOSPI: 1,000,000주 이상 (`KOSPI_MIN_AVG_20D_VOLUME`)
   - KOSDAQ: 200,000주 이상 (`KOSDAQ_MIN_AVG_20D_VOLUME`)
   - US: 5,000,000주 이상 (`US_MIN_AVG_20D_VOLUME`)
   - 20거래일 데이터가 부족하거나 시장 구분이 안 되는 종목은 제외하고 로그에 기록한다.
   - 거래대금은 계산/필터에 쓰지 않는다. 당일 거래량·평균 대비 배수는 요약 메시지의 참고 정보로만 표시한다.
4. 필터를 통과한 종목의 주봉 OHLCV로 매물대(거래량 프로파일)를 계산한다.
   - 핵심 매물대(POC), 상단 저항 매물대/거리, 하단 지지 매물대/거리, 현재 위치를 산출한다.
5. 통과 종목이 1개 이상이면 테마별로 그룹화한 `[주봉 매물대 요약]` Telegram 메시지 1개를 보낸다
   (국내 실행 1회당 최대 1개, 미국 실행 1회당 최대 1개).
6. 통과 종목이 0개면 요약 메시지를 보내지 않는다.
7. 개별 종목의 데이터 부족/시장 구분 실패/API 오류는 해당 종목만 건너뛰고 로그에 남기며,
   전체 과매도 알림 작업이나 다른 종목 처리를 중단시키지 않는다.

## 새 파일

- `volume_profile.py`: 거래량 필터 + 매물대 계산 + 요약 메시지 포맷 (공용, 시장 무관 순수 로직)
- `rsi_oversold_alert.py`, `us_stock_rsi_alert.py`: 각각 후속 처리용 함수만 **추가**됨
  (`fetch_daily_ohlcv`/`fetch_weekly_ohlcv`/`fetch_kr_market_snapshot`, `fetch_ohlcv`,
  `build_*_volume_summary_candidates`, `run_*_volume_summary`). 기존 함수는 한 줄도 수정하지 않았습니다.

## 테스트

```bash
pip install -r requirements-dev.txt
pytest tests/ -q
```

- `tests/test_volume_profile.py`: 거래량 필터(KOSPI/KOSDAQ/US 기준 통과·미달), 시장 구분 실패,
  데이터 부족, 매물대 계산, 오류 발생 시 나머지 종목 처리 지속 여부
- `tests/test_kr_post_alert_flow.py`, `tests/test_us_post_alert_flow.py`:
  - 통과 종목 0개 → 요약 메시지 미전송
  - 통과 종목 여러 개 → 요약 메시지는 정확히 1개
  - RSI 과매도 알림이 항상 먼저 전송된 뒤 매물대 요약이 실행되는지 (`main()` 레벨 통합 테스트)
  - 데이터/네트워크 오류가 발생해도 전체 작업이 중단되지 않는지
