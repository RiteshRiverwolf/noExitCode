# MCP tool servers

Our tools, as MCP servers that both our agent team and AnythingLLM can use.
Run them from the repo root with the project's Python.

| Server | Port | Tools | Status |
|---|---|---|---|
| `web_access` | 8766 | `web_search`, `fetch_page` | Working, tested |
| docgen (stage 0) | 8765 | `create_word_document` | Test version in `stage0/` |

## web_access: the internet, only when a person says yes

This is the only way agents reach the internet. AnythingLLM's own
web-browsing and web-scraping skills are switched off, so its agents have to
go through this server too.

**Start it**

```powershell
.venv\Scripts\python -m mcp_servers.web_access --mode ask
```

It prints an approval link like
`http://127.0.0.1:8766/approvals?token=...`. Open it in a browser on the
same PC. The link is also saved in `logs/web_access_approval_url.txt`.

**Modes**

| Mode | What happens |
|---|---|
| `off` (default) | The tools refuse, and nothing is sent. Use this for the air-gapped setup and the network proof. |
| `ask` | Each search or page waits on the approval page until someone presses **Approve** or **Decline**. No answer in 45 seconds means no. |
| `allow` | Everything goes through without asking, still logged. Demos only. |

The approval page shows the exact search words or web address that would
leave the building. It also warns when they look confidential: equipment
tags like `R-2247`, report numbers, the organisation's name, e-mail
addresses. There's a button to allow everything for 15 minutes.

**What stops an agent approving itself**

- The approval page only answers the local browser, with the secret token.
  Requests from the AnythingLLM container are refused, even with the token.
- `fetch_page` refuses local and internal addresses, so it can't be pointed at
  the approval page or any other service on the network.
- Searches go to DuckDuckGo only, so every destination is known and can be
  allowlisted.

**The log**

Every call is written to `logs/web_access_tool_calls.jsonl`, whether it was
approved, declined or timed out: who asked, what was asked, who decided,
how long it took, and what came back. Each entry includes the fingerprint
(SHA-256) of the entry before it. If anyone edits or deletes an entry, the
check below fails at that point.

```powershell
.venv\Scripts\python -m mcp_servers.audit logs\web_access_tool_calls.jsonl
```

**Tests**

```powershell
# the server on its own (15 checks: approve, decline, timeout, refusals, log)
.venv\Scripts\python -m mcp_servers.web_access --mode ask --approval-timeout 8
.venv\Scripts\python -m mcp_servers.check_web_access

# an AnythingLLM agent using it, with a scripted stand-in approving
.venv\Scripts\python -m mcp_servers.check_anythingllm_web granite4.1:8b
```

**Known limits**

- AnythingLLM stops waiting for a tool after 60 seconds, so approvals must
  happen within 45.
- The address check runs before each request, but the page is downloaded in
  a separate step. A site that changes its DNS answer between the two could
  still slip through ("DNS rebinding"). Outbound blocking at the network level
  remains the real safety net.
- The log proves nobody edited it in the middle. Someone who rewrites the
  whole file could rebuild the chain, so the latest fingerprint should also
  be recorded somewhere else.
