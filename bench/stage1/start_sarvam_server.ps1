# Serve the official Sarvam 30B GGUF (6 shards, architecture bailingmoe2) with Ollama's bundled
# llama-server on 127.0.0.1:8082 -- the settings used for the 3 x 12 summary test (2026-09-12).
#
# GPU: started on its own, this llama-server cannot find Ollama's CUDA backend and silently runs
# on the CPU ("no usable GPU found" in the log). GGML_BACKEND_PATH and PATH fix that.
# --n-cpu-moe 12: the MoE experts of 12 of the 18 MoE layers stay in system RAM, the rest on the
# GPU (~8.8 GB VRAM on the 12 GB RTX 4070). ~53 tokens/s generation.
# Thinking stays ON: "--reasoning off", enable_thinking=false and <|nothink|> were ignored, and
# "--reasoning-budget 0" leaked the thinking into the answer. Give requests a large max_tokens
# (6000) and the model's own settings: temperature 0.7, top_p 0.8, top_k 20.
$sp = $PSScriptRoot
$lib = "$env:LOCALAPPDATA\Programs\Ollama\lib\ollama"
$env:GGML_BACKEND_PATH = "$lib\cuda_v12\ggml-cuda.dll"
$env:PATH = "$lib\cuda_v12;$lib;$env:PATH"
$m = "C:\SIH 2026\models\sarvam-30b\sarvam-30b-Q4_K_M.gguf-00001-of-00006.gguf"
$p = Start-Process "$lib\llama-server.exe" -ArgumentList @(
    "-m", "`"$m`"", "--host", "127.0.0.1", "--port", "8082",
    "-ngl", "99", "--n-cpu-moe", "12", "-c", "8192", "--jinja"
) -RedirectStandardOutput "$sp\sarvam_server.out.log" -RedirectStandardError "$sp\sarvam_server.err.log" -WindowStyle Hidden -PassThru
"sarvam llama-server PID $($p.Id) -- check $sp\sarvam_server.err.log for 'CUDA0'"
