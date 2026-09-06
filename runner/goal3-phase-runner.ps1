[CmdletBinding()]
param(
    [ValidateSet('run', 'status')]
    [string]$Action = 'status',
    [string]$BoundaryManifest = 'artifacts/campaigns/goal3-ablation-v2.json',
    [string]$OneDayScreenManifest = 'artifacts/campaigns/goal3-screen-1d-v1.json',
    [string]$CoreScreenManifest = 'artifacts/campaigns/goal3-screen-5d20d-v1.json',
    [string]$OneDayDecisionArtifact = 'artifacts/decisions/goal3-one-day-screen-v1.json',
    [string]$FiveDayAblationManifest = 'artifacts/campaigns/goal3-ablation-5d-v1.json',
    [string]$TwentyDayAblationManifest = 'artifacts/campaigns/goal3-ablation-20d-v1.json',
    [string]$OneDayAblationManifest = 'artifacts/campaigns/goal3-ablation-1d-v1.json',
    [string]$BuildManifest = 'data/live/builds/production/2fc936a7ca9b939d8016ad3c5efea17c53ffd5264d5ece398a8329bf2f2dfe5f/2fc936a7ca9b939d8016ad3c5efea17c53ffd5264d5ece398a8329bf2f2dfe5f.json',
    [string]$CodeCommit = '000812e09be3ceef5491aab073b47778a757c165',
    [string]$ExperimentRegistry = 'artifacts/experiments/advanced.jsonl',
    [string]$LogRoot = 'artifacts/logs/goal3-phased'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ResearchRunner = (Resolve-Path (Join-Path $PSScriptRoot 'research-runner.ps1')).Path
$WindowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

function Resolve-ProjectPath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $PathValue))
}

function Write-PhaseEvent([string]$Root, [string]$Event, [string]$Detail) {
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    $record = [ordered]@{
        at = [DateTimeOffset]::UtcNow.ToString('o')
        event = $Event
        detail = $Detail
        locked_holdout_accessed = $false
    }
    Add-Content -LiteralPath (Join-Path $Root 'phase-runner.jsonl') -Value ($record | ConvertTo-Json -Compress) -Encoding UTF8
}

function Get-ManifestPayload([string]$PathValue) {
    if (-not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
        return $null
    }
    return Get-Content -LiteralPath $PathValue -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-AllSucceeded($Payload) {
    if ($null -eq $Payload) {
        return $false
    }
    return @($Payload.batches | Where-Object { [string]$_.status -ne 'SUCCEEDED' }).Count -eq 0
}

function Get-BoundaryBatch($Payload) {
    if ($null -eq $Payload) {
        throw 'boundary campaign manifest is missing'
    }
    $batch = @($Payload.batches | Where-Object {
        [string]$_.batch_id -eq 'h1-lightgbm-s17'
    }) | Select-Object -First 1
    if ($null -eq $batch) {
        throw 'boundary batch h1-lightgbm-s17 is missing'
    }
    return $batch
}

function Get-OneDayDecision($OneDayPayload) {
    if (-not (Test-Path -LiteralPath $OneDayDecisionPath -PathType Leaf)) {
        return $null
    }
    try {
        $decision = Get-Content -LiteralPath $OneDayDecisionPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
    } catch {
        throw 'one-day screen decision artifact is missing or invalid'
    }
    if ([string]$decision.schema_version -ne 'goal3-one-day-screen-decision-v1') {
        throw 'one-day screen decision schema mismatch'
    }
    if ([string]$decision.criteria_version -ne 'D080') {
        throw 'one-day screen decision criteria mismatch'
    }
    if ([string]$decision.one_day_campaign_id -ne [string]$OneDayPayload.campaign_id) {
        throw 'one-day screen decision campaign mismatch'
    }
    if ([string]$decision.build_id -ne [string]$OneDayPayload.build_id) {
        throw 'one-day screen decision build mismatch'
    }
    if ([string]$decision.code_commit -ne [string]$OneDayPayload.code_commit) {
        throw 'one-day screen decision code commit mismatch'
    }
    if ([bool]$decision.locked_holdout_accessed) {
        throw 'one-day screen decision must not access locked holdout'
    }
    $expectedReportIds = @(
        $OneDayPayload.batches |
            ForEach-Object { [string]$_.report_id } |
            Where-Object { $_ } |
            Sort-Object
    )
    $observedReportIds = @($decision.screen_report_ids | ForEach-Object { [string]$_ } | Sort-Object)
    if ($expectedReportIds.Count -ne @($OneDayPayload.batches).Count) {
        throw 'one-day screen decision requires every completed screen report'
    }
    if (@(Compare-Object $expectedReportIds $observedReportIds).Count -ne 0) {
        throw 'one-day screen decision report identity mismatch'
    }
    $allGatesPassed = (
        [bool]$decision.gates.stable_across_seeds_and_folds -and
        [bool]$decision.gates.non_redundant_with_h5_h20 -and
        [bool]$decision.gates.improves_development_oof_stack -and
        [bool]$decision.gates.improves_realistic_cost -and
        [bool]$decision.gates.non_worsening_turnover_downside_large_loss
    )
    $expectedDecision = if ($allGatesPassed) {
        'KEEP_FOR_FULL_ABLATION'
    } else {
        'EXCLUDE_FROM_FULL_ABLATION_AND_FINAL'
    }
    if ([string]$decision.decision -ne $expectedDecision) {
        throw 'one-day screen decision contradicts fixed D080 gates'
    }
    return $decision
}

function Get-PhaseStatus {
    $boundary = Get-ManifestPayload $BoundaryPath
    $boundaryBatch = Get-BoundaryBatch $boundary
    $phase = 'BOUNDARY_BATCH'
    $activeManifest = $BoundaryPath
    $detail = $null
    $oneDayDecision = $null
    if ([string]$boundaryBatch.status -eq 'SUCCEEDED') {
        $oneDay = Get-ManifestPayload $OneDayPath
        if ($null -eq $oneDay) {
            $phase = 'ONE_DAY_SCREEN_QUEUED'
            $activeManifest = $null
        } elseif (-not (Test-AllSucceeded $oneDay)) {
            $phase = 'ONE_DAY_SCREEN'
            $activeManifest = $OneDayPath
        } else {
            $oneDayDecision = Get-OneDayDecision $oneDay
            if ($null -eq $oneDayDecision) {
                $phase = 'ONE_DAY_EVALUATION_READY'
                $activeManifest = $null
            } else {
                $fiveDay = Get-ManifestPayload $FiveDayPath
                if ($null -eq $fiveDay) {
                    $phase = 'FIVE_DAY_ABLATION_QUEUED'
                    $activeManifest = $null
                } elseif (-not (Test-AllSucceeded $fiveDay)) {
                    $phase = 'FIVE_DAY_ABLATION'
                    $activeManifest = $FiveDayPath
                } else {
                    $twentyDay = Get-ManifestPayload $TwentyDayPath
                    if ($null -eq $twentyDay) {
                        $phase = 'TWENTY_DAY_ABLATION_QUEUED'
                        $activeManifest = $null
                    } elseif (-not (Test-AllSucceeded $twentyDay)) {
                        $phase = 'TWENTY_DAY_ABLATION'
                        $activeManifest = $TwentyDayPath
                    } elseif ([string]$oneDayDecision.decision -eq 'KEEP_FOR_FULL_ABLATION') {
                        $oneDayAblation = Get-ManifestPayload $OneDayAblationPath
                        if ($null -eq $oneDayAblation) {
                            $phase = 'ONE_DAY_ABLATION_QUEUED'
                            $activeManifest = $null
                        } elseif (-not (Test-AllSucceeded $oneDayAblation)) {
                            $phase = 'ONE_DAY_ABLATION'
                            $activeManifest = $OneDayAblationPath
                        } else {
                            $phase = 'FEATURE_SELECTION_READY'
                            $activeManifest = $null
                        }
                    } else {
                        $phase = 'FEATURE_SELECTION_READY'
                        $activeManifest = $null
                    }
                }
            }
        }
    }
    if ($null -ne $activeManifest) {
        $statusLines = @(
            & $WindowsPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
                -File $ResearchRunner -Action status -Manifest $activeManifest -Json
        )
        if ($LASTEXITCODE -ne 0) {
            throw 'phase read-only campaign status failed'
        }
        $detail = ($statusLines -join [Environment]::NewLine) | ConvertFrom-Json
    }
    return [pscustomobject]@{
        schema_version = 'goal3-phase-runner-status-v1'
        checked_at = [DateTimeOffset]::UtcNow.ToString('o')
        phase = $phase
        active_manifest = $activeManifest
        campaign = $detail
        one_day_decision = $oneDayDecision
        legacy_core_screen_latch = if (Test-Path -LiteralPath $CorePath -PathType Container) {
            'ARMED'
        } else {
            'NOT_ARMED'
        }
        locked_holdout_accessed = $false
    }
}

function Assert-SourceProvenance {
    $safeDirectory = "safe.directory=$($ProjectRoot.Replace('\', '/'))"
    & git -c $safeDirectory -C $ProjectRoot cat-file -e "$CodeCommit`^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'phase runner code commit is unavailable'
    }
    & git -c $safeDirectory -C $ProjectRoot diff --quiet $CodeCommit -- src pyproject.toml uv.lock
    if ($LASTEXITCODE -ne 0) {
        throw 'phase runner model source or dependency lock differs from fixed commit'
    }
    $untrackedSource = @(& git -c $safeDirectory -C $ProjectRoot ls-files --others --exclude-standard -- src)
    if ($LASTEXITCODE -ne 0 -or $untrackedSource.Count -gt 0) {
        throw 'untracked model source prevents phase provenance authentication'
    }
}

function Invoke-ResearchRunner([string]$ManifestPath) {
    & $WindowsPowerShell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $ResearchRunner -Action run -Manifest $ManifestPath | Out-Host
    $exitCode = $LASTEXITCODE
    return $exitCode
}

function Invoke-NewScreen(
    [string]$ManifestPath,
    [string]$Horizons,
    [string]$Families,
    [string]$ReportRoot,
    [string]$CheckpointRoot,
    [string]$ChildLogRoot
) {
    $env:PYTHONPATH = Join-Path $ProjectRoot 'src'
    Remove-Item Env:JQUANTS_API_KEY -ErrorAction SilentlyContinue
    & $Python -m stock_ai research campaign `
        --build-manifest $BuildPath `
        --code-commit $CodeCommit `
        --horizons $Horizons `
        --model-families $Families `
        --seeds '17,29,43' `
        --target-family return `
        --tuning-trials 3 `
        --tuning-timeout-seconds 900 `
        --estimator-count 50 `
        --initial-train-periods 500 `
        --validation-periods 60 `
        --step-periods 60 `
        --holdout-periods 120 `
        --no-run-ablations `
        --no-run-diagnostics `
        --max-materialized-oof-rows 20000000 `
        --max-model-fits 1000 `
        --campaign-manifest $ManifestPath `
        --report-root $ReportRoot `
        --experiment-registry $RegistryPath `
        --checkpoint-root $CheckpointRoot `
        --log-root $ChildLogRoot | Out-Host
    $exitCode = $LASTEXITCODE
    return $exitCode
}

function Invoke-ScreenPhase(
    [string]$ManifestPath,
    [string]$Horizons,
    [string]$Families,
    [string]$ReportRoot,
    [string]$CheckpointRoot,
    [string]$ChildLogRoot
) {
    if (Test-Path -LiteralPath $ManifestPath -PathType Leaf) {
        return Invoke-ResearchRunner $ManifestPath
    }
    return Invoke-NewScreen $ManifestPath $Horizons $Families $ReportRoot $CheckpointRoot $ChildLogRoot
}

function Invoke-NewAblation(
    [string]$ManifestPath,
    [string]$Horizon,
    [string]$ReportRoot,
    [string]$CheckpointRoot,
    [string]$ChildLogRoot
) {
    $env:PYTHONPATH = Join-Path $ProjectRoot 'src'
    Remove-Item Env:JQUANTS_API_KEY -ErrorAction SilentlyContinue
    & $Python -m stock_ai research campaign `
        --build-manifest $BuildPath `
        --code-commit $CodeCommit `
        --horizons $Horizon `
        --model-families 'lightgbm,xgboost,catboost' `
        --seeds '17,29,43' `
        --target-family return `
        --tuning-trials 20 `
        --tuning-timeout-seconds 900 `
        --estimator-count 300 `
        --initial-train-periods 500 `
        --validation-periods 60 `
        --step-periods 60 `
        --holdout-periods 120 `
        --run-ablations `
        --run-diagnostics `
        --max-materialized-oof-rows 20000000 `
        --max-model-fits 5000 `
        --campaign-manifest $ManifestPath `
        --report-root $ReportRoot `
        --experiment-registry $RegistryPath `
        --checkpoint-root $CheckpointRoot `
        --log-root $ChildLogRoot | Out-Host
    return $LASTEXITCODE
}

function Invoke-AblationPhase(
    [string]$ManifestPath,
    [string]$Horizon,
    [string]$ReportRoot,
    [string]$CheckpointRoot,
    [string]$ChildLogRoot
) {
    if (Test-Path -LiteralPath $ManifestPath -PathType Leaf) {
        return Invoke-ResearchRunner $ManifestPath
    }
    return Invoke-NewAblation $ManifestPath $Horizon $ReportRoot $CheckpointRoot $ChildLogRoot
}

$BoundaryPath = Resolve-ProjectPath $BoundaryManifest
$OneDayPath = Resolve-ProjectPath $OneDayScreenManifest
$CorePath = Resolve-ProjectPath $CoreScreenManifest
$OneDayDecisionPath = Resolve-ProjectPath $OneDayDecisionArtifact
$FiveDayPath = Resolve-ProjectPath $FiveDayAblationManifest
$TwentyDayPath = Resolve-ProjectPath $TwentyDayAblationManifest
$OneDayAblationPath = Resolve-ProjectPath $OneDayAblationManifest
$BuildPath = Resolve-ProjectPath $BuildManifest
$RegistryPath = Resolve-ProjectPath $ExperimentRegistry
$PhaseLogRoot = Resolve-ProjectPath $LogRoot
$OneDayReportRoot = Resolve-ProjectPath 'artifacts/reports/advanced'
$OneDayCheckpointRoot = Resolve-ProjectPath 'artifacts/checkpoints/goal3-screen-1d-v1'
$OneDayLogRoot = Resolve-ProjectPath 'artifacts/logs/goal3-screen-1d-v1'
$CoreReportRoot = Resolve-ProjectPath 'artifacts/reports/advanced'
$FiveDayCheckpointRoot = Resolve-ProjectPath 'artifacts/checkpoints/goal3-ablation-5d-v1'
$FiveDayLogRoot = Resolve-ProjectPath 'artifacts/logs/goal3-ablation-5d-v1'
$TwentyDayCheckpointRoot = Resolve-ProjectPath 'artifacts/checkpoints/goal3-ablation-20d-v1'
$TwentyDayLogRoot = Resolve-ProjectPath 'artifacts/logs/goal3-ablation-20d-v1'
$OneDayAblationCheckpointRoot = Resolve-ProjectPath 'artifacts/checkpoints/goal3-ablation-1d-v1'
$OneDayAblationLogRoot = Resolve-ProjectPath 'artifacts/logs/goal3-ablation-1d-v1'

if ($Action -eq 'status') {
    Get-PhaseStatus | ConvertTo-Json -Depth 14
    exit 0
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'phase runner Python is missing'
}
if (-not (Test-Path -LiteralPath $BuildPath -PathType Leaf)) {
    throw 'phase runner Production Build manifest is missing'
}
Assert-SourceProvenance

$phaseLockPath = Join-Path $PhaseLogRoot 'phase-runner.lock'
New-Item -ItemType Directory -Path $PhaseLogRoot -Force | Out-Null
$phaseLock = $null
try {
    $phaseLock = [System.IO.File]::Open(
        $phaseLockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch [System.IO.IOException] {
    exit 0
}

try {
    # Do not inspect or alter the running boundary worker. The existing
    # research runner owns this lock until its current batch reaches a safe
    # boundary.
    $boundaryLock = $null
    try {
        $boundaryLock = [System.IO.File]::Open(
            "$BoundaryPath.runner.lock",
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    } catch [System.IO.IOException] {
        Write-PhaseEvent $PhaseLogRoot 'WAITING_FOR_BOUNDARY_LOCK' 'current runner remains owner'
        exit 0
    } finally {
        if ($null -ne $boundaryLock) {
            $boundaryLock.Dispose()
        }
    }

    $boundaryPayload = Get-ManifestPayload $BoundaryPath
    $boundaryBatch = Get-BoundaryBatch $boundaryPayload
    if ([string]$boundaryBatch.status -ne 'SUCCEEDED') {
        Write-PhaseEvent $PhaseLogRoot 'RESUME_BOUNDARY_BATCH' ([string]$boundaryBatch.status)
        exit (Invoke-ResearchRunner $BoundaryPath)
    }
    $unexpectedOldBatch = @(
        $boundaryPayload.batches |
            Where-Object {
                [string]$_.batch_id -ne 'h1-lightgbm-s17' -and
                [string]$_.status -ne 'PENDING'
            }
    )
    if ($unexpectedOldBatch.Count -gt 0) {
        throw 'old campaign crossed the fixed D077 boundary'
    }

    Write-PhaseEvent $PhaseLogRoot 'START_OR_RESUME_ONE_DAY_SCREEN' 'xgboost,catboost seeds=17,29,43'
    $oneDayExit = Invoke-ScreenPhase `
        $OneDayPath '1' 'xgboost,catboost' `
        $OneDayReportRoot $OneDayCheckpointRoot $OneDayLogRoot
    if ($oneDayExit -ne 0) {
        exit $oneDayExit
    }

    $oneDayPayload = Get-ManifestPayload $OneDayPath
    $oneDayDecision = Get-OneDayDecision $oneDayPayload
    if ($null -eq $oneDayDecision) {
        Write-PhaseEvent $PhaseLogRoot 'ONE_DAY_EVALUATION_READY' 'fixed D080 development-only gates; locked holdout untouched'
        exit 0
    }

    Write-PhaseEvent $PhaseLogRoot 'START_OR_RESUME_FIVE_DAY_ABLATION' 'all families seeds=17,29,43; no core screen'
    $fiveDayExit = Invoke-AblationPhase `
        $FiveDayPath '5' $CoreReportRoot $FiveDayCheckpointRoot $FiveDayLogRoot
    if ($fiveDayExit -ne 0) {
        exit $fiveDayExit
    }

    Write-PhaseEvent $PhaseLogRoot 'START_OR_RESUME_TWENTY_DAY_ABLATION' 'all families seeds=17,29,43; no core screen'
    $twentyDayExit = Invoke-AblationPhase `
        $TwentyDayPath '20' $CoreReportRoot $TwentyDayCheckpointRoot $TwentyDayLogRoot
    if ($twentyDayExit -ne 0) {
        exit $twentyDayExit
    }

    if ([string]$oneDayDecision.decision -eq 'KEEP_FOR_FULL_ABLATION') {
        Write-PhaseEvent $PhaseLogRoot 'START_OR_RESUME_ONE_DAY_ABLATION' 'D080 gates passed; all families seeds=17,29,43'
        $oneDayAblationExit = Invoke-AblationPhase `
            $OneDayAblationPath '1' $CoreReportRoot `
            $OneDayAblationCheckpointRoot $OneDayAblationLogRoot
        if ($oneDayAblationExit -ne 0) {
            exit $oneDayAblationExit
        }
    }

    Write-PhaseEvent $PhaseLogRoot 'FEATURE_SELECTION_READY' 'full ablation complete; locked holdout untouched'
    exit 0
} catch {
    Write-PhaseEvent $PhaseLogRoot 'PHASE_RUNNER_FAILED' $_.Exception.GetType().FullName
    exit 1
} finally {
    if ($null -ne $phaseLock) {
        $phaseLock.Dispose()
    }
}
