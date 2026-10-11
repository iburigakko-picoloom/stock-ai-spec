$ErrorActionPreference='Stop'
$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
$base=$PSScriptRoot
$root=Join-Path 'C:\Users\manat\app' ([string][char]0x682a+'AI\stock-ai-spec')
$out=Join-Path $base 'stock-h20-quantile-once-20261011'
$pre=Get-Content -LiteralPath (Join-Path $out 'plan-receipt.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$activePath=Join-Path $base 'stock-active-runtime.json'
$active=Get-Content -LiteralPath $activePath -Raw -Encoding UTF8 | ConvertFrom-Json
$old=Get-Content -LiteralPath $active.WorkerRecord -Raw -Encoding UTF8 | ConvertFrom-Json
$backup=Get-Content -LiteralPath (Join-Path $out 'backup-verification.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime=Join-Path $out 'runtime'
if(Test-Path -LiteralPath $runtime){throw 'Single launch already attempted; no retry.'}
if($env:COMPUTERNAME -ne 'MANATOBOOK'){throw 'Wrong machine'}
if($old.pid -ne $backup.old_pid -or $old.phase -ne 'WAITING_FOR_MEMORY' -or $old.batch_id -ne 'h20-catboost-s17' -or $old.task -ne 'quantile' -or $old.fold -ne 5){throw 'Target already advanced; no stop'}
$os=Get-CimInstance Win32_OperatingSystem
if([double]$os.FreePhysicalMemory/1MB -ge $old.required_gib){throw 'Original guard can admit; unnecessary stop refused'}
foreach($property in $backup.checkpoint_hashes.PSObject.Properties){
    $live=Join-Path $backup.checkpoint $property.Name
    $copy=Join-Path (Join-Path $out 'verified-before\checkpoint') $property.Name
    if((Get-FileHash -LiteralPath $live -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value -or (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value){throw 'Checkpoint changed; no stop'}
}
foreach($pair in @(@('stock_runtime_memory.py',$pre.base_policy_sha256),@('stock_quantile_once_policy.py',$pre.runtime_policy_sha256))){
    if((Get-FileHash -LiteralPath (Join-Path $base $pair[0]) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pair[1]){throw 'Policy hash changed'}
}
& git -c "safe.directory=$root" -C $root diff --quiet $pre.source_pin -- src pyproject.toml uv.lock
if($LASTEXITCODE -ne 0){throw 'Scientific code changed'}
$tasks=@(Get-ScheduledTask -TaskName 'StockAI-Goal3-*' | ForEach-Object {$_.State.ToString()})
if($tasks.Count -lt 4 -or @($tasks | Where-Object {$_ -ne 'Disabled'}).Count){throw 'Legacy tasks not disabled'}
$native=Get-CimInstance Win32_Process -Filter "ProcessId=$($old.pid)"
if($native.Name -ne 'python.exe' -or $native.CommandLine -notmatch 'stock_h20_adaptive_worker.py'){throw 'Unexpected PID identity'}
$parent=Get-CimInstance Win32_Process -Filter "ProcessId=$($native.ParentProcessId)"
$utf8=[System.Text.UTF8Encoding]::new($false)
$lock=[System.IO.File]::Open((Join-Path $out 'single-launch.lock'),[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
$lock.Dispose()
# Target is blocked before fit; all successful units were copied and hashed.
Stop-Process -Id $old.pid -ErrorAction Stop
$stopped=Get-Process -Id $old.pid -ErrorAction SilentlyContinue
if($null -ne $stopped){$stopped.WaitForExit(5000)|Out-Null}
if(Get-Process -Id $old.pid -ErrorAction SilentlyContinue){throw 'Old native worker still alive; no launch'}
if($null -ne $parent -and $parent.Name -eq 'python.exe' -and $parent.CommandLine -match 'stock_h20_adaptive_worker.py'){
    $parentProcess=Get-Process -Id $parent.ProcessId -ErrorAction SilentlyContinue
    if($null -ne $parentProcess){Stop-Process -Id $parent.ProcessId -ErrorAction Stop}
}
$remaining=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {$_.CommandLine -and ($_.CommandLine -match [regex]::Escape($root) -or $_.CommandLine -match 'stock_ai|stock_h20|stock_adaptive')})
if($remaining.Count){throw 'Another stock process remains; no launch'}
$manifest=Get-Content -LiteralPath $pre.campaign_path -Raw -Encoding UTF8 | ConvertFrom-Json
$batch=$manifest.batches | Where-Object batch_id -eq 'h20-catboost-s17'
if($batch.status -ne 'RUNNING'){throw 'Unexpected campaign state'}
$batch.status='PENDING'; $batch.child_pid=$null
$batch.last_error='Explicit one-time quantile fold5 resume; prior runtime and checkpoint preserved.'
[System.IO.File]::WriteAllText(($pre.campaign_path+'.tmp'),($manifest|ConvertTo-Json -Depth 15),$utf8)
Move-Item -LiteralPath ($pre.campaign_path+'.tmp') -Destination $pre.campaign_path -Force
New-Item -ItemType Directory -Path $runtime | Out-Null
$script=Join-Path $base 'stock_h20_quantile_once_worker.py'
$launch=[ordered]@{LaunchedAtUtc=[DateTimeOffset]::UtcNow.ToString('o');OldPid=$old.pid;OldNativeConfirmedStopped=$true;Threads=1;OSReserveGiB=1.25;EmergencyPhysicalGiB=0.5;NoAutoRetry=$true;worker_sha256=(Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant();plan_receipt_sha256=(Get-FileHash -LiteralPath (Join-Path $out 'plan-receipt.json') -Algorithm SHA256).Hash.ToLowerInvariant();runtime_policy_sha256=$pre.runtime_policy_sha256}
$launchFile=Join-Path $runtime 'launch-receipt.json'
[System.IO.File]::WriteAllText($launchFile,($launch|ConvertTo-Json),$utf8)
$env:PYTHONPATH=Join-Path $root 'src'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:PANDAS_COPY_ON_WRITE='1'
$env:PYTHONUNBUFFERED='1'; $env:PYTHONIOENCODING='utf-8'; $env:OMP_NUM_THREADS='1'; $env:OPENBLAS_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'
$launcher=Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') -ArgumentList @(('"'+$script+'"')) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'worker.stdout.log') -RedirectStandardError (Join-Path $runtime 'worker.stderr.log') -PassThru
$launch['LauncherPid']=$launcher.Id
[System.IO.File]::WriteAllText($launchFile,($launch|ConvertTo-Json),$utf8)
$active.Runtime=$runtime; $active.WorkerRecord=Join-Path $runtime 'worker.json'
$active.PriorRuntimePointer=Join-Path $out 'verified-before\active-runtime.json'
[System.IO.File]::WriteAllText(($activePath+'.tmp'),($active|ConvertTo-Json -Depth 5),$utf8)
Move-Item -LiteralPath ($activePath+'.tmp') -Destination $activePath -Force
$launch | ConvertTo-Json
