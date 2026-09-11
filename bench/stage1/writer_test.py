"""Summary-writer comparison: same 12 reports, same facts, same checker, N runs each.

    python writer_test.py ollama:granite4.1:8b 3
    python writer_test.py llamacpp:http://127.0.0.1:8082 3 --label sarvam-30b

Mirrors workbench.prose.write_summary (one repair attempt, then the code
fallback) but talks to either Ollama or a llama-server OpenAI endpoint, so a
model outside Ollama can be judged by exactly the same rules.
Thinking is switched off for both (Ollama think=false; llama-server
chat_template_kwargs enable_thinking=false).
"""
import json, sys, time
from pathlib import Path
import httpx

sys.path.insert(0, r"C:\SIH 2026")
from workbench.evidence import from_ground_truth
from workbench.rules import evaluate
from workbench.prose import SYSTEM, STYLE_ONLY, check, facts_for_model

OUT = Path(__file__).parent / "writer_results"
OUT.mkdir(exist_ok=True)
DOCS = [f"insp_{n}" for n in range(1000, 1012)]


# Per-model settings. Default: thinking off, low temperature. "sarvam": the model's own
# published Writing-Bench settings (temperature 0.7, top_p 0.8, top_k 20) with thinking
# allowed and room for it -- Sarvam 30B would not switch thinking off (2026-09-12).
PROFILES = {
    "default": {"temperature": 0.2, "max_tokens": 600, "chat_template_kwargs": {"enable_thinking": False}},
    # 6000: a one-sentence question used all of a 3000-token budget on thinking (58 s, no answer).
    "sarvam": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "max_tokens": 6000},
}
PROFILE = sys.argv[sys.argv.index("--profile") + 1] if "--profile" in sys.argv else "default"


def chat(backend: str, messages: list[dict]) -> tuple[str, dict]:
    kind, _, target = backend.partition(":")
    if kind == "ollama":
        r = httpx.post("http://127.0.0.1:11434/api/chat", timeout=600, json={
            "model": target, "messages": messages, "stream": False, "think": False,
            "options": {"temperature": 0.2, "num_ctx": 4096}}).json()
        if "error" in r:
            raise RuntimeError(r["error"])
        return r["message"]["content"].strip(), {"reply_tokens": r.get("eval_count")}
    r = httpx.post(f"{target}/v1/chat/completions", timeout=1800,
                   json={"messages": messages, **PROFILES[PROFILE]}).json()
    if "choices" not in r:
        raise RuntimeError(json.dumps(r)[:300])
    msg = r["choices"][0]["message"]
    return (msg.get("content") or "").strip(), {"reply_tokens": r.get("usage", {}).get("completion_tokens"),
                                                "finish": r["choices"][0].get("finish_reason"),
                                                "thinking_chars": len(msg.get("reasoning_content") or "")}


def one(backend: str, doc: str) -> dict:
    ev = from_ground_truth(doc)
    dec = evaluate(ev)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": facts_for_model(ev, dec)}]
    attempts = []
    t0 = time.time()
    for i in (1, 2):
        try:
            text, meta = chat(backend, messages)
        except Exception as e:
            attempts.append({"attempt": i, "error": f"{type(e).__name__}: {e}"})
            break
        problems = check(text, ev, dec)
        safety = [p for p in problems if not p.startswith(STYLE_ONLY)]
        attempts.append({"attempt": i, "text": text, "problems": problems, **meta})
        if not problems:
            return {"doc": doc, "result": "clean" if i == 1 else "repaired", "attempts": attempts,
                    "seconds": round(time.time() - t0, 1), "words": len(text.split())}
        if not safety and i == 2:
            return {"doc": doc, "result": "long but accurate", "attempts": attempts,
                    "seconds": round(time.time() - t0, 1), "words": len(text.split())}
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "Your summary has these problems: " + "; ".join(problems)
                      + ". Rewrite it, fixing them, using only the facts given."}]
    return {"doc": doc, "result": "fallback" if "error" not in attempts[-1] else "error", "attempts": attempts,
            "seconds": round(time.time() - t0, 1)}


def main():
    backend, runs = sys.argv[1], int(sys.argv[2])
    label = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else backend.split(":", 1)[1].replace(":", "_")
    allres = []
    for run in range(1, runs + 1):
        for doc in DOCS:
            r = one(backend, doc)
            r["run"] = run
            allres.append(r)
            first = r["attempts"][0].get("problems", r["attempts"][0].get("error"))
            print(f"run {run} {doc}: {r['result']:18} {r['seconds']:>6}s  first-try problems: {first}", flush=True)
    (OUT / f"{label}.json").write_text(json.dumps(allres, indent=2, ensure_ascii=False), encoding="utf-8")
    counts = {}
    for r in allres:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    caught = sum(1 for r in allres for a in r["attempts"]
                 if any(not p.startswith(STYLE_ONLY) for p in a.get("problems", [])))
    secs = sorted(r["seconds"] for r in allres)
    print(f"TOTAL {label}: {len(allres)} summaries: {counts}; attempts with a safety problem caught: {caught}; "
          f"median {secs[len(secs) // 2]}s")


if __name__ == "__main__":
    main()
