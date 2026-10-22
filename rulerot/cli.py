from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import SEVERITY_ORDER, analyze


def render_text(rep: dict) -> str:
    out = [f"rulerot: {len(rep['files'])} rule file(s), {rep['directives']} directive(s), {len(rep['findings'])} finding(s)"]
    for f in rep["files"]:
        out.append(f"  scanned {f}")
    for f in rep["findings"]:
        out.append(f"[{f['severity'].upper()}] {f['kind']} {f['file']}:{f['line']}  {f['message']}")
        for r in f["related"]:
            out.append(f"    {r}")
    return "\n".join(out)


def render_md(rep: dict) -> str:
    out = ["# rulerot report", "", f"Scanned {len(rep['files'])} rule file(s), {len(rep['findings'])} finding(s).", ""]
    if rep["findings"]:
        out += ["| severity | kind | location | message |", "|---|---|---|---|"]
        for f in rep["findings"]:
            msg = f["message"].replace("|", "\\|")
            out.append(f"| {f['severity']} | {f['kind']} | `{f['file']}:{f['line']}` | {msg} |")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rulerot", description="Find stale and conflicting rules in AI coding-agent instruction files (AGENTS.md, CLAUDE.md, .cursor/rules, copilot-instructions).")
    p.add_argument("root", nargs="?", default=".", help="repository root (default .)")
    p.add_argument("--file", action="append", help="scan only this rule file (relative to root); repeatable")
    p.add_argument("--format", choices=["text", "json", "md"], default="text")
    p.add_argument("--threshold", type=float, default=0.75, help="token similarity needed to call two opposite directives a contradiction (default 0.75)")
    p.add_argument("--fail-on", choices=["info", "low", "medium", "high", "none"], default="none",
                   help="exit 1 if any finding is at or above this severity")
    p.add_argument("--version", action="version", version=f"rulerot {__version__}")
    a = p.parse_args(argv)
    rep = analyze(a.root, a.file, a.threshold)
    if a.format == "json":
        print(json.dumps(rep, indent=2))
    elif a.format == "md":
        print(render_md(rep))
    else:
        print(render_text(rep))
    if a.fail_on != "none":
        lim = SEVERITY_ORDER[a.fail_on]
        if any(SEVERITY_ORDER[f["severity"]] >= lim for f in rep["findings"]):
            return 1
    return 0
