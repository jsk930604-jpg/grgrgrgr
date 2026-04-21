# 한글 시장 알림 코드 사용법

## 파일
- `market_alert_kr.ps1` (권장: PowerShell에서 바로 실행)
- `.env` (텔레그램 토큰/채팅 ID)

## 필수 입력값
- `Y10`, `Y2`: 미국채 10년/2년 금리
- `VIX`, `DXY`, `WTI`, `MOVE`: 현재값

## 선택 입력값(방향 판단용)
- `Y10Prev`, `Y2Prev`, `VIXPrev`, `DXYPrev`, `WTIPrev`, `MOVEPrev`
- 생략하면 현재값과 동일로 처리되어 방향은 `→`(변화 없음)으로 계산됩니다.

## 실행 예시
```powershell
powershell -ExecutionPolicy Bypass -File .\market_alert_kr.ps1 \
  -Y10 4.35 -Y2 3.95 -Y10Prev 4.32 -Y2Prev 3.95 \
  -VIX 16.2 -VIXPrev 17.1 \
  -DXY 103.9 -DXYPrev 104.2 \
  -WTI 80.5 -WTIPrev 80.0 \
  -MOVE 99 -MOVEPrev 101
```

## Python 자동조회(실시간)
```powershell
python .\market_regime_score.py
```
- 인자 없이 실행하면 Yahoo Finance 자동조회(`--auto`)로 동작합니다.
- 자동조회 지표: `10Y/2Y, VIX, DXY, WTI, MOVE, NAS100`
- 실행 시 텔레그램 알림이 2건 발송됩니다.
- 1건: 시장 종합 알림(점수/패턴 가이드 포함)
- 2건: 테마 RSI 과매도 알림(장마감 종가 기준, 일봉/주봉 RSI14)

## GitHub Actions 자동 실행
- 워크플로우 파일: `.github/workflows/market-alert-kr.yml`
- 실행 주기: 평일 `07:20 KST` 자동 실행 (GitHub cron은 UTC 기준)
- 수동 실행: GitHub 저장소 `Actions` 탭에서 `Market Alert KR` 선택 후 `Run workflow`

### GitHub Secrets 설정(필수)
- `Settings` → `Secrets and variables` → `Actions` → `New repository secret`
- `TELEGRAM_BOT_TOKEN` 추가
- `TELEGRAM_CHAT_ID` 추가

시크릿이 없으면 워크플로우는 실패하도록 되어 있습니다.

## 테마 RSI 대상 (총 150종목)
- 우주(50)
- 양자(50)
- 원자력(50)
- 과매도 조건: `일봉 RSI <= 30` 또는 `주봉 RSI <= 30`

## 테스트 모드(전송 없이 확인)
```powershell
powershell -ExecutionPolicy Bypass -File .\market_alert_kr.ps1 ... -DryRun
```

## 알림 해석 기준(반영됨)
- 공격 조건: `금리차↑ + VIX↓ + DXY↓`
- 방어 조건: `금리차↓ + VIX↑ + DXY↑`
- VIX 구간: `13 미만 과열`, `13~18 정상`, `18~25 불안`, `25+ 공포`
- MOVE 구간: `~100 안정`, `100~120 주의`, `120+ 위험`
- WTI: 급등/급락 같은 "급변"에 경고 가중치
