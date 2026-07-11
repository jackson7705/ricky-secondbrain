# Wiring Redis Iris into Ricky

## 1. Env vars — add to `~/SecondBrain/.claude/scripts/.env`

```bash
# Redis Cloud DB (for load_data.py) — from the DB's Configuration → Connect
REDIS_URL="redis://default:<password>@<host>:<port>"

# Context Retriever (required for the query tools) — from the service's Agent key tab
CONTEXT_RETRIEVER_AGENT_KEY="<agent-key>"
CONTEXT_RETRIEVER_MCP_URL="<streamable-http-mcp-endpoint>"   # service Configuration page

# Agent Memory (optional — managed session/long-term memory)
AGENT_MEMORY_ENDPOINT="<endpoint>"
AGENT_MEMORY_STORE_ID="<store-id>"
AGENT_MEMORY_KEY="<service-key>"

# LangCache (optional — semantic LLM-response cache to cut cost)
LANGCACHE_ENDPOINT="<endpoint>"
LANGCACHE_ID="<id>"
LANGCACHE_KEY="<service-key>"
```

## 2. Register the Context Retriever MCP

Redis Iris exposes Context Retriever as a **Streamable-HTTP MCP** authenticated with an
`X-API-Key` header (same pattern as `coleam00/redis-iris-agent`). Add it to Ricky's MCP
config in `~/.claude.json` under `mcpServers`:

```json
"redis-iris": {
  "type": "http",
  "url": "${CONTEXT_RETRIEVER_MCP_URL}",
  "headers": { "X-API-Key": "${CONTEXT_RETRIEVER_AGENT_KEY}" }
}
```

Then add the tool names to `allowed_tools` in `.claude/chat/engine.py` (they arrive as
`mcp__redis-iris__*`). The tools are generated from `entities.py`, e.g.:

- `mcp__redis-iris__get_invoice_by_id`
- `mcp__redis-iris__filter_invoice_by_vendor` · `filter_invoice_by_business` · `filter_invoice_by_month`
- `mcp__redis-iris__find_invoice_by_amount_range`
- `mcp__redis-iris__search_invoice_by_text`
- `…get_/filter_/search_` for `vendor` and `client`

(If you'd rather keep it out of the always-on set, register it through the `mcp-client`
skill instead so it loads on demand.)

## 3. Load data + smoke test

```bash
cd ~/SecondBrain/.claude/scripts
uv add redis
uv run python redis_iris/load_data.py           # push invoices/vendors/clients into Redis
```

Then, in the Redis Cloud Context Retriever console, Auto-detect fields on the loaded keys
and set index types per `entities.py`. Finally, ask Ricky:

> "What did we spend on Vercel?" · "List all Locafy invoices from June" · "Which clients are roofing companies?"

He'll call the generated tools instead of grepping markdown.

## Guardrails
- Context Retriever is **read-through** (agents call generated tools, never touch Redis directly; the agent key scopes access).
- This is **additive** — the Obsidian vault is unchanged and remains the narrative brain. Redis holds a queryable mirror of the *structured* data only.
- Re-run `load_data.py` after big invoice batches to refresh (idempotent). Later: wire it into the weekly cron alongside `memory_lint`.
