# rulerot

Find stale and conflicting rules in the instruction files that AI coding agents read before they touch your repo.

Repos now carry a pile of standing instructions for agents: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`, `.windsurfrules`, `.clinerules`, plus nested `AGENTS.md` files in subpackages. They are written by different people for different tools and nobody tests them. They rot. A script gets renamed and the rule still says `npm run lint`. One file says tabs, another says spaces. The team moved to pnpm but `CLAUDE.md` still says npm. An agent follows whichever rule it reads last, and you get a confusing diff.

`rulerot` checks those files against each other and against the repo itself. It is offline, standard library only, and runs in CI.

## What is novel

Existing markdown linters check formatting, and agent-config linters check one tool's schema. `rulerot` treats the whole set of instruction files as one rulebook and checks it against the actual repository.

| kind | severity | what it catches |
|---|---|---|
| `stale-command` | high | `npm run X`, `pnpm X`, `yarn X`, `bun run X`, `make X`, `just X` where no package.json script, Makefile target, or justfile recipe named X exists (package-manager builtins like `install` are skipped) |
| `manager-mismatch` | high | a rule tells the agent to use one package manager while the lockfile says another (npm/pnpm/yarn/bun, poetry/uv/pipenv) |
| `contradiction` | high | an always/must rule and a never/don't rule about the same thing, within one file or across files (token similarity, `--threshold`) |
| `style-conflict` | medium | mutually exclusive choices across rules: tabs vs spaces, single vs double quotes, semicolons, test runner, formatter |
| `manager-conflict` | medium | rule files name several package managers and no lockfile settles it |
| `stale-path` | medium | a backticked path that does not exist (nested rule files resolve relative to their own folder; fenced code is ignored) |
| `dead-glob` | medium | a `.mdc` rule whose `globs:` match no file, so the rule never activates |

## Install

```
pip install git+https://github.com/rashedhasan090/rulerot
```

Or run it from a clone with `python3 -m rulerot`. Python 3.9+, no dependencies.

## Run

```
rulerot                      # scan the current repo
rulerot path/to/repo --format md
rulerot --format json > rulerot.json
rulerot --fail-on high       # exit 1 in CI if any high finding
rulerot --file AGENTS.md --file CLAUDE.md
```

## Demo

`examples/demo-repo` has an `AGENTS.md`, a `CLAUDE.md`, and a Cursor rule that have drifted apart.

```
$ python3 -m rulerot examples/demo-repo
rulerot: 3 rule file(s), 7 directive(s), 7 finding(s)
  scanned .cursor/rules/react.mdc
  scanned AGENTS.md
  scanned CLAUDE.md
[HIGH] stale-command AGENTS.md:3  says `npm run lint` but no package.json defines a `lint` script
[HIGH] stale-command AGENTS.md:4  says `make test` but the Makefile has no `test` target
[HIGH] contradiction AGENTS.md:7  directive is contradicted by a rule in another rule file (similarity 1.00)
    AGENTS.md:7 + Always commit generated files in the dist folder.
    CLAUDE.md:4 - Never commit generated files in the dist folder.
[HIGH] manager-mismatch CLAUDE.md:5  tells the agent to use pnpm, but the repo is locked with npm (package-lock.json)
[MEDIUM] dead-glob .cursor/rules/react.mdc:1  rule scope glob `components/**/*.tsx` matches no file in the repo, so this rule never activates
[MEDIUM] style-conflict AGENTS.md:5  conflicting indentation guidance: spaces vs tabs
    CLAUDE.md:3 - Use 2 spaces for indentation.
    AGENTS.md:5 - Use tabs for indentation.
[MEDIUM] stale-path CLAUDE.md:6  references `src/api/client.ts` but no such file or directory exists
```

## Tests

```
python3 -m unittest discover -s tests -v
```

## Limits

Contradiction detection is lexical. It catches "Always commit X" against "Never commit X" and close paraphrases, not two rules that conflict only in meaning. Tune `--threshold` down for more recall. Command checks cover package.json scripts, Makefiles, and justfiles.

## License

MIT
