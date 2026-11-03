#!/usr/bin/env pwsh
# 一键跑一篇：.\run.ps1 -Doc <文档ID> -Name "part251"
param(
  [string]$Name = "口播成品",
  [Parameter(Mandatory=$true)][string]$Doc,
  [string]$Images = "C:\Users\发\Desktop\250",
  [string]$BgmName = "Sustained",
  [string]$Voice = "云希"
)
$ErrorActionPreference = "Stop"
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = "C:\Users\发\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" }
if (-not $env:MDOCS_TOKEN) { Write-Error "请先设置 MDOCS_TOKEN" }
Set-Location $PSScriptRoot
& $py -m jyauto run --name $Name --doc $Doc --force --voice $Voice --images $Images --bgm-name $BgmName
& $py -m jyauto sheet $Name
& $py -m jyauto report $Name
