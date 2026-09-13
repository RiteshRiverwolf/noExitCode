# Serve PaddleOCR-VL-1.6 with Ollama's bundled llama-server (no new install), on 127.0.0.1:8081.
# NOT YET RUN. GPU backend set the same way as start_sarvam_server.ps1 (without it the bundled
# llama-server silently runs on the CPU).
$sp = $PSScriptRoot
$lib = "$env:LOCALAPPDATA\Programs\Ollama\lib\ollama"
$env:GGML_BACKEND_PATH = "$lib\cuda_v12\ggml-cuda.dll"
$env:PATH = "$lib\cuda_v12;$lib;$env:PATH"
$bin = "$lib\llama-server.exe"
$m = "C:\SIH 2026\models\paddleocr-vl-1.6"
$p = Start-Process $bin -ArgumentList @(
    "-m", "`"$m\PaddleOCR-VL-1.6-GGUF.gguf`"",
    "--mmproj", "`"$m\PaddleOCR-VL-1.6-GGUF-mmproj.gguf`"",
    "--host", "127.0.0.1", "--port", "8081",
    "-ngl", "99", "-c", "8192", "--temp", "0"
) -RedirectStandardOutput "$sp\paddle_server.out.log" -RedirectStandardError "$sp\paddle_server.err.log" -WindowStyle Hidden -PassThru
"paddle llama-server PID $($p.Id)"
