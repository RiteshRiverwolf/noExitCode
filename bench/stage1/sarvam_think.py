"""Why does Sarvam think when told not to? Try three ways of switching it off."""
import time, httpx

URL = "http://127.0.0.1:8082/v1/chat/completions"
Q = "In one sentence: what does a thickness reading below its minimum mean for a pressure vessel?"
variants = {
    "A kwargs enable_thinking=false": {"messages": [{"role": "user", "content": Q}],
                                        "chat_template_kwargs": {"enable_thinking": False}},
    "B <|nothink|> appended": {"messages": [{"role": "user", "content": Q + "<|nothink|>"}]},
    "C thinking allowed, 3000 tokens": {"messages": [{"role": "user", "content": Q}], "max_tokens": 3000},
}
for name, body in variants.items():
    body = {"temperature": 0.2, "max_tokens": 600, **body}
    t = time.time()
    r = httpx.post(URL, timeout=900, json=body).json()
    m = r["choices"][0]["message"]
    print(f"=== {name}: {time.time() - t:.1f}s, tokens {r['usage']['completion_tokens']}, "
          f"finish {r['choices'][0]['finish_reason']}, reasoning {len(m.get('reasoning_content') or '')} chars")
    print("  reasoning head:", (m.get("reasoning_content") or "")[:200].replace("\n", " "))
    print("  content:", (m.get("content") or "")[:400].replace("\n", " "))
props = httpx.get("http://127.0.0.1:8082/props").json()
print("=== server chat template has nothink:", "<|nothink|>" in (props.get("chat_template") or ""))
