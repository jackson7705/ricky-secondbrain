# Feature: Large-task runtime support

The following plan is complete, but implementation must still validate the current codebase patterns and task sanity before editing.

## Feature Description

Allow Ricky to finish long-running deliverables such as slide decks without the chat watchdog misclassifying a quiet tool call as a hung agent. Keep conservative limits for ordinary chat, provide visible progress during long jobs, and remove contradictory deck-vs-PDF routing.

## User Story

As Ricky's owner, I want large jobs to receive an appropriately long execution window and visible progress so that decks and other substantial deliverables finish instead of aborting after ten silent minutes.

## Problem Statement

`ConversationEngine.handle_message()` applies the same 600-second inactivity timeout and 1,800-second hard ceiling to every request. Agent SDK events pause while a long Bash/render/upload tool call is running, so legitimate work can be cancelled. Separately, `deck` and `slides` match a generic directive that mandates a PDF even though the system prompt mandates `pptx-generator`, creating conflicting instructions. The router leaves the placeholder unchanged for the entire job.

## Solution Statement

Introduce injectable normal and large-task runtime policies, classify large deliverables before prompt mutation, and use monotonic timing with a precise hard ceiling. Give large jobs a one-hour inactivity window and four-hour total window by default, configurable through `.env`. Route deck requests to a dedicated PPTX directive. Update the chat placeholder periodically while processing continues. Cover classification, directive routing, deadline selection, and progress behavior with tests.

## Out of Scope / Non-Goals

- Not included: durable job persistence across host restarts.
- Not included: a database-backed queue or worker fleet.
- Not changing: normal-chat default timeout behavior, tool permissions, cost limits, or session rotation.
- Not changing: final Drive upload requirements.

## Feature Metadata

**Feature Type**: Bug Fix / Enhancement
**Estimated Complexity**: Medium
**Primary Systems Affected**: `chat/engine.py`, `chat/router.py`, runtime configuration, chat tests
**Dependencies**: Python standard library only

## Related Work

**Implements**: User request on 2026-08-31 to make Ricky handle large tasks.
**Epic**: none.

---

## CONTEXT REFERENCES

### Relevant Codebase Files

- `chat/engine.py` lines 58-112 — deliverable detection and generic PDF directive.
- `chat/engine.py` lines 284-326 — system prompt with separate deck/PPTX instruction.
- `chat/engine.py` lines 419-464 — fixed inactivity and hard-ceiling watchdog.
- `chat/router.py` lines 49-116 — placeholder lifecycle and response collection.
- `scripts/config.py` lines 140-150 — chat runtime configuration.
- `scripts/.env.example` section 8 — documented chat limits.
- `chat/main.py` lines 90-145 — engine/router construction and startup reporting.
- `scripts/tests/conftest.py` — test path setup convention.
- `skills/pptx-generator/SKILL.md` lines 30-44 and 627-675 — batch generation and validation explain why decks are long-running.

### New Files to Create

- `scripts/tests/test_chat_runtime.py` — unit tests for policy classification, directives, deadlines, and router progress.
- `.claude/reports/large-task-runtime-report.md` — implementation report.

### Relevant Documentation

- Python standard-library `asyncio.wait_for`, `asyncio.shield`, and `time.monotonic` semantics. No new third-party dependency is required.

### Patterns to Follow

**Naming Conventions:** module constants in uppercase; helpers and configuration in snake_case; constructor-injected settings for testability.
**Error Handling:** log timestamped operational failures and continue when a nonessential progress update fails.
**Logging Pattern:** existing `print(f"[{datetime.now()}] ...")` operational logs.
**Testing Pattern:** pytest classes/functions with direct assertions; `asyncio.run()` for async behavior because `pytest-asyncio` is not a project dependency.

---

## IMPLEMENTATION PLAN

### Phase 1: Runtime policy and routing

- Add a frozen `TaskRuntimePolicy` value object and pure helpers for task classification and the next watchdog timeout.
- Add a dedicated slide-deck directive that mandates PPTX generation and Drive delivery.
- Route slide requests before the generic document directive.

### Phase 2: Engine integration and configuration

- Inject normal/large inactivity and hard-ceiling limits into `ConversationEngine`.
- Select the policy from the original user text before directive injection.
- Replace fixed `datetime` timeout handling with monotonic elapsed time and `min(inactivity, remaining-hard-ceiling)` waits.
- Add environment settings and expose the configured limits at startup.

### Phase 3: User-visible progress

- Add a configurable progress interval to `ChatRouter`.
- Collect the engine response in a task protected with `asyncio.shield` while periodically updating the existing placeholder.
- Ensure failed progress updates never cancel the underlying job.

### Phase 4: Testing and validation

- Test ordinary vs large-task profiles, including decks and explicit large-job language.
- Test that slides receive PPTX instructions while reports retain PDF instructions.
- Test deadline calculations and validation failures.
- Test progress updates while a slow engine remains active and final response replacement.

---

## STEP-BY-STEP TASKS

### UPDATE `chat/engine.py`

- **IMPLEMENT**: task profiles, intent routing, monotonic deadline enforcement, and profile logging.
- **PATTERN**: current module-level regex/directive helpers and timestamped logs.
- **IMPORTS**: `dataclass`, `time`.
- **GOTCHA**: classify before modifying `message.text`; otherwise injected directive words create false large-task matches.
- **VALIDATE**: `cd scripts && uv run python -m pytest tests/test_chat_runtime.py -q`
- **SATISFIES**: AC 1, 2, 3, 4.

### UPDATE `scripts/config.py`, `scripts/.env.example`, and `chat/main.py`

- **IMPLEMENT**: configurable normal/large limits and progress interval with safe defaults.
- **PATTERN**: existing `CHAT_MAX_*` environment parsing and constructor wiring.
- **GOTCHA**: keep defaults backward compatible for ordinary chat.
- **VALIDATE**: `cd scripts && uv run python ../chat/main.py --test`
- **SATISFIES**: AC 1, 3, 6.

### UPDATE `chat/router.py`

- **IMPLEMENT**: shielded response collector and periodic placeholder progress.
- **PATTERN**: existing placeholder update error handling.
- **GOTCHA**: never cancel the collector when a progress timer expires; use `asyncio.shield`.
- **VALIDATE**: `cd scripts && uv run python -m pytest tests/test_chat_runtime.py -q`
- **SATISFIES**: AC 5.

### CREATE `scripts/tests/test_chat_runtime.py`

- **IMPLEMENT**: pure helper tests plus a fake-adapter slow-engine router test.
- **PATTERN**: existing pytest style in `scripts/tests/`.
- **GOTCHA**: avoid real sleeps longer than a few milliseconds and external SDK/network calls.
- **VALIDATE**: `cd scripts && uv run python -m pytest tests/test_chat_runtime.py -q`
- **SATISFIES**: AC 2, 3, 4, 5, 7.

---

## TESTING STRATEGY

### Unit Tests

- Runtime policy selection for ordinary chat, slide decks, full audits, and case-insensitive matching.
- Dedicated PPTX directive precedence over generic PDF routing.
- Remaining hard-ceiling calculation and invalid limit rejection.

### Integration Tests

- Router keeps a slow engine task alive across progress intervals, updates the placeholder, and finally replaces it with the completed response.

### Edge Cases

- Classification must use original text, not injected directives.
- Remaining hard-ceiling shorter than inactivity window.
- Progress update failure must not abort work.
- Missing placeholder must skip progress updates safely.

## VALIDATION COMMANDS

### Level 1: Syntax & Style

```bash
cd scripts && uv run ruff check ../chat config.py tests
```

### Level 2: Unit Tests

```bash
cd scripts && uv run python -m pytest tests -q
```

### Level 3: Type Check

```bash
cd scripts && uv run mypy ../chat config.py
```

### Level 4: Startup Smoke Test

```bash
cd scripts && uv run python ../chat/main.py --test
```

## ACCEPTANCE CRITERIA

- [ ] Ordinary chat retains a 10-minute inactivity and 30-minute total default.
- [ ] Large jobs default to a 60-minute inactivity and four-hour total window.
- [ ] Runtime limits are configurable through environment variables.
- [ ] Hard ceilings are enforced even if no SDK message arrives.
- [ ] Long jobs produce periodic placeholder progress without cancelling work.
- [ ] Slide/deck requests receive only PPTX-specific deliverable instructions, not the generic PDF mandate.
- [ ] Focused and full tests pass with no regression.

## COMPLETION CHECKLIST

- [ ] All tasks completed in order.
- [ ] All validation commands executed.
- [ ] Full test suite passes.
- [ ] Lint and type checks pass or pre-existing failures are documented.
- [ ] Startup smoke test passes where local credentials permit.
- [ ] Implementation report written.

## OPEN QUESTIONS / ASSUMPTIONS

- Assumption: four hours is sufficient for current deck workflows; it remains configurable.
- Assumption: background persistence across machine/process restarts is a separate future capability.
- Assumption: periodic edits are supported by all registered adapters because they already implement final placeholder replacement.

## NOTES

The chosen design retains a meaningful runaway boundary instead of disabling timeouts globally. Large jobs receive a separate profile because increasing ordinary-chat limits would make genuine short-message hangs expensive and slow to recover.

## AMENDMENTS

- None.

**Confidence Score**: 9/10
