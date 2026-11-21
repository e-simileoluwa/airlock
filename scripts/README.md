# Maintenance scripts

Every file in this directory is an entry point a person or a workflow runs by hand. They are
listed here with what they change, because four of them write into the checkout and one can
create issues on GitHub. `AGENTS.md` section 12 treats this directory as protected: read the row
before passing a flag you have not used before.

| Script | Purpose | Flags that change behaviour | Files it writes | Network |
|---|---|---|---|---|
| `dev_setup.sh` | Build the environment `CONTRIBUTING.md` assumes: a virtualenv, the package installed editable, then the dev group whose specifiers it reads out of `pyproject.toml` (task 9.69). | `--print` prints the plan and runs nothing; `PYTHON`, `VENV` and `PIP` choose the interpreter, the virtualenv directory and the pip binary, so `VENV=/tmp/x` keeps the whole run outside the checkout. | `.venv/` at the repository root, and only when it is missing. Both installs write inside that directory rather than into the tracked tree. | yes: each `pip install` reaches the index unless the packages are already in the local cache. |
| `build_site.py` | Regenerate the documentation site's derived blocks from the shipped rule data (task 8.6). | `--check` compares and writes nothing; `--root PATH` picks the repository root to read and write instead of this checkout. | `site/rules.html`, `site/index.html` and `site/data/rules.json`, each replaced between their marker comments. | none |
| `roadmap_progress.py` | Recompute the `ROADMAP.md` progress table from the task lines (task 1.9). | `--check` exits 1 with the correct table on stdout and writes nothing; a positional path selects the roadmap file instead of the one at the repository root. | the block between `PROGRESS:START` and `PROGRESS:END` in the roadmap file it was given. | none |
| `check_roadmap_touched.sh` | Fail a pull request that changes files without updating `ROADMAP.md`, or that updates it and leaves `Last updated` where it was (task 1.9). | The base ref is the single argument, or `origin/$GITHUB_BASE_REF` when no argument is given; with neither it exits 1 rather than guessing. | nothing. It only runs `git diff`, `git merge-base` and `git show`. | none |
| `sync_readme.py` | Refresh the README metrics block and the Shields.io endpoint JSON that the badges read. | `--check` exits 1 when a target is stale and modifies nothing. | the block between `METRICS:START` and `METRICS:END` in `README.md`, and `site/data/badge-*.json`. | none. It writes the endpoint files the badges fetch; it does not fetch anything itself. |
| `bypass_probe.py` | Measure whether the seven bypass cases in `PRD.md` Appendix B are real against somebody else's scanner (roadmap 0.4). | `--script PATH` is required and names the `malware_scan.py` to probe; there is no check mode, and no argument writes into the repository. | nothing here. Each case is staged inside a temporary directory that is removed afterwards. | none |
| `create_wave_issues.sh` | Publish the Wave issue batch in `docs/wave/issues/` (task 1.14). | Dry run unless `--apply`. `--repo owner/name` retargets it away from `posture-sec/airlock` and `--dir PATH` reads a different issue directory; `--apply` still refuses to start when the target has no `Stellar Wave` label. | nothing in the repository. Each body is staged at `/tmp/airlock-wave-body.<slug>.md` before it is posted. | yes, only with `--apply`: it calls `gh issue create` and `gh issue edit` against the target repository. |

Two rules the table depends on, so that a future row cannot quietly break them:

- The dry-run mode is the safe one on every script that has a mode: `--check` reads, compares and
  exits non-zero without touching the tree, which is what CI runs, and `dev_setup.sh`'s `--print`
  does the same for a script whose real mode cannot be checked rather than printed.
- `create_wave_issues.sh` is the only entry point here that can change state outside the
  repository, and `--apply` is the only flag that does it. Everything else is local by default.

`.gitkeep` is in the directory to keep it in git and is not an entry point, so it is not a row.
`tests/unit/test_scripts_index.py` compares this table against the non-hidden files here and
fails if either side gains an entry the other does not have.
