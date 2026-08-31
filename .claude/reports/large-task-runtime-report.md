# Implementation Report — Large-task runtime support

**Plan**: `.claude/plans/large-task-runtime.md`
**Branch**: `feature/large-task-runtime`
**Status**: COMPLETE

## Summary

Ricky now assigns slide decks and other recognized large jobs a configurable one-hour inactivity window and four-hour total execution ceiling while retaining the existing conservative limits for ordinary chat. Deck requests receive a PPTX-specific directive instead of the contradictory generic PDF directive, and the chat placeholder posts periodic progress updates without cancelling the underlying job.

## Tasks completed

- Added runtime-policy classification and deadline enforcement → `chat/engine.py` (UPDATE)
- Added a dedicated branded PPTX/Drive directive for deck requests → `chat/engine.py` (UPDATE)
- Added normal/large timeout and progress environment settings → `scripts/config.py`, `scripts/.env.example` (UPDATE)
- Wired runtime settings into startup and diagnostics → `chat/main.py` (UPDATE)
- Added non-cancelling periodic progress updates and cancellation cleanup → `chat/router.py` (UPDATE)
- Added runtime, routing, deadline, progress, and failure-isolation tests → `scripts/tests/test_chat_runtime.py` (CREATE)

## Tests added

`scripts/tests/test_chat_runtime.py` covers:

- ordinary and large task classification;
- deck/PPTX directive precedence over generic PDF instructions;
- policy configuration validation;
- hard-ceiling-aware wait calculations;
- periodic progress without collector cancellation;
- adapter progress-update failures without job cancellation.

Result: 15 new tests pass; 88 project tests pass.

## Validation results

- `git diff --check` and Python compilation: PASS
- Full pytest suite: PASS — 88 tests
- Changed-surface Ruff check (existing long lines ignored): PASS
- Targeted mypy module check: PASS — 3 chat modules
- Runtime-policy startup smoke test with temporary SQLite store: PASS
- Repository-wide Ruff baseline: FAIL — 14 pre-existing import-order/line-length findings in adapters, session, and unchanged engine lines
- Repository-wide mypy baseline: FAIL — 23 pre-existing package-import, optional Discord stub, and generic typing findings

## Deviations from the plan

- Router progress polling uses `asyncio.wait()` instead of `wait_for(shield(...))`. `asyncio.wait()` provides the same non-cancelling behavior while avoiding ambiguity between a polling timeout and a `TimeoutError` raised by the collector itself.
- The stock `chat/main.py --test` smoke command was replaced with an in-process temporary-store smoke test because this source checkout has no configured chat surface; `main.py --test` exits before engine construction when credentials are absent.

## Issues encountered

- The initial test environment omitted the declared `dev` extra; validation was rerun with `uv run --extra dev`.
- Existing full-repository lint and type-check debt remains outside this change. No new focused lint or type errors were introduced.
