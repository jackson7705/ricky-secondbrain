#!/usr/bin/env python3
"""gen_launchagents.py — render Ricky's launchd jobs for THIS machine/user.

Reads the templated plists in deploy/launchd/templates/ and substitutes the
per-machine tokens, then writes them to ~/Library/LaunchAgents/ and (optionally)
loads them. Idempotent: safe to re-run — it unloads any existing copy first.

Tokens substituted:
    __PROJECT_DIR__   absolute path to the SecondBrain repo root (contains .claude/)
    __HOME__          the user's home dir
    __LABEL_PREFIX__  launchd label prefix (default com.<slug>secondbrain)
    __LOG_DIR__       where job logs go (default /tmp/<slug>secondbrain)

Usage:
    uv run python deploy/gen_launchagents.py            # render + load all jobs
    uv run python deploy/gen_launchagents.py --print    # dry-run: print, don't write
    uv run python deploy/gen_launchagents.py --no-load  # write plists but don't launchctl load
    uv run python deploy/gen_launchagents.py --only chat,heartbeat
"""
from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "launchd" / "templates"
# repo root = .../SecondBrain ; this file is .../SecondBrain/.claude/deploy/
PROJECT_DIR = HERE.parent.parent


def _config() -> dict[str, str]:
    home = str(Path.home())
    user = getpass.getuser()
    # Label slug: OWNER_LAUNCHD_SLUG lets a teammate namespace their own jobs
    # (e.g. "taylorsecondbrain"). Defaults to "<user>secondbrain".
    slug = os.getenv("OWNER_LAUNCHD_SLUG", f"{user.lower()}secondbrain")
    return {
        "__PROJECT_DIR__": os.getenv("PROJECT_DIR", str(PROJECT_DIR)),
        "__HOME__": home,
        "__LABEL_PREFIX__": os.getenv("LAUNCHD_LABEL_PREFIX", f"com.{slug}"),
        "__LOG_DIR__": os.getenv("RICKY_LOG_DIR", f"/tmp/{slug}"),
    }


def _render(tmpl_text: str, cfg: dict[str, str]) -> str:
    out = tmpl_text
    for token, value in cfg.items():
        out = out.replace(token, value)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="dry", action="store_true", help="print rendered plists, don't write")
    ap.add_argument("--no-load", action="store_true", help="write plists but don't launchctl load")
    ap.add_argument("--only", default="", help="comma-separated job suffixes to render (default: all)")
    args = ap.parse_args()

    cfg = _config()
    label_prefix = cfg["__LABEL_PREFIX__"]
    dst_dir = Path.home() / "Library" / "LaunchAgents"
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    tmpls = sorted(TEMPLATES.glob("*.plist.tmpl"))
    if not tmpls:
        print(f"no templates found in {TEMPLATES}", file=sys.stderr)
        return 1

    print("Rendering Ricky launchd jobs with:")
    for k, v in cfg.items():
        print(f"  {k:18} {v}")
    print()

    Path(cfg["__LOG_DIR__"]).mkdir(parents=True, exist_ok=True)
    uid = os.getuid()
    rendered = 0
    for tmpl in tmpls:
        suffix = tmpl.name[: -len(".plist.tmpl")]
        if only and suffix not in only:
            continue
        text = _render(tmpl.read_text(), cfg)
        label = f"{label_prefix}.{suffix}"
        out_path = dst_dir / f"{label}.plist"

        if args.dry:
            print(f"----- {out_path} -----\n{text}\n")
            rendered += 1
            continue

        dst_dir.mkdir(parents=True, exist_ok=True)
        # Unload any existing copy first (idempotent re-runs)
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                       capture_output=True)
        out_path.write_text(text)
        rendered += 1
        if args.no_load:
            print(f"  wrote  {out_path.name}")
            continue
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(out_path)],
                           capture_output=True, text=True)
        status = "loaded ✓" if r.returncode == 0 else f"load FAILED: {r.stderr.strip()[:80]}"
        print(f"  {out_path.name:50} {status}")

    print(f"\n{rendered} job(s) processed. Manage with: launchctl list | grep {label_prefix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
