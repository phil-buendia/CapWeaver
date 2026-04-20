param(
    [string]$Model = "claude-4.6-sonnet"
)

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$coreCoderRoot = Join-Path $repoRoot "CoreCoder"

if (-not (Test-Path (Join-Path $coreCoderRoot "corecoder\__init__.py"))) {
    Write-Error "Local CoreCoder source not found under $coreCoderRoot"
    exit 1
}

Push-Location $coreCoderRoot
try {
    python -m corecoder -m $Model
}
finally {
    Pop-Location
}
