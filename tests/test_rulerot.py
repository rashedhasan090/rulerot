import json
import os
import tempfile
import unittest

from rulerot.core import analyze, discover
from rulerot.cli import main

HERE = os.path.dirname(__file__)
DEMO = os.path.join(HERE, "..", "examples", "demo-repo")


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text)


def kinds(rep):
    return [f["kind"] for f in rep["findings"]]


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.rep = analyze(DEMO)

    def test_discovers_all_rule_files(self):
        self.assertEqual(sorted(self.rep["files"]), [".cursor/rules/react.mdc", "AGENTS.md", "CLAUDE.md"])

    def test_expected_findings(self):
        k = kinds(self.rep)
        for want in ["stale-command", "contradiction", "manager-mismatch", "dead-glob", "style-conflict", "stale-path"]:
            self.assertIn(want, k)
        self.assertEqual(k.count("stale-command"), 2)

    def test_existing_path_not_flagged(self):
        msgs = " ".join(f["message"] for f in self.rep["findings"])
        self.assertNotIn("src/main.ts", msgs)


class UnitTests(unittest.TestCase):
    def test_clean_repo_has_no_findings(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "package.json", json.dumps({"scripts": {"lint": "eslint ."}}))
            write(d, "pnpm-lock.yaml", "")
            write(d, "src/app.py", "")
            write(d, "AGENTS.md", "- Always run `pnpm lint` before pushing.\n- Code lives in `src/app.py`.\n- Use pnpm install.\n")
            self.assertEqual(analyze(d)["findings"], [])

    def test_builtin_subcommands_not_stale(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "package.json", "{}")
            write(d, "AGENTS.md", "Use pnpm install and yarn add as needed.\n")
            self.assertNotIn("stale-command", kinds(analyze(d)))

    def test_code_block_paths_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "AGENTS.md", "```\ncat `nope/file.py`\n```\n")
            self.assertNotIn("stale-path", kinds(analyze(d)))

    def test_contradiction_within_one_file(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "CLAUDE.md", "- Always use relative imports in the server package.\n- Never use relative imports in the server package.\n")
            f = [x for x in analyze(d)["findings"] if x["kind"] == "contradiction"]
            self.assertEqual(len(f), 1)
            self.assertIn("the same file", f[0]["message"])

    def test_unrelated_opposites_not_contradiction(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "AGENTS.md", "- Always write docstrings for public functions.\n- Never commit secrets or API keys.\n")
            self.assertNotIn("contradiction", kinds(analyze(d)))

    def test_manager_conflict_without_lockfile(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "AGENTS.md", "Use yarn install.\n")
            write(d, ".github/copilot-instructions.md", "Use bun install.\n")
            self.assertIn("manager-conflict", kinds(analyze(d)))

    def test_missing_makefile(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "AGENTS.md", "Run make check.\n")
            f = analyze(d)["findings"]
            self.assertTrue(any("no Makefile" in x["message"] for x in f))

    def test_live_glob_not_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "components/Button.tsx", "")
            write(d, ".cursor/rules/r.mdc", "---\nglobs: components/**/*.tsx\n---\n- Prefer hooks.\n")
            self.assertNotIn("dead-glob", kinds(analyze(d)))

    def test_nested_agents_md_discovered(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "packages/api/AGENTS.md", "x\n")
            self.assertIn("packages/api/AGENTS.md", discover(d))

    def test_nested_relative_path_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "packages/api/handler.py", "")
            write(d, "packages/api/AGENTS.md", "Handlers go in `handler.py`.\n")
            self.assertNotIn("stale-path", kinds(analyze(d)))


class CliTests(unittest.TestCase):
    def test_fail_on_gate(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main([DEMO, "--fail-on", "high"]), 1)
            self.assertEqual(main([DEMO]), 0)

    def test_json_and_md(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main([DEMO, "--format", "json"])
        self.assertIn("findings", json.loads(buf.getvalue()))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main([DEMO, "--format", "md"])
        self.assertIn("| severity |", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
