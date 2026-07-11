# Redis Iris integration (scaffold)

Gives Ricky a **structured-data query layer** over his tabular data (invoices, vendors,
clients) via Redis Iris **Context Retriever** — auto-generated MCP tools like
`filter_invoice_by_vendor`, `find_invoice_by_amount_range`, `search_client_by_text`.

**This does NOT replace the Obsidian vault.** The vault stays the human-readable narrative
brain. Redis Iris handles the structured half (precise "what did we spend on Vercel this
quarter" queries) that markdown is bad at. See [[ricky-redis-iris]] memory.

Modeled on `coleam00/redis-iris-agent` (Pydantic AI + Claude + uv + MCP — same stack Ricky runs).

## Status: scaffold — needs your Redis Cloud account + keys to go live

Everything here is ready; the only missing pieces are external signups only Jason can do.

## Setup checklist (do these once)

1. **Create a Redis Cloud database** (free 30 MB tier): https://cloud.redis.io → New Database.
2. **Add the one dependency:** `cd ~/SecondBrain/.claude/scripts && uv add redis`.
3. **Create a Context Retriever service** in the Redis Cloud console:
   - Define the 3 entities from `entities.py` (name + key template) — see that file for the exact table.
   - Auto-detect fields, then set the index types (TAG/TEXT/NUMERIC) per `entities.py`.
   - Generate an **Agent Key** and copy it.
4. *(optional)* Create **Agent Memory** + **LangCache** services if you want managed session memory / LLM-response caching. Copy their keys.
5. **Drop the keys into `~/SecondBrain/.claude/scripts/.env`** — the exact var names are in `mcp_setup.md`.
6. **Load the data:** `uv run python redis_iris/load_data.py` — pushes invoices/vendors/clients into Redis so Context Retriever can index them. Re-run anytime to refresh (idempotent).
7. **Register the MCP** into Ricky per `mcp_setup.md`, then ask Ricky "what did we spend on Vercel?" to confirm.

## Files
- `entities.py` — the "define once" data model (entities, key templates, field index types). Drives both the console setup and the loader.
- `load_data.py` — reads Ricky's structured data (invoice ledger, vendor memory, client list) → writes Redis entity records. Guarded: no-ops with instructions if `REDIS_URL` isn't set.
- `mcp_setup.md` — env vars + how to register the Iris Context Retriever (and optional Agent Memory / LangCache) MCP into Ricky.
