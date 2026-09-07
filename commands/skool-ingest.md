Ingest a Skool.com classroom and turn it into working assets.

Use the `skool-course-ingest` skill. Argument is the Skool group slug (the bit
after skool.com/), e.g. `/skool-ingest the-seo-lab`.

Run in order, reporting after each phase:

1. `cd .claude/scripts && uv run python -m skool.cli doctor` — if the Skool session
   is signed out, run `login`, tell Jason a browser window is open for him to sign
   in, and wait for him before continuing.
2. `crawl <group>` — then report how many courses, lessons and videos were found.
   If it finds 0 courses, `probe` the classroom URL and fix the key lists rather
   than guessing.
3. `transcribe <group>` — long job; run it as a long task and report progress per
   course. Then `index <group>`.
4. Distill per-course notes (Phase 3 of the skill).
5. Write the SOPs (`sop-creator`) and draft the new skill (`skill-creator`),
   then show Jason the draft before promoting it into `.claude/skills/`.

Never commit anything under `deliverables/skool/` — course material stays local.
