param([switch]$RegisterGitHubSecrets)
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$vault = Join-Path $workspace '.demo-artifacts/android-signing'
$isNewVault = !(Test-Path -LiteralPath $vault)
New-Item -ItemType Directory -Path $vault -Force | Out-Null
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
if ($isNewVault) {
    Set-Acl -LiteralPath $vault -AclObject $acl
} else {
    $existingAcl = Get-Acl -LiteralPath $vault
    if (!$existingAcl.AreAccessRulesProtected -or @($existingAcl.Access | Where-Object { $_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Value -ne $identity }).Count -ne 0) {
        throw 'Signing directory is not restricted to the current Windows account.'
    }
}
$pfxPath = Join-Path $vault 'stockai-signing.p12'
$credentialPath = Join-Path $vault 'credentials.dpapi'
Add-Type -AssemblyName System.Security.Cryptography.ProtectedData
if ((Test-Path -LiteralPath $pfxPath) -ne (Test-Path -LiteralPath $credentialPath)) {
    throw 'Signing backup is incomplete. Restore it; never replace an existing signing key.'
}
if (!(Test-Path -LiteralPath $pfxPath)) {
    $random = [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    $password = [Convert]::ToBase64String($random)
    $rsa = [Security.Cryptography.RSA]::Create(3072)
    $request = [Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=StockAI Android Signing', $rsa, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $request.CertificateExtensions.Add([Security.Cryptography.X509Certificates.X509KeyUsageExtension]::new([Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature, $true))
    $certificate = $request.CreateSelfSigned([DateTimeOffset]::UtcNow.AddDays(-1), [DateTimeOffset]::UtcNow.AddYears(30))
    $certificate.FriendlyName = 'stockai'
    [IO.File]::WriteAllBytes($pfxPath, $certificate.Export([Security.Cryptography.X509Certificates.X509ContentType]::Pkcs12, $password))
    $credentials = @{ storePassword = $password; keyPassword = $password; alias = 'stockai' } | ConvertTo-Json -Compress
    [IO.File]::WriteAllBytes($credentialPath, [Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($credentials), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser))
    $rsa.Dispose()
} else {
    $raw = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($credentialPath), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
    $credentials = [Text.Encoding]::UTF8.GetString($raw)
    $record = $credentials | ConvertFrom-Json
    $password = $record.storePassword
    $certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($pfxPath, $password, [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
}
$record = $credentials | ConvertFrom-Json
$fingerprint = $certificate.GetCertHashString([Security.Cryptography.HashAlgorithmName]::SHA256).ToLowerInvariant()
$publicPath = Join-Path $workspace 'mobile/signing-certificate.json'
$public = @{ schema_version=1; certificate_sha256=$fingerprint; alias=$record.alias; application_id='jp.stockai.app' } | ConvertTo-Json
if (Test-Path -LiteralPath $publicPath) {
    $old = Get-Content -LiteralPath $publicPath -Raw | ConvertFrom-Json
    if ($old.certificate_sha256 -ne $fingerprint) { throw 'Signing certificate mismatch: refusing key rotation.' }
} else {
    [IO.File]::WriteAllText($publicPath, $public + "`n", [Text.UTF8Encoding]::new($false))
}
if ($RegisterGitHubSecrets) {
    $repository = 'iburigakko-picoloom/stock-ai-spec'
    $values = @{
        ANDROID_KEYSTORE_BASE64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($pfxPath))
        ANDROID_KEYSTORE_PASSWORD = $record.storePassword
        ANDROID_KEY_ALIAS = $record.alias
        ANDROID_KEY_PASSWORD = $record.keyPassword
    }
    foreach ($name in $values.Keys) {
        # Read secret values on stdin; never place them in command arguments/logs.
        # Write() deliberately avoids PowerShell's pipeline trailing newline.
        $process = [Diagnostics.Process]::new()
        $process.StartInfo.FileName = (Get-Command gh).Source
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        $process.StartInfo.RedirectStandardInput = $true
        foreach ($argument in @('secret', 'set', $name, '--repo', $repository)) { $process.StartInfo.ArgumentList.Add($argument) }
        [void]$process.Start()
        $process.StandardInput.Write([string]$values[$name])
        $process.StandardInput.Close()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "GitHub secret registration failed: $name" }
        $process.Dispose()
    }
}
@{ certificate_sha256=$fingerprint; encrypted_keystore=$pfxPath; windows_protected_credentials=$credentialPath; github_secrets_registered=[bool]$RegisterGitHubSecrets } | ConvertTo-Json -Compress
