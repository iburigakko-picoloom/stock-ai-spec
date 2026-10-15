$ErrorActionPreference='Stop'
$stockRoot='C:\Users\manat\app\株AI\stock-ai-spec'
$work='C:\Users\manat\Documents\Codex\2026-10-01\task\stock-campaign-continuation'
$runtime=Join-Path $work 'runtime'
if(Test-Path -LiteralPath $runtime){throw 'Single attempt already exists; no restart.'}
$adopt=Get-Content -LiteralPath (Join-Path $work 'adoption-completed.json') -Encoding utf8 -Raw|ConvertFrom-Json
if(-not$adopt.adoption_completed -or -not$adopt.genuine_pins_preserved){throw 'Research adoption not authenticated.'}
$tasks=@(Get-ScheduledTask -TaskName 'StockAI-Goal3-*'|Select-Object TaskName,State)
if($tasks.Count-lt4 -or @($tasks|Where-Object{$_.State-ne'Disabled'}).Count){throw 'Legacy tasks not all Disabled.'}
$workers=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'"|Where-Object{$_.CommandLine-and($_.CommandLine-match[regex]::Escape($stockRoot)-or$_.CommandLine-match'stock_ai|stock_seed43_worker')})
if($workers.Count){throw 'Stock Python worker exists; duplicate refused.'}
if(Test-Path -LiteralPath $adopt.seed43_checkpoint){throw 'Seed43 namespace already exists.'}
$pin='8d82fa67a7f64186f42208f0632b799e13381c0d'
& git -c "safe.directory=$stockRoot" -C $stockRoot diff --quiet $pin -- src pyproject.toml uv.lock
if($LASTEXITCODE-ne0){throw 'Scientific source or lock changed.'}
$os=Get-CimInstance Win32_OperatingSystem
$free=[double]$os.FreePhysicalMemory/1MB
$diskFree=(Get-PSDrive -Name C).Free/1GB
if($free-lt7.0){throw ('Preparation headroom insufficient: {0:F3} GiB; no launch.'-f$free)}
if($diskFree-lt4){throw 'Scratch disk headroom insufficient.'}
$script='C:\Users\manat\Documents\Codex\2026-10-01\task\stock_seed43_worker.py'
$utf8=New-Object System.Text.UTF8Encoding($false)
New-Item -ItemType Directory -Path $runtime|Out-Null
$intent=[ordered]@{CheckedAtUtc=[DateTimeOffset]::UtcNow.ToString('o');AvailablePhysicalGiB=$free;ScratchDiskFreeGiB=$diskFree;RequiredPreparationGiB=7.0;RequiredFitGiB=3.5;StockWorkersBeforeLaunch=0;NoAutoRestart=$true;ModelCodeCommit=$pin;ConfigHash=$adopt.seed43_config_hash;WorkerSha256=(Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant()}
[System.IO.File]::WriteAllText((Join-Path $runtime 'intent.json'),($intent|ConvertTo-Json),$utf8)
$env:PYTHONPATH=Join-Path $stockRoot 'src'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PANDAS_COPY_ON_WRITE='1'
$env:PYTHONUNBUFFERED='1'
$env:PYTHONIOENCODING='utf-8'
$record=Join-Path $runtime 'worker.json'
$stdout=Join-Path $runtime 'worker.stdout.log'
$stderr=Join-Path $runtime 'worker.stderr.log'
$arguments=@(('"'+$script+'"'),'--repository',('"'+$stockRoot+'"'),'--campaign',('"'+$adopt.continuation_manifest+'"'),'--worker-record',('"'+$record+'"'),'--scratch-root',('"'+(Join-Path $runtime 'scratch')+'"'))
$launcher=Start-Process -FilePath (Join-Path $stockRoot '.venv\Scripts\python.exe') -ArgumentList $arguments -WorkingDirectory $stockRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
$launch=[ordered]@{LaunchedAtUtc=[DateTimeOffset]::UtcNow.ToString('o');LauncherPid=$launcher.Id;Preparation=$intent;CheckpointPath=$adopt.seed43_checkpoint;WorkerRecord=$record;Stdout=$stdout;Stderr=$stderr;LegacyTasks=$tasks;WorkerLaunched=$true;FitStartedVerified=$false;NoAutoRestart=$true}
[System.IO.File]::WriteAllText((Join-Path $runtime 'launch-receipt.json'),($launch|ConvertTo-Json -Depth 7),$utf8)
$observerScript='C:\Users\manat\Documents\Codex\2026-10-01\task\stock_seed43_watch.ps1'
$observer=Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$observerScript+'"')) -WorkingDirectory $stockRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'observer.stdout.log') -RedirectStandardError (Join-Path $runtime 'observer.stderr.log') -PassThru
[System.IO.File]::WriteAllText((Join-Path $runtime 'observer-launch.json'),(@{StartedAtUtc=[DateTimeOffset]::UtcNow.ToString('o');ObserverPid=$observer.Id;NoWorkerActions=$true;ProcessChecksMinutes=15;MetadataChecksSeconds=30}|ConvertTo-Json),$utf8)
$launch|ConvertTo-Json -Depth 7
