"""Core analysis for rulerot. Standard library only."""
from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass, field, asdict

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3}

# Files that coding agents read as standing instructions.
RULE_FILES = [
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules", ".windsurfrules",
    ".clinerules", ".github/copilot-instructions.md", "CONVENTIONS.md",
]
RULE_DIRS = [(".cursor/rules", (".mdc", ".md")), (".clinerules", (".md",)),
             (".github/instructions", (".md",))]

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox"}

LOCKFILES = {
    "package-lock.json": "npm", "npm-shrinkwrap.json": "npm",
    "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "bun.lockb": "bun", "bun.lock": "bun",
    "poetry.lock": "poetry", "uv.lock": "uv", "Pipfile.lock": "pipenv",
}
JS_MANAGERS = {"npm", "pnpm", "yarn", "bun"}
PY_MANAGERS = {"poetry", "uv", "pipenv"}

# Mutually exclusive style choices. Each family maps choice -> regex.
FAMILIES = {
    "indentation": {"tabs": r"\btabs?\b(?! (?:and|or) spaces)", "spaces": r"\b(?:\d+ )?spaces\b(?! (?:and|or) tabs)"},
    "quotes": {"single quotes": r"\bsingle[- ]quotes?\b", "double quotes": r"\bdouble[- ]quotes?\b"},
    "semicolons": {"semicolons": r"\b(?:use|always use|require) semicolons\b", "no semicolons": r"\b(?:no|omit|avoid|never use|without) semicolons\b"},
    "test runner": {"jest": r"\bjest\b", "vitest": r"\bvitest\b", "mocha": r"\bmocha\b", "pytest": r"\bpytest\b", "unittest": r"\bunittest\b"},
    "formatter": {"prettier": r"\bprettier\b", "biome": r"\bbiome\b", "black": r"\bblack\b(?= (?:formatter|to format|for formatting|\.|,|$))", "ruff format": r"\bruff format\b"},
}

NEG = r"(?:never|don't|do not|must not|mustn't|should not|shouldn't|avoid|no longer|stop)"
POS = r"(?:always|must|should|make sure to|be sure to|remember to|prefer|use|do)"
STOP = set("a an the to of in on for and or with your you any all this that these those it its be is are please when".split())


@dataclass
class Directive:
    file: str
    line: int
    text: str
    polarity: int  # +1 or -1
    key: frozenset = field(default_factory=frozenset)


@dataclass
class Finding:
    kind: str
    severity: str
    file: str
    line: int
    message: str
    related: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def discover(root: str) -> list[str]:
    found = []
    for rel in RULE_FILES:
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            found.append(rel)
    for d, exts in RULE_DIRS:
        base = os.path.join(root, d)
        if os.path.isdir(base):
            for dirpath, dirnames, files in os.walk(base):
                for f in sorted(files):
                    if f.endswith(exts):
                        found.append(os.path.relpath(os.path.join(dirpath, f), root))
    # Nested AGENTS.md / CLAUDE.md in subprojects.
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if os.path.samefile(dirpath, root):
            continue
        for f in files:
            if f in ("AGENTS.md", "CLAUDE.md"):
                rel = os.path.relpath(os.path.join(dirpath, f), root)
                if rel not in found:
                    found.append(rel)
    return sorted(set(found))


def split_frontmatter(text: str):
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[4:end], end + 4
    return "", 0


def parse_globs(front: str) -> list[str]:
    for line in front.splitlines():
        m = re.match(r"\s*globs\s*:\s*(.*)$", line)
        if m:
            val = m.group(1).strip().strip("[]")
            return [g.strip().strip("'\"") for g in val.split(",") if g.strip().strip("'\"")]
    return []


def iter_lines(text: str):
    """Yield (lineno, line, in_code_block)."""
    fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith(("```", "~~~")):
            fence = not fence
            yield i, line, True
            continue
        yield i, line, fence


def load_package_scripts(root: str) -> dict[str, set[str]]:
    """Map directory (relative) -> script names for every package.json."""
    out = {}
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if "package.json" in files:
            try:
                with open(os.path.join(dirpath, "package.json"), encoding="utf-8") as fh:
                    data = json.load(fh)
                out[os.path.relpath(dirpath, root)] = set((data.get("scripts") or {}).keys())
            except (OSError, ValueError):
                pass
    return out


def load_make_targets(root: str) -> set[str] | None:
    for name in ("Makefile", "makefile", "GNUmakefile"):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            targets = set()
            with open(p, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    m = re.match(r"^([A-Za-z0-9_.\-/]+(?:\s+[A-Za-z0-9_.\-/]+)*)\s*:(?!=)", line)
                    if m:
                        targets.update(m.group(1).split())
            return targets
    return None


def load_just_recipes(root: str) -> set[str] | None:
    for name in ("justfile", "Justfile", ".justfile"):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            rec = set()
            with open(p, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    m = re.match(r"^@?([A-Za-z0-9_\-]+)[^:=]*:(?!=)", line)
                    if m:
                        rec.add(m.group(1))
            return rec
    return None


def repo_files(root: str) -> list[str]:
    out = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in files:
            out.append(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/"))
    return out


PATH_RE = re.compile(r"`([^`\s]+)`")
NPM_BUILTINS = {"install", "i", "ci", "add", "remove", "uninstall", "update", "init", "publish", "exec",
                "dlx", "x", "link", "audit", "outdated", "why", "list", "ls", "create", "help", "config",
                "version", "pack", "rebuild", "prune", "dedupe", "upgrade", "up", "store", "start", "test"}
CMD_RE = re.compile(r"\b(npm run|pnpm run|yarn run|bun run|pnpm|yarn|bun|make|just)\s+([A-Za-z0-9:_\-.]+)")


def looks_like_path(tok: str) -> bool:
    if tok.startswith(("http://", "https://", "-", "$", "@", "#")) or "://" in tok:
        return False
    if any(c in tok for c in "*?{}<>|=()\"'"):
        return False
    if "/" in tok:
        return True
    return bool(re.search(r"\.(?:py|ts|tsx|js|jsx|mjs|cjs|json|ya?ml|toml|md|mdc|sh|go|rs|java|rb|cfg|ini|lock|sql|css|html)$", tok))


def directive_key(text: str) -> frozenset:
    t = re.sub(r"`[^`]*`", lambda m: " " + m.group(0).strip("`").lower() + " ", text.lower())
    t = re.sub(NEG, " ", t)
    t = re.sub(r"\b(?:always|must|should|make sure to|be sure to|remember to|prefer|please)\b", " ", t)
    toks = [w for w in re.findall(r"[a-z0-9_./:\-]+", t) if w not in STOP and len(w) > 1]
    return frozenset(toks)


def extract_directives(rel: str, text: str) -> list[Directive]:
    out = []
    _, body_start = split_frontmatter(text)
    offset_lines = text[:body_start].count("\n")
    for ln, line, code in iter_lines(text[body_start:]):
        if code:
            continue
        s = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line).strip()
        if not s or s.startswith("#"):
            continue
        for sent in re.split(r"(?<=[.!;])\s+", s):
            low = sent.lower()
            if re.search(r"\b" + NEG + r"\b", low):
                pol = -1
            elif re.search(r"^\s*(?:\*\*)?" + POS + r"\b", low) or re.search(r"\b(?:always|must)\b", low):
                pol = 1
            else:
                continue
            key = directive_key(sent)
            if len(key) >= 2:
                out.append(Directive(rel, ln + offset_lines, sent.strip(), pol, key))
    return out


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def analyze(root: str, files: list[str] | None = None, threshold: float = 0.75) -> dict:
    root = os.path.abspath(root)
    files = files if files is not None else discover(root)
    findings: list[Finding] = []
    directives: list[Directive] = []
    texts = {}
    for rel in files:
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
                texts[rel] = fh.read()
        except OSError as e:
            findings.append(Finding("unreadable", "low", rel, 0, f"could not read rule file: {e}"))

    scripts = load_package_scripts(root)
    all_scripts = set().union(*scripts.values()) if scripts else set()
    make_targets = load_make_targets(root)
    just_recipes = load_just_recipes(root)
    allfiles = repo_files(root)
    allset = set(allfiles)
    alldirs = {os.path.dirname(f) for f in allfiles}
    expanded = set()
    for d in alldirs:
        while d:
            expanded.add(d)
            d = os.path.dirname(d)
    lock_managers = {}
    for f in allfiles:
        b = os.path.basename(f)
        if b in LOCKFILES and "node_modules" not in f:
            lock_managers.setdefault(LOCKFILES[b], f)

    mention_managers: dict[str, list[tuple[str, int]]] = {}
    family_hits: dict[str, dict[str, list[tuple[str, int, str]]]] = {}

    for rel, text in texts.items():
        front, _ = split_frontmatter(text)
        if rel.endswith(".mdc"):
            globs = parse_globs(front)
            for g in globs:
                if not any(fnmatch.fnmatch(f, g) or fnmatch.fnmatch(f, g.replace("**/", "")) for f in allfiles):
                    findings.append(Finding("dead-glob", "medium", rel, 1,
                                            f"rule scope glob `{g}` matches no file in the repo, so this rule never activates"))
        base = os.path.dirname(rel)
        for ln, line, code in iter_lines(text):
            low = line.lower()
            # stale path references
            for m in PATH_RE.finditer(line):
                tok = m.group(1).rstrip(".,:;").lstrip("./") if not m.group(1).startswith("../") else m.group(1)
                if not looks_like_path(tok) or code:
                    continue
                cand = [os.path.normpath(os.path.join(base, tok)).replace(os.sep, "/"), os.path.normpath(tok).replace(os.sep, "/")]
                ok = any(c.rstrip("/") in allset or c.rstrip("/") in expanded for c in cand)
                if not ok and tok.startswith("~"):
                    ok = True
                if not ok:
                    findings.append(Finding("stale-path", "medium", rel, ln,
                                            f"references `{m.group(1)}` but no such file or directory exists"))
            # stale commands
            for m in CMD_RE.finditer(line):
                tool, name = m.group(1), m.group(2).rstrip(".,:;")
                if tool in ("make",):
                    if make_targets is None:
                        findings.append(Finding("stale-command", "high", rel, ln, f"says `make {name}` but the repo has no Makefile"))
                    elif name not in make_targets:
                        findings.append(Finding("stale-command", "high", rel, ln, f"says `make {name}` but the Makefile has no `{name}` target"))
                elif tool == "just":
                    if just_recipes is None:
                        findings.append(Finding("stale-command", "high", rel, ln, f"says `just {name}` but the repo has no justfile"))
                    elif name not in just_recipes:
                        findings.append(Finding("stale-command", "high", rel, ln, f"says `just {name}` but the justfile has no `{name}` recipe"))
                else:
                    if tool in ("pnpm", "yarn", "bun") and name in NPM_BUILTINS:
                        continue
                    if not scripts:
                        findings.append(Finding("stale-command", "high", rel, ln, f"says `{tool} {name}` but the repo has no package.json"))
                    elif name not in all_scripts:
                        findings.append(Finding("stale-command", "high", rel, ln,
                                                f"says `{tool} {name}` but no package.json defines a `{name}` script"))
            # package manager mentions
            for mgr in JS_MANAGERS | PY_MANAGERS:
                if re.search(r"(?<![\w-])" + mgr + r"(?:\s+(?:run|install|add|i|ci|exec|dlx|x|sync|lock|test)\b|x\b)", low) or re.search(r"\buse " + mgr + r"\b", low):
                    if mgr == "npm" and re.search(r"\bnpx\b", low) and not re.search(r"\bnpm\s", low):
                        pass
                    mention_managers.setdefault(mgr, []).append((rel, ln))
            # style families
            if not code:
                for fam, choices in FAMILIES.items():
                    for choice, rx in choices.items():
                        if re.search(rx, low):
                            neg = re.search(r"\b" + NEG + r"\b[^.]*" + rx, low)
                            if neg:
                                continue
                            family_hits.setdefault(fam, {}).setdefault(choice, []).append((rel, ln, line.strip()))
        directives.extend(extract_directives(rel, text))

    # package manager conflicts vs lockfiles and between files
    js_mentioned = {m for m in mention_managers if m in JS_MANAGERS}
    js_locked = {m for m in lock_managers if m in JS_MANAGERS}
    py_mentioned = {m for m in mention_managers if m in PY_MANAGERS}
    py_locked = {m for m in lock_managers if m in PY_MANAGERS}
    for mentioned, locked in ((js_mentioned, js_locked), (py_mentioned, py_locked)):
        if locked:
            for m in sorted(mentioned - locked):
                rel, ln = mention_managers[m][0]
                findings.append(Finding("manager-mismatch", "high", rel, ln,
                                        f"tells the agent to use {m}, but the repo is locked with {', '.join(sorted(locked))} ({', '.join(lock_managers[x] for x in sorted(locked))})",
                                        [f"{r}:{l}" for r, l in mention_managers[m][1:]]))
        elif len(mentioned) > 1:
            ms = sorted(mentioned)
            rel, ln = mention_managers[ms[0]][0]
            findings.append(Finding("manager-conflict", "medium", rel, ln,
                                    f"rule files name more than one package manager ({', '.join(ms)}) and no lockfile settles it",
                                    [f"{r}:{l}" for m in ms for r, l in mention_managers[m]]))

    # style family conflicts
    for fam, choices in family_hits.items():
        if len(choices) > 1:
            names = sorted(choices)
            first = min((h for c in names for h in choices[c]), key=lambda h: (h[0], h[1]))
            findings.append(Finding("style-conflict", "medium", first[0], first[1],
                                    f"conflicting {fam} guidance: " + " vs ".join(names),
                                    [f"{r}:{l} {t}" for c in names for r, l, t in choices[c]]))

    # polarity contradictions
    seen = set()
    for i, a in enumerate(directives):
        for b in directives[i + 1:]:
            if a.polarity == b.polarity:
                continue
            if (a.file, a.line) == (b.file, b.line):
                continue
            sim = jaccard(a.key, b.key)
            if sim >= threshold:
                pair = ((a.file, a.line), (b.file, b.line))
                if pair in seen:
                    continue
                seen.add(pair)
                pos, neg = (a, b) if a.polarity > 0 else (b, a)
                where = "the same file" if a.file == b.file else "another rule file"
                findings.append(Finding("contradiction", "high", pos.file, pos.line,
                                        f"directive is contradicted by a rule in {where} (similarity {sim:.2f})",
                                        [f"{pos.file}:{pos.line} + {pos.text}", f"{neg.file}:{neg.line} - {neg.text}"]))

    findings.sort(key=lambda f: (-SEVERITY_ORDER[f.severity], f.file, f.line, f.kind))
    return {"root": root, "files": files, "directives": len(directives),
            "findings": [f.to_dict() for f in findings]}
