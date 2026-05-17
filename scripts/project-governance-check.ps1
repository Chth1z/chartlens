param(
    [switch]$SkipGenerated
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Violations = New-Object System.Collections.Generic.List[string]
$Warnings = New-Object System.Collections.Generic.List[string]

function Add-Violation([string]$Message) {
    $Violations.Add($Message) | Out-Null
}

function Add-Warning([string]$Message) {
    $Warnings.Add($Message) | Out-Null
}

function Relative-Path([string]$Path) {
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    return $resolved.Substring($RepoRoot.Length + 1)
}

function Get-SourceFiles([string[]]$Roots, [string[]]$Includes) {
    foreach ($root in $Roots) {
        $path = Join-Path $RepoRoot $root
        if (Test-Path -LiteralPath $path) {
            Get-ChildItem -LiteralPath $path -Recurse -File -Include $Includes -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.FullName -notmatch '\\__pycache__\\' -and
                    $_.FullName -notmatch '\\node_modules\\' -and
                    $_.FullName -notmatch '\\dist\\' -and
                    $_.FullName -notmatch '\\\.tmp-frontend-tests\\'
                }
        }
    }
}

# Backend API contract: frontend-facing JSON endpoints must expose response_model.
# Streaming/file endpoints are intentionally excluded because they do not return JSON contracts.
$routesPath = Join-Path $RepoRoot "backend\app\api\routes.py"
$streamingRouteAllowlist = @(
    '"/cases/{case_id}/source-pages/{page}"',
    '"/cases/{case_id}/export"'
)
if (Test-Path -LiteralPath $routesPath) {
    $lines = Get-Content -LiteralPath $routesPath
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i].Trim()
        if ($line -match '^@router\.(get|post|patch|delete|put)\(' -and $line -notmatch 'response_model=') {
            $isAllowed = $false
            foreach ($allowed in $streamingRouteAllowlist) {
                if ($line.Contains($allowed)) {
                    $isAllowed = $true
                    break
                }
            }
            if (-not $isAllowed) {
                Add-Violation ("backend/app/api/routes.py:{0}: route decorator missing response_model: {1}" -f ($i + 1), $line)
            }
        }
    }
}

# Frontend API boundary: all HTTP access must go through shared/api/client.ts.
$apiClientPath = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "frontend\src\shared\api\client.ts")).Path
$frontendFiles = Get-SourceFiles @("frontend\src") @("*.ts", "*.tsx")
foreach ($file in $frontendFiles) {
    if ($file.FullName -eq $apiClientPath) {
        continue
    }
    $matches = Select-String -Path $file.FullName -Pattern 'fetch\(', 'XMLHttpRequest', '\baxios\b', '["'']\/api\/' -AllMatches
    foreach ($match in $matches) {
        Add-Violation ("{0}:{1}: frontend API access must use frontend/src/shared/api/client.ts: {2}" -f (Relative-Path $file.FullName), $match.LineNumber, $match.Line.Trim())
    }
}

$frontendLib = Join-Path $RepoRoot "frontend\src\lib"
if (Test-Path -LiteralPath $frontendLib) {
    $parallelClients = Get-ChildItem -LiteralPath $frontendLib -Recurse -File -Include "*api*.ts", "*client*.ts", "*fetch*.ts" -ErrorAction SilentlyContinue
    foreach ($file in $parallelClients) {
        Add-Violation ("{0}: do not reintroduce parallel frontend API clients under frontend/src/lib" -f (Relative-Path $file.FullName))
    }
}

# Stale identifiers that previously represented legacy behavior or dead abstractions.
$staleFiles = Get-SourceFiles @("backend\app", "frontend\src", "config", "docs", "scripts") @("*.py", "*.ts", "*.tsx", "*.md", "*.yaml", "*.yml", "*.ps1")
$stalePatterns = @(
    "domain_plugins",
    "register_domain_plugin",
    "get_domain_plugin",
    "medical_inpatient_zh_code9",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/chatgpt/complete"
)
foreach ($file in $staleFiles) {
    if ($file.FullName -eq $PSCommandPath) {
        continue
    }
    # docs/DECISIONS.md is the decision log; it must be allowed to record
    # which legacy identifiers are deliberately retired. The stale-identifier
    # check still covers all live code and live docs.
    $decisionsLogPath = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "docs\DECISIONS.md")).Path
    if ($file.FullName -eq $decisionsLogPath) {
        continue
    }
    $matches = Select-String -Path $file.FullName -Pattern $stalePatterns -SimpleMatch
    foreach ($match in $matches) {
        Add-Violation ("{0}:{1}: stale legacy identifier remains: {2}" -f (Relative-Path $file.FullName), $match.LineNumber, $match.Line.Trim())
    }
}

# Generated files should be removed before a Codex completion report.
if (-not $SkipGenerated) {
    $generatedTargets = @(
        ".pytest_cache",
        "frontend\dist",
        "frontend\.tmp-frontend-tests"
    )
    foreach ($target in $generatedTargets) {
        $path = Join-Path $RepoRoot $target
        if (Test-Path -LiteralPath $path) {
            Add-Violation ("{0}: generated output/cache should not remain in the working tree" -f $target)
        }
    }
    $pycacheDirs = Get-ChildItem -LiteralPath (Join-Path $RepoRoot "backend") -Recurse -Directory -Force -Filter "__pycache__" -ErrorAction SilentlyContinue
    foreach ($dir in $pycacheDirs) {
        Add-Violation ("{0}: generated Python cache should be cleaned before completion" -f (Relative-Path $dir.FullName))
    }
}

# Large files are warnings, not failures. Split only when a file mixes multiple responsibilities.
$largeFiles = Get-SourceFiles @("backend\app", "frontend\src") @("*.py", "*.ts", "*.tsx", "*.css")
foreach ($file in $largeFiles) {
    $lineCount = (Get-Content -LiteralPath $file.FullName | Measure-Object -Line).Lines
    if ($lineCount -gt 800 -or $file.Length -gt 60000) {
        Add-Warning ("{0}: large file ({1} lines, {2} KB). Split only if responsibilities are mixed." -f (Relative-Path $file.FullName), $lineCount, [math]::Round($file.Length / 1KB, 1))
    }
}

if ($Warnings.Count -gt 0) {
    Write-Output "Governance warnings:"
    foreach ($warning in $Warnings) {
        Write-Output "  - $warning"
    }
}

if ($Violations.Count -gt 0) {
    Write-Output "Governance violations:"
    foreach ($violation in $Violations) {
        Write-Output "  - $violation"
    }
    exit 1
}

Write-Output "Project governance check passed."
