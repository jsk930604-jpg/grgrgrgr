param(
    [Parameter(Mandatory = $true)][double]$Y10,
    [Parameter(Mandatory = $true)][double]$Y2,
    [Parameter(Mandatory = $true)][double]$VIX,
    [Parameter(Mandatory = $true)][double]$DXY,
    [Parameter(Mandatory = $true)][double]$WTI,
    [Parameter(Mandatory = $true)][double]$MOVE,

    [double]$Y10Prev = [double]::NaN,
    [double]$Y2Prev = [double]::NaN,
    [double]$VIXPrev = [double]::NaN,
    [double]$DXYPrev = [double]::NaN,
    [double]$WTIPrev = [double]::NaN,
    [double]$MOVEPrev = [double]::NaN,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Load-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }

    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }

        $parts = $trimmed.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim() -replace '^["'']|["'']$', ''

        if ($key -and -not [string]::IsNullOrWhiteSpace($value) -and -not (Test-Path "Env:$key")) {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

function Get-Trend {
    param(
        [double]$Current,
        [double]$Previous,
        [double]$Threshold
    )

    $diff = $Current - $Previous
    if ($diff -gt $Threshold) { return "up" }
    if ($diff -lt (-1 * $Threshold)) { return "down" }
    return "flat"
}

function Get-Arrow {
    param([string]$Trend)
    switch ($Trend) {
        "up" { "↑" }
        "down" { "↓" }
        default { "→" }
    }
}

function Get-SpreadZone {
    param([double]$Spread)
    if ($Spread -ge 1.0) { return "과열 후반" }
    if ($Spread -ge 0.3) { return "정상 상승" }
    if ($Spread -gt 0) { return "초입/둔화" }
    return "역전(위험)"
}

function Get-VixZone {
    param([double]$Value)
    if ($Value -lt 13) { return "과열(주의)" }
    if ($Value -lt 18) { return "정상(좋음)" }
    if ($Value -lt 25) { return "불안" }
    return "공포(기회)"
}

function Get-MoveZone {
    param([double]$Value)
    if ($Value -le 100) { return "안정" }
    if ($Value -le 120) { return "주의" }
    return "위험"
}

function Get-OilState {
    param(
        [double]$Current,
        [double]$Previous
    )

    if ($Previous -eq 0) {
        return @{ Label = "안정"; ChangePct = 0.0 }
    }

    $pct = (($Current - $Previous) / $Previous) * 100
    if ($pct -ge 2.0) {
        return @{ Label = "급등"; ChangePct = $pct }
    }
    if ($pct -le -2.0) {
        return @{ Label = "급락"; ChangePct = $pct }
    }
    return @{ Label = "안정"; ChangePct = $pct }
}

function Get-Pattern {
    param(
        [double]$Spread,
        [string]$SpreadTrend,
        [string]$VixTrend
    )

    if ($Spread -le 0 -and $VixTrend -eq "up") {
        return @{ Pattern = "하락 직전"; Strategy = "방어" }
    }
    if ($Spread -le 0 -and $VixTrend -eq "down") {
        return @{ Pattern = "후반 상승"; Strategy = "단타" }
    }
    if ($SpreadTrend -eq "up" -and $VixTrend -eq "down") {
        return @{ Pattern = "상승장 초입"; Strategy = "적극" }
    }
    if ($SpreadTrend -eq "up" -and $VixTrend -eq "up") {
        return @{ Pattern = "흔들리는 상승장"; Strategy = "눌림 매수" }
    }
    if ($SpreadTrend -eq "down" -and $VixTrend -eq "up") {
        return @{ Pattern = "하락장"; Strategy = "회피" }
    }
    if ($SpreadTrend -eq "down" -and $VixTrend -eq "down") {
        return @{ Pattern = "후반 상승(위험)"; Strategy = "짧게" }
    }

    return @{ Pattern = "혼조"; Strategy = "중립" }
}

if ([double]::IsNaN($Y10Prev)) { $Y10Prev = $Y10 }
if ([double]::IsNaN($Y2Prev)) { $Y2Prev = $Y2 }
if ([double]::IsNaN($VIXPrev)) { $VIXPrev = $VIX }
if ([double]::IsNaN($DXYPrev)) { $DXYPrev = $DXY }
if ([double]::IsNaN($WTIPrev)) { $WTIPrev = $WTI }
if ([double]::IsNaN($MOVEPrev)) { $MOVEPrev = $MOVE }

$spread = $Y10 - $Y2
$spreadPrev = $Y10Prev - $Y2Prev

$spreadTrend = Get-Trend -Current $spread -Previous $spreadPrev -Threshold 0.03
$vixTrend = Get-Trend -Current $VIX -Previous $VIXPrev -Threshold 0.30
$dxyTrend = Get-Trend -Current $DXY -Previous $DXYPrev -Threshold 0.15
$moveTrend = Get-Trend -Current $MOVE -Previous $MOVEPrev -Threshold 1.5

$oil = Get-OilState -Current $WTI -Previous $WTIPrev
$patternResult = Get-Pattern -Spread $spread -SpreadTrend $spreadTrend -VixTrend $vixTrend

$attackOk = ($spreadTrend -eq "up" -and $vixTrend -eq "down" -and $dxyTrend -eq "down")
$defendOk = ($spreadTrend -eq "down" -and $vixTrend -eq "up" -and $dxyTrend -eq "up")

$bullScore = 0
$riskScore = 0

if ($spread -gt 0 -and $spreadTrend -eq "up") { $bullScore++ }
if ($vixTrend -eq "down") { $bullScore++ }
if ($dxyTrend -eq "down") { $bullScore++ }
if ($oil.Label -eq "안정") { $bullScore++ }
if ($MOVE -le 100 -and $moveTrend -ne "up") { $bullScore++ }

if ($spread -le 0) { $riskScore += 2 }
if ($spreadTrend -eq "down") { $riskScore++ }
if ($vixTrend -eq "up") { $riskScore++ }
if ($dxyTrend -eq "up") { $riskScore++ }
if ($oil.Label -eq "급등") { $riskScore++ }
if ($MOVE -gt 120 -or $moveTrend -eq "up") { $riskScore++ }

if ($riskScore -ge 4 -or ($spread -le 0 -and $vixTrend -eq "up")) {
    $marketState = "⚠️ 위험 장"
    $stance = "방어"
}
elseif ($bullScore -ge 4 -and $oil.Label -ne "급등" -and $MOVE -le 120) {
    $marketState = "🔥 좋은 장"
    $stance = "공격"
}
else {
    $marketState = "➖ 중립/혼조"
    $stance = $patternResult.Strategy
}

if ($attackOk) { $stance = "공격" }
if ($defendOk) { $stance = "방어" }

$nowKst = (Get-Date).ToUniversalTime().AddHours(9)
$timestamp = $nowKst.ToString("yyyy-MM-dd HH:mm 'KST'")

$message = @(
    "📊 시장 종합 알림 ($timestamp)",
    "종합 판정: $marketState",
    "매매 스탠스: $stance",
    "",
    "[핵심 조건]",
    "- 공격 조건(금리차↑ + VIX↓ + DXY↓): $(if ($attackOk) { '충족' } else { '미충족' })",
    "- 방어 조건(금리차↓ + VIX↑ + DXY↑): $(if ($defendOk) { '충족' } else { '미충족' })",
    "",
    "[추가 지표 요약]",
    "- VIX: $($VIX.ToString('F2'))점 ($(Get-VixZone -Value $VIX)) $(Get-Arrow -Trend $vixTrend)",
    "- 금리차(10Y-2Y): $($spread.ToString('F2')) ($(Get-SpreadZone -Spread $spread)) $(Get-Arrow -Trend $spreadTrend)",
    "- DXY: $($DXY.ToString('F2')) $(Get-Arrow -Trend $dxyTrend)",
    "- MOVE: $($MOVE.ToString('F2')) ($(Get-MoveZone -Value $MOVE)) $(Get-Arrow -Trend $moveTrend)",
    "- WTI: $($WTI.ToString('F2'))달러 ($($oil.Label), $($oil.ChangePct.ToString('+0.00;-0.00;0.00'))%)",
    "",
    "[패턴] $($patternResult.Pattern) → 전략: $($patternResult.Strategy)",
    "[점수] 상승 ${bullScore}점 / 위험 ${riskScore}점",
    "",
    "※ 참고: 본 알림은 보조 지표 해석용이며 투자 책임은 본인에게 있습니다."
) -join "`n"

$message

if ($DryRun) {
    Write-Host "`n[dry-run] 텔레그램 전송은 생략했습니다."
    exit 0
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Load-DotEnv -Path (Join-Path $scriptDir ".env")

$token = $env:TELEGRAM_BOT_TOKEN
$chatId = $env:TELEGRAM_CHAT_ID

if ([string]::IsNullOrWhiteSpace($token) -or [string]::IsNullOrWhiteSpace($chatId)) {
    throw "텔레그램 전송을 위해 .env의 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID가 필요합니다."
}

$uri = "https://api.telegram.org/bot$token/sendMessage"
$body = @{
    chat_id = $chatId
    text = $message
    disable_web_page_preview = "true"
}

$response = Invoke-RestMethod -Method Post -Uri $uri -Body $body
if (-not $response.ok) {
    throw "텔레그램 API 응답 오류: $($response | ConvertTo-Json -Depth 5 -Compress)"
}

Write-Host "`n텔레그램 전송 완료"
