# qwen3.5:9b scan-reading sweep: 12 reports x 4 scan qualities.
$sp = $PSScriptRoot
$py = "C:\SIH 2026\.venv\Scripts\python.exe"
$docs = 1000..1011 | ForEach-Object { "insp_$_" }
$env:PYTHONIOENCODING = "utf-8"
"START $(Get-Date -Format s)" | Out-File "$sp\sweep_qwen.log" -Encoding utf8
foreach ($q in "medium", "heavy", "light", "clean") {
    & $py "$sp\extract_probe.py" "qwen3.5:9b" $q @docs *> "$sp\sweep_qwen_$q.log"
    "DONE $q exit $LASTEXITCODE $(Get-Date -Format s) :: $((Get-Content "$sp\sweep_qwen_$q.log" | Select-String '^TOTAL') -join ' ')" | Out-File "$sp\sweep_qwen.log" -Append -Encoding utf8
}
"ALL DONE $(Get-Date -Format s)" | Out-File "$sp\sweep_qwen.log" -Append -Encoding utf8
