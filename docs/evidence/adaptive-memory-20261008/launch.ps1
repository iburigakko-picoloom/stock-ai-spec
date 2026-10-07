$ErrorActionPreference='Stop'
$root=Join-Path 'C:\Users\manat\app' ([string][char]0x682a+'AI\stock-ai-spec')
$out=Join-Path $PSScriptRoot 'stock-h20-adaptive-resume-20261008'
$receiptPath=Join-Path $out 'plan-receipt.json'
$pre=Get-Content -LiteralPath $receiptPath -Encoding utf8 -Raw|ConvertFrom-Json
$runtime=Join-Path $out 'runtime'
if(Test-Path -LiteralPath $runtime){throw 'Existing runtime; duplicate launch refused.'}
$workers=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'"|Where-Object {$_.CommandLine-and($_.CommandLine-match[regex]::Escape($root)-or$_.CommandLine-match'stock_ai|stock_seed43|stock_h20|stock_adaptive')})
if($workers.Count){throw 'Stock process exists; duplicate launch refused.'}
$tasks=@(Get-ScheduledTask -TaskName 'StockAI-Goal3-*'|ForEach-Object {$_.State.ToString()})
if($tasks.Count-lt4-or@($tasks|Where-Object {$_-ne'Disabled'}).Count){throw 'Legacy tasks must remain Disabled.'}
& git -c "safe.directory=$root" -C $root diff --quiet $pre.source_pin -- src pyproject.toml uv.lock
if($LASTEXITCODE-ne0){throw 'Scientific implementation changed.'}
$policy=Join-Path $PSScriptRoot 'stock_runtime_memory.py'
if((Get-FileHash -LiteralPath $policy -Algorithm SHA256).Hash.ToLowerInvariant()-ne$pre.runtime_policy_sha256){throw 'Execution policy changed after validation.'}
$os=Get-CimInstance Win32_OperatingSystem
$free=[double]$os.FreePhysicalMemory/1MB
if($free-lt2.0){throw 'OS reserve plus interpreter bootstrap memory unavailable; no launch.'}
$exclusive=[System.IO.File]::Open((Join-Path $out 'single-launch.lock'),[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
$exclusive.Dispose()
New-Item -ItemType Directory -Path $runtime|Out-Null
$script=Join-Path $PSScriptRoot 'stock_h20_adaptive_worker.py'
$launch=[ordered]@{LaunchedAtUtc=[DateTimeOffset]::UtcNow.ToString('o');AvailablePhysicalGiB=$free;StockWorkersBeforeLaunch=0;OSReserveGiB=1.25;EmergencyPhysicalGiB=0.5;ExecutionPolicy=$pre.execution_policy;AuthenticatedReusedTuning=7;NewTuningBudget=$false;Threads=1;worker_sha256=(Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant();plan_receipt_sha256=(Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant();runtime_policy_sha256=$pre.runtime_policy_sha256;NoAdditionalObserver=$true;NoAutoRetry=$true}
$utf8=New-Object System.Text.UTF8Encoding($false)
$launchFile=Join-Path $runtime 'launch-receipt.json'
[System.IO.File]::WriteAllText($launchFile,($launch|ConvertTo-Json),$utf8)
$env:PYTHONPATH=Join-Path $root 'src'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PANDAS_COPY_ON_WRITE='1'
$env:PYTHONUNBUFFERED='1'
$env:PYTHONIOENCODING='utf-8'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$launcher=Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') -ArgumentList @(('"'+$script+'"')) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'worker.stdout.log') -RedirectStandardError (Join-Path $runtime 'worker.stderr.log') -PassThru
$launch['LauncherPid']=$launcher.Id
[System.IO.File]::WriteAllText($launchFile,($launch|ConvertTo-Json),$utf8)
$prior=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'stock-active-runtime.json') -Encoding utf8 -Raw|ConvertFrom-Json
$pointer=[ordered]@{Horizon=20;FeatureCount=51;Runtime=$runtime;WorkerRecord=(Join-Path $runtime 'worker.json');CampaignManifest=$pre.campaign_path;CheckpointRoot=(Get-Content -LiteralPath $pre.campaign_path -Encoding utf8 -Raw|ConvertFrom-Json).checkpoint_root;CheckpointPathLocation='Read current checkpoint_path in WorkerRecord';ExperimentRegistry=$prior.ExperimentRegistry;ReportRoot=$prior.ReportRoot;HumanProgressCadenceHours=12;NoAdditionalObserver=$true;PriorRuntimePointer=(Join-Path $out 'before\active-runtime.json');PriorH5RuntimePointerPreserved=$prior.PriorH5RuntimePointerPreserved}
$pointerPath=Join-Path $PSScriptRoot 'stock-active-runtime.json'
[System.IO.File]::WriteAllText(($pointerPath+'.tmp'),($pointer|ConvertTo-Json),$utf8)
Move-Item -LiteralPath ($pointerPath+'.tmp') -Destination $pointerPath -Force
$launch|ConvertTo-Json
