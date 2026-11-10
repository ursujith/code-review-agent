$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$launcher = Join-Path $projectRoot "scripts\run_mcp_server.py"
$configDir = Join-Path $projectRoot ".kiro\settings"
$configPath = Join-Path $configDir "mcp.json"
if (-not (Test-Path $python)) { throw "Project virtual environment not found at $python. Create .venv and install dependencies first." }
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
$config = @{ mcpServers = @{} }
if (Test-Path $configPath) {
    $existing = Get-Content $configPath -Raw | ConvertFrom-Json -AsHashtable
    if ($existing -and $existing.ContainsKey("mcpServers")) { $config = $existing }
}
$config.mcpServers["ai-code-review-agent"] = @{ command = $python; args = @($launcher); disabled = $false }
$config | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 $configPath
Write-Host "Kiro MCP configuration written to: $configPath"
Write-Host "Open Kiro's MCP panel and verify the server is connected."
