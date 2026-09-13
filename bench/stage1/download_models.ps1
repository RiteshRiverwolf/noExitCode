# Download PaddleOCR-VL-1.6 GGUF (small, first) and the official Sarvam 30B GGUF shards.
# curl -C - resumes a partial file if this is re-run.
$log = "$PSScriptRoot\download_models.log"
$jobs = @(
    @{ repo = "PaddlePaddle/PaddleOCR-VL-1.6-GGUF"; dir = "C:\SIH 2026\models\paddleocr-vl-1.6"; files = @("PaddleOCR-VL-1.6-GGUF.gguf", "PaddleOCR-VL-1.6-GGUF-mmproj.gguf", "chat_template.jinja", "README.md") },
    @{ repo = "sarvamai/sarvam-30b-gguf"; dir = "C:\SIH 2026\models\sarvam-30b"; files = (1..6 | ForEach-Object { "sarvam-30b-Q4_K_M.gguf-0000$_-of-00006.gguf" }) + @("README.md") }
)
"START $(Get-Date -Format s)" | Out-File $log -Encoding utf8
$failed = 0
foreach ($j in $jobs) {
    New-Item -ItemType Directory -Force $j.dir | Out-Null
    foreach ($f in $j.files) {
        $url = "https://huggingface.co/$($j.repo)/resolve/main/$f"
        $out = Join-Path $j.dir $f
        "GET $f $(Get-Date -Format s)" | Out-File $log -Append -Encoding utf8
        & curl.exe -L --fail --retry 5 --retry-delay 10 -C - -s -S -o $out $url 2>&1 | Out-File $log -Append -Encoding utf8
        if ($LASTEXITCODE -eq 0) {
            "OK   $f $([math]::Round((Get-Item $out).Length / 1GB, 2)) GB $(Get-Date -Format s)" | Out-File $log -Append -Encoding utf8
        } else {
            $failed++
            "FAIL $f curl exit $LASTEXITCODE $(Get-Date -Format s)" | Out-File $log -Append -Encoding utf8
        }
    }
}
"ALL DONE failed=$failed $(Get-Date -Format s)" | Out-File $log -Append -Encoding utf8
