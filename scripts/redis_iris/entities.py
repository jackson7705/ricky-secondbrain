"""Redis Iris Context Retriever — the "define once" data model for Ricky.

Each entity maps Ricky's existing structured data to a Redis key pattern + typed
fields. The field index type determines which MCP tool Context Retriever
auto-generates:

    PK       -> get_<entity>_by_id
    TAG      -> filter_<entity>_by_<field>          (exact match)
    TEXT     -> search_<entity>_by_text             (full-text)
    NUMERIC  -> find_<entity>_by_<field>_range      (min/max)

Enter these in the Redis Cloud Context Retriever console (entity name + key
template), then Auto-detect fields and set the index types below. `load_data.py`
writes records under these exact key templates.
"""

ENTITIES = {
    # Every filed/queued receipt from the invoice-router ledger.
    "invoice": {
        "key_template": "invoice:{id}",  # id = message_id
        "source": "invoice-router/pending-clarification.json",
        "fields": {
            "vendor": "TAG",       # filter_invoice_by_vendor  ("all Vercel invoices")
            "business": "TAG",     # filter_invoice_by_business ("Locafy vs Wonderly")
            "month": "TAG",        # filter_invoice_by_month    ("2026-06")
            "status": "TAG",       # filter_invoice_by_status   (applied/awaiting/declined)
            "amount": "NUMERIC",   # find_invoice_by_amount_range ($50-$100)
            "use": "TEXT",         # search_invoice_by_text
            "subject": "TEXT",
        },
    },
    # Known vendors (from vendor-memory + the vault vendors/ pages).
    "vendor": {
        "key_template": "vendor:{id}",  # id = slug
        "source": "invoice-router/vendor-memory.json",
        "fields": {
            "name": "TEXT",        # search_vendor_by_text
            "business": "TAG",     # filter_vendor_by_business
            "category": "TEXT",
        },
    },
    # ClickUp team tasks (pulled live via the ClickUp API).
    "task": {
        "key_template": "task:{id}",
        "source": "ClickUp API (team tasks in CLICKUP_WORKSPACE_ID)",
        "fields": {
            "name": "TEXT",         # search_task_by_text
            "status": "TAG",        # filter_task_by_status
            "status_type": "TAG",   # filter_task_by_status_type  (open/closed/done)
            "assignee": "TAG",      # filter_task_by_assignee     ("what's on Gavin's plate")
            "list": "TAG",          # filter_task_by_list
            "priority": "TAG",      # filter_task_by_priority
            "due_ymd": "NUMERIC",   # find_task_by_due_ymd_range  (YYYYMMDD; 0 = no due date)
        },
    },
    # Locafy SEO/GSC clients (from locafy-gsc-reporting known properties).
    "client": {
        "key_template": "client:{id}",  # id = slug
        "source": "locafy-gsc-reporting known properties",
        "fields": {
            "name": "TEXT",         # search_client_by_text
            "property_url": "TAG",  # filter_client_by_property_url
            "business": "TAG",      # filter_client_by_business
            "industry": "TEXT",
        },
    },
}
