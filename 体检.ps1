chcp 65001 >$null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
# 只读体检包装：给 health_check.ps1 传中文标题
& (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'gui\health_check.ps1') -Title 'MiliastraGME 一键体检（只读，不修改任何文件）'