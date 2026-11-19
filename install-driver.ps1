param([Parameter(Mandatory=$true)][string]$Installer, [switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
$signature = Get-AuthenticodeSignature -LiteralPath $Installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) -cne 'BUREL VINCENT Entrepreneur individuel') {
    throw 'Driver publisher signature could not be verified. Nothing was installed.'
}
if ($VerifyOnly) { exit 0 }
# This is intentionally visible: the owner must review the license and installation.
$process = Start-Process -FilePath $Installer -Verb RunAs -Wait -PassThru
if ($process.ExitCode -ne 0) {
    throw "Driver installer exited with code $($process.ExitCode)."
}
