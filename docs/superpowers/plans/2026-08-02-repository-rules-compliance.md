# Repository Rules Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `mage` into compliance with shared repository, worktree, and GitHub protection rules without exposing secrets or deleting uncertain worktrees.

**Architecture:** Add one read-only Python repository verifier and one Make target for repeatable local checks. Apply tracked-file and documentation fixes separately from Git metadata migration, then scan tracked content, publish the repository, create the `main` ruleset, and verify each external state change.

**Tech Stack:** Python 3.12, standard library `pathlib`/`subprocess`, pytest, Make, Git, GitHub CLI/API.

## Global Constraints

- `CLAUDE.md` must contain only `@AGENTS.md` and `@AGENTS.local.md`.
- `.gitignore` must include `AGENTS.local.md` and `.claude/settings.local.json`.
- `AGENTS.local.md` stays untracked and local-only.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` must be tracked.
- Version bump is patch: `0.3.9` to `0.3.10`.
- Commits use Conventional Commits and no `Co-Authored-By:` trailer.
- No nested worktree deletion; preserve uncertain worktrees.
- Repository visibility changes only after clean tracked-content secret scan.
- Verification evidence required before completion claims.

---

### Task 1: Add repository verifier and tests

**Files:**
- Create: `scripts/verify_repository.py`
- Create: `tests/unit/test_verify_repository.py`
- Modify: `Makefile`
- Modify: `.gitignore`

**Interfaces:**
- Produces executable `python scripts/verify_repository.py [--root PATH]`.
- Produces `make verify-repository`.
- Verifier exits `0` when all checks pass and `1` with one diagnostic per failure.

- [ ] **Step 1: Write failing tests for required checks**

Test a temporary repository fixture with these cases:

```python
def test_accepts_required_files_and_exact_claude_references(tmp_path):
    write_valid_repository_fixture(tmp_path)
    assert verify(tmp_path) == []


def test_rejects_missing_local_ignore_entries(tmp_path):
    write_valid_repository_fixture(tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    assert any("AGENTS.local.md" in error for error in verify(tmp_path))


def test_rejects_wrong_worktree_path_and_upstream(tmp_path):
    write_valid_repository_fixture(tmp_path)
    result = verify_worktrees(
        tmp_path,
        [(tmp_path / ".claude/worktrees/x", "feature-x", "origin/main")],
    )
    assert "sibling" in " ".join(result)
    assert "origin/feature-x" in " ".join(result)
```

Use injected command results for Git checks; do not invoke real Git in unit tests.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `uv run pytest tests/unit/test_verify_repository.py -q`
Expected: FAIL because verifier module and Make target do not exist.

- [ ] **Step 3: Implement read-only verifier**

Implement these functions with exact signatures:

```python
def verify(root: Path) -> list[str]: ...
def verify_files(root: Path) -> list[str]: ...
def verify_git(root: Path, git: GitProbe) -> list[str]: ...
def verify_worktrees(root: Path, worktrees: list[Worktree]) -> list[str]: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

Use `dataclasses.dataclass(frozen=True)` for `Worktree` and a small `GitProbe` protocol. Check exact required file contents, required ignore strings, no tracked cache artifacts, repository root path, bare Git directory, sibling worktree paths, branch/path agreement, direct fetch refspec, remote URL, and matching `origin/<branch>` upstream. Print `repository verification passed` only on success.

- [ ] **Step 4: Add Make target and ignore entries**

Add `.PHONY` entry and target:

```make
verify-repository: ## Verify repository rules and worktree invariants
	uv run python scripts/verify_repository.py
```

Add exactly these lines to `.gitignore`:

```gitignore
AGENTS.local.md
.claude/settings.local.json
```

Remove `docs/superpowers/` ignore rule. Keep runtime/cache ignores.

- [ ] **Step 5: Run focused tests and verifier**

Run: `uv run pytest tests/unit/test_verify_repository.py -q`
Expected: PASS.

Run: `make verify-repository`
Expected: FAIL only on currently noncompliant worktree topology/upstreams, with actionable diagnostics.

- [ ] **Step 6: Commit local verifier**

```bash
git add scripts/verify_repository.py tests/unit/test_verify_repository.py Makefile .gitignore
git commit -m "feat: add repository compliance verifier"
```

### Task 2: Normalize tracked documentation and version surfaces

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `docs/superpowers/plans/README.md`

**Interfaces:**
- Version becomes `0.3.10` in `pyproject.toml` and lock metadata.
- README documents `make verify-repository`, tracked design/plan paths, public repository status, and GitHub protection policy.

- [ ] **Step 1: Add documentation-path and verifier tests**

Extend `tests/unit/test_verify_repository.py`:

```python
def test_requires_tracked_superpowers_documentation(root):
    assert verify_files(root) == []


def test_requires_single_unreleased_changelog_section(root):
    assert verify_files(root) == []
```

- [ ] **Step 2: Run focused tests and confirm expected failures**

Run: `uv run pytest tests/unit/test_verify_repository.py -q`
Expected: FAIL until tracked documentation and changelog checks are satisfied.

- [ ] **Step 3: Update documentation and version**

Merge all duplicate `[Unreleased]` content into one section. Add one `### Changed` entry for repository compliance. Update README links and development commands. Add AGENTS guidance for `make verify-repository`, secret scanning, and ruleset verification. Bump `pyproject.toml` to `0.3.10`; run `uv lock` so `uv.lock` metadata matches. Add `docs/superpowers/plans/README.md` explaining that implementation plans are tracked there.

- [ ] **Step 4: Run documentation checks**

Run: `uv run pytest tests/unit/test_verify_repository.py -q`
Expected: PASS.

Run: `git diff --check`
Expected: no output.

- [ ] **Step 5: Commit documentation update**

```bash
git add README.md CHANGELOG.md AGENTS.md pyproject.toml uv.lock docs/superpowers/plans/README.md
git commit -m "docs: align repository guidance and release metadata"
```

### Task 3: Repair bare-repository worktree topology

**Files:**
- Modify: Git worktree registrations and branch upstream configuration.
- Modify: `scripts/verify_repository.py` only if migration exposes a missing invariant.
- Test: `tests/unit/test_verify_repository.py`

**Interfaces:**
- Every retained worktree is a sibling of `mage.git/`.
- Every worktree directory name equals branch name.
- Every branch tracks `origin/<branch>` when remote branch exists.

- [ ] **Step 1: Inventory worktrees and active processes**

Run:

```bash
git worktree list --porcelain
ps -ef | grep -E 'claude|python|pytest|mage' | grep -v grep || true
git branch -vv
```

Record nested paths, branch names, dirty state, and active process ownership. Do not move an active worktree.

- [ ] **Step 2: Move only safe nested worktrees**

For each inactive nested worktree whose sibling destination does not exist:

```bash
git worktree move /home/divinefilth/code/github/MistressFilth/mage/mage.git/.claude/worktrees/<id> /home/divinefilth/code/github/MistressFilth/mage/<branch>
```

If destination naming collides or branch mapping is unclear, leave worktree unchanged and record diagnostic. Do not use `git worktree remove`.

- [ ] **Step 3: Repair matching upstreams**

For each retained branch with a remote branch:

```bash
git branch --set-upstream-to=origin/<branch> <branch>
```

Skip branches without matching remote refs. Do not create or delete remote branches.

- [ ] **Step 4: Run topology verification**

Run: `make verify-repository`
Expected: `repository verification passed`.

- [ ] **Step 5: Commit verifier adjustments if needed**

```bash
git add scripts/verify_repository.py tests/unit/test_verify_repository.py
git commit -m "fix: enforce bare worktree repository layout"
```

### Task 4: Scan tracked content and publish repository

**Files:**
- No source changes.
- External state: repository visibility.

**Interfaces:**
- Repository visibility changes from `private` to `public` only after clean scan.

- [ ] **Step 1: Enumerate tracked content**

```bash
git ls-files -z | xargs -0 -r grep -Il . > /tmp/mage-text-files.txt
```

Review generated file list. Exclude ignored files because they are not tracked.

- [ ] **Step 2: Run GitHub secret scan**

Collect tracked text contents and submit them to `mcp__github__run_secret_scanning` for `MistressFilth/mage`. Stop if any credential is reported. Revoke or rotate any confirmed live credential before continuing.

- [ ] **Step 3: Change visibility**

```bash
gh api --method PATCH repos/MistressFilth/mage -f visibility=public
```

Expected: response contains `"visibility":"public"`.

- [ ] **Step 4: Verify visibility**

```bash
gh api repos/MistressFilth/mage --jq '.visibility'
```

Expected: `public`.

### Task 5: Create and verify GitHub main ruleset

**Files:**
- External state: `MistressFilth/mage` rulesets.
- Modify: `AGENTS.md` or README only if returned API capabilities differ from design.

**Interfaces:**
- `main` protected by active ruleset with deletion, non-fast-forward, linear-history, pull-request, and squash-only rules plus required `check` status.

- [ ] **Step 1: Inspect current rulesets after publication**

```bash
gh api repos/MistressFilth/mage/rulesets --jq '.[] | {id,name,target,enforcement,rules}'
```

If an equivalent `main` ruleset exists, update/verify it rather than creating a duplicate.

- [ ] **Step 2: Create ruleset when absent**

```bash
cat > /tmp/mage-main-ruleset.json <<'JSON'
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    {"type": "required_status_checks", "parameters": {"do_not_enforce_on_create": false, "required_status_checks": [{"context": "check", "integration_id": 15368}], "strict_required_status_checks_policy": false}},
    {"type": "pull_request", "parameters": {"allowed_merge_methods": ["squash"], "dismiss_stale_reviews_on_push": false, "dismissal_restriction": {"allowed_actors": [], "enabled": false}, "require_code_owner_review": false, "require_last_push_approval": false, "required_approving_review_count": 0, "required_review_thread_resolution": false, "required_reviewers": []}}
  ]
}
JSON
gh api --method POST repos/MistressFilth/mage/rulesets --input /tmp/mage-main-ruleset.json
```

- [ ] **Step 3: Verify effective protection**

```bash
gh api repos/MistressFilth/mage/rulesets --jq '.[] | select(.name=="main") | {name,target,enforcement,conditions,rules}'
```

Expected: active `main` ruleset contains all supported requested rules. Record unsupported fields or integration errors exactly.

### Task 6: Full verification and release documentation

**Files:**
- Modify: `CHANGELOG.md` only if final external-state result needs recording.
- Test: all repository checks.

- [ ] **Step 1: Run full local gates**

```bash
make verify-repository
make check
make test
```

Expected: all commands exit `0`.

- [ ] **Step 2: Verify Git state**

```bash
git status --short
git log --oneline -5
git worktree list --porcelain
git config --get remote.origin.url
git config --get remote.origin.fetch
```

Expected: clean tree, conventional commits, sibling worktrees, required remote values.

- [ ] **Step 3: Verify GitHub state**

```bash
gh api repos/MistressFilth/mage --jq '{visibility,default_branch}'
gh api repos/MistressFilth/mage/rulesets --jq '.[] | select(.name=="main") | {name,enforcement,rules}'
```

Expected: public repository, active verified `main` ruleset.

- [ ] **Step 4: Commit final documentation if changed**

```bash
git add CHANGELOG.md README.md AGENTS.md
git commit -m "docs: record repository protection state"
```
