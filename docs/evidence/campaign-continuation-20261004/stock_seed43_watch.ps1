$ErrorActionPreference='Stop'
$runtime='C:\Users\manat\Documents\Codex\2026-10-01\task\stock-campaign-continuation\runtime'
$launch=Get-Content -LiteralPath (Join-Path $runtime 'launch-receipt.json') -Encoding utf8 -Raw|ConvertFrom-Json
$audit=Join-Path $runtime 'audit'
if(Test-Path -LiteralPath $audit){throw 'Observer already exists.'}
New-Item -ItemType Directory -Path $audit|Out-Null
$utf8=New-Object System.Text.UTF8Encoding($false)
$lastProcess=[DateTimeOffset]::MinValue
$firstBoundary=$false
while($true){
 $now=[DateTimeOffset]::UtcNow
 $record=$null
 if(Test-Path -LiteralPath $launch.WorkerRecord){$record=Get-Content -LiteralPath $launch.WorkerRecord -Encoding utf8 -Raw|ConvertFrom-Json}
 $units=@()
 $progressFile=Join-Path $launch.CheckpointPath 'progress.json'
 if(Test-Path -LiteralPath $progressFile){$progress=Get-Content -LiteralPath $progressFile -Encoding utf8 -Raw|ConvertFrom-Json;$units=@($progress.units.PSObject.Properties.Value)}
 $checks=@()
 $scratch=Join-Path $runtime 'scratch'
 if(Test-Path -LiteralPath $scratch){$guard=Get-ChildItem -LiteralPath $scratch -File -Filter '*.fit-headroom.json'|Select-Object -First 1;if($guard){$checks=@(Get-Content -LiteralPath $guard.FullName -Encoding utf8 -Raw|ConvertFrom-Json)}}
 $passed=@($checks|Where-Object{$_.passed}).Count
 $terminal=$record-and($record.phase-in@('COMPLETED','FAILED','BLOCKED_BEFORE_FIT'))
 $sample=[ordered]@{ObservedAtUtc=$now.ToString('o');ObservedAtJst=$now.ToOffset([TimeSpan]::FromHours(9)).ToString('o');WorkerPhase=if($record){$record.phase}else{'LAUNCHING'};WorkerError=if($record){$record.error}else{$null};SucceededUnits=@($units|Where-Object{$_.status-eq'SUCCEEDED'}).Count;FailedUnits=@($units|Where-Object{$_.status-eq'FAILED'}).Count;Running=@($units|Where-Object{$_.status-eq'RUNNING'}|ForEach-Object{[pscustomobject]@{Task=$_.evidence.task;Fold=$_.evidence.fold;Scope=$_.evidence.checkpoint_scope;UpdatedAt=$_.updated_at}});PassedFitGuards=$passed;FitGuardChecks=$checks;NoWorkerActionsTaken=$true}
 if(($now-$lastProcess).TotalMinutes-ge15 -or ($passed-gt0-and-not$firstBoundary) -or $terminal){
  $queryPid=if($record){[int]$record.pid}else{[int]$launch.LauncherPid}
  $process=Get-Process -Id $queryPid -ErrorAction SilentlyContinue
  $os=Get-CimInstance Win32_OperatingSystem
  $sample['WorkerPid']=$queryPid
  $sample['WorkerAlive']=[bool]$process
  $sample['CpuTotalSeconds']=if($process){$process.TotalProcessorTime.TotalSeconds}else{$null}
  $sample['WorkingSetGiB']=if($process){$process.WorkingSet64/1GB}else{$null}
  $sample['PeakWorkingSetGiB']=if($process){$process.PeakWorkingSet64/1GB}else{$null}
  $sample['AvailablePhysicalGiB']=[double]$os.FreePhysicalMemory/1MB
  $lastProcess=$now
  if($passed-gt0-and$process){$firstBoundary=$true;$sample['FirstFitBoundaryReached']=$true}
  if(-not$process){$terminal=$true;$sample['WorkerExitObserved']=$true}
 }
 [System.IO.File]::AppendAllText((Join-Path $audit 'samples.jsonl'),(($sample|ConvertTo-Json -Depth 10 -Compress)+[Environment]::NewLine),$utf8)
 [System.IO.File]::WriteAllText((Join-Path $audit 'latest.json'),($sample|ConvertTo-Json -Depth 10),$utf8)
 if($terminal){
  $sample['StdoutTail']=@(Get-Content -LiteralPath $launch.Stdout -Encoding utf8 -Tail 15)
  $sample['StderrTail']=@(Get-Content -LiteralPath $launch.Stderr -Encoding utf8 -Tail 15)
  [System.IO.File]::WriteAllText((Join-Path $audit 'terminal.json'),($sample|ConvertTo-Json -Depth 12),$utf8)
  break
 }
 Start-Sleep -Seconds 30
}
