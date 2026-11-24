---
name: github-project
description: Diagnose a GitHub project from a local checkout in read-only mode, using confirmed decisions from a prior discovery step. Use when asked to assess a repo's structure, documentation, tests, CI configuration and conventions.
---

Diagnose the project checked out in the current working directory, guided by the confirmed decisions. **Read-only**: use only the `read`, `grep`, `find` and `ls` tools. Do not write files and do not run commands. If something needs the network, `gh`, or git history, say it could not be verified instead of guessing.

Rules:

- Never execute scripts, installers, or code from the repository.
- Never print tokens, credentials, or secrets. If you find one, report only that one exists and in which file.
- Every claim in the diagnosis must be backed by an `evidence` entry naming the file path (and line when useful) that supports it.

Method:

1. Restate the repository and the goal from the confirmed decisions.
2. Map the layout (`ls`, `find`), then read the README, contribution docs, license, package/build manifests, CI configuration (e.g. `.github/workflows`) and test layout.
3. Compare what you found against each confirmed decision and open question.
4. Finish with a single JSON block, and nothing after it, matching the step contract:

```json
{"diagnosis": "<concise diagnosis>", "evidence": ["<file path> -> <finding>", "..."]}
```
