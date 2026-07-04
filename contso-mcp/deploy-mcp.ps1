#requires -Version 7.0
<#
.SYNOPSIS
    Contoso ポリシー MCP サーバーを Azure Container Apps にデプロイします。

.DESCRIPTION
    1. Azure CLI / containerapp 拡張 / リソースプロバイダーを確認・登録
    2. `az containerapp up --source` でクラウドビルド（ローカル Docker 不要）し、
       ACR + Container Apps 環境 + Container App（外部 HTTPS Ingress, port 8000）を作成
    3. 公開 URL をコンソールに出力（認証なし）

.NOTES
    本フォルダー単体でデプロイできます。
#>

[CmdletBinding()]
param(
    [string]$SubscriptionId,
    [string]$ResourceGroup,
    [string]$Location,
    [string]$AppName          = ($env:CONTOSO_MCP_APP_NAME    ?? 'contoso-policy-mcp'),
    [string]$EnvName          = ($env:MCP_ENV_NAME            ?? 'aca-mcps'),
    [string]$AcrName          = ($env:MCP_ACR_NAME            ?? $null)
)

$ErrorActionPreference = 'Stop'
$mcpDir   = $PSScriptRoot

Write-Host '== Contoso MCP サーバー デプロイ (Azure Container Apps) ==' -ForegroundColor Cyan

# --- ルートの .env から接続情報を取得（他リソースと RG を揃える）---------------
$repoRoot = Split-Path -Parent $mcpDir
$rootEnv  = Join-Path $repoRoot '.env'
$envMap   = @{}
if (Test-Path $rootEnv) {
    foreach ($line in Get-Content $rootEnv) {
        $t = $line.Trim()
        if ($t -and -not $t.StartsWith('#') -and $t.Contains('=')) {
            $k, $v = $t -split '=', 2
            $envMap[$k.Trim()] = $v.Trim()
        }
    }
}
if (-not $SubscriptionId) { $SubscriptionId = $envMap['AZURE_SUBSCRIPTION_ID'] ?? $env:AZURE_SUBSCRIPTION_ID }
if (-not $ResourceGroup)  { $ResourceGroup  = $envMap['AZURE_RESOURCE_GROUP']  ?? $env:AZURE_RESOURCE_GROUP ?? 'rg-contoso-mcp' }
if (-not $Location)       { $Location       = $envMap['AZURE_LOCATION']        ?? $env:AZURE_LOCATION ?? 'eastus2' }

# --- 0. 前提確認 ---------------------------------------------------------------
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) が見つかりません。'
}
# SubscriptionId 未指定時は現在の az コンテキストを使用
if (-not $SubscriptionId) { $SubscriptionId = az account show --query id -o tsv 2>$null }
if (-not $SubscriptionId) { throw 'サブスクリプションが特定できません。az login を実行するか -SubscriptionId を指定してください。' }
az account set --subscription $SubscriptionId | Out-Null

Write-Host '[0/3] containerapp 拡張 / プロバイダーを確認...' -ForegroundColor Yellow
az extension add --name containerapp --upgrade --only-show-errors 2>$null | Out-Null
az provider register --namespace Microsoft.App --wait 2>$null | Out-Null
az provider register --namespace Microsoft.OperationalInsights --wait 2>$null | Out-Null
az provider register --namespace Microsoft.ContainerRegistry --wait 2>$null | Out-Null

# --- 1. RG 確認 ----------------------------------------------------------------
az group create -n $ResourceGroup -l $Location --only-show-errors | Out-Null

# --- 2. containerapp up（ソースからクラウドビルド） -----------------------------
Write-Host "[1/2] イメージをビルドして Container App をデプロイ（数分かかります）..." -ForegroundColor Yellow
Push-Location $mcpDir
try {
    $upArgs = @(
        '--name', $AppName,
        '--resource-group', $ResourceGroup,
        '--location', $Location,
        '--environment', $EnvName,
        '--source', '.',
        '--ingress', 'external',
        '--target-port', '8000',
        '--env-vars', 'PORT=8000'
    )
    # ACR 名が指定された場合は、その ACR を明示的に作成・利用（未指定なら up が自動作成）
    if ($AcrName) {
        az acr create -n $AcrName -g $ResourceGroup --sku Basic --admin-enabled true --only-show-errors | Out-Null
        $upArgs += @('--registry-server', "$AcrName.azurecr.io")
    }
    az containerapp up @upArgs
}
finally {
    Pop-Location
}

# コールドスタート（scale-to-zero による初回タイムアウト）を防ぐため最小レプリカを 1 に固定。
# `containerapp up` は --min-replicas を受け付けないため、デプロイ後に update で設定する。
Write-Host "  最小レプリカを 1 に設定（コールドスタート回避）..." -ForegroundColor DarkGray
az containerapp update -n $AppName -g $ResourceGroup --min-replicas 1 --only-show-errors | Out-Null

# --- 4. 公開 URL 取得 -----------------------------------------------------------
$fqdn = az containerapp show -n $AppName -g $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
if ([string]::IsNullOrWhiteSpace($fqdn)) {
    throw 'Container App の FQDN を取得できませんでした。'
}
$mcpUrl = "https://$fqdn/mcp"

Write-Host "[2/2] 公開 URL: $mcpUrl" -ForegroundColor Yellow

Write-Host ''
Write-Host '== 完了 ==' -ForegroundColor Cyan
Write-Host "MCP URL : $mcpUrl"
Write-Host ''
Write-Host 'スモークテスト:' -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe smoke_test.py $mcpUrl"
