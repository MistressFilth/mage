## Task 1: ruff exception-handling cluster (BLE001 + S110 + S112 + B017 = 13 errors)

**Files:**
- Modify: `src/mage/artifacts/cosmetic_state.py:56` (BLE001)
- Modify: `src/mage/cli.py:336,488` (BLE001)
- Modify: `src/mage/orchestration/cosmetic_apply.py:137,159` (BLE001)
- Modify: `src/mage/orchestration/cosmetic_watcher.py:96,116` (BLE001 + S112)
- Modify: `tests/unit/test_cli.py:110,248` (BLE001 + S110)
- Modify: `tests/features/test_e2e_mage_run_no_dry_run.py:20` (BLE001)
- Modify: `tests/unit/test_host_overrides.py:59` (B017)
- No new tests.
- No interfaces consumed or produced by other tasks (independent).

- [ ] **Step 1: Capture the baseline count**

Run: `cd <worktree> && uv run ruff check src tests --select BLE001,S110,S112,B017 --output-format=concise 2>&1 | tee /tmp/plan19-task1-baseline.txt`
Expected: 13 errors. The concise list shows file:line:rule per error.

- [ ] **Step 2: Read the file and apply BLE001 fix at `cosmetic_state.py:56`**

Open `src/mage/artifacts/cosmetic_state.py` lines 50-60:

```python
def load_state(path: Path) -> CosmeticAppliedState:
    if not path.exists():
        return CosmeticAppliedState()
    data = yaml.safe_load(path.read_text()) or {}
    return CosmeticAppliedState(**data)
except Exception:
    return CosmeticAppliedState()
```

Wait, the function as shown doesn't include the `try` block — read the file to see the actual context. The fix:

```python
def load_state(path: Path) -> CosmeticAppliedState:
    if not path.exists():
        return CosmeticAppliedState()
    try:
        data = yaml.safe_load(path.read_text()) or {}
        return CosmeticAppliedState(**data)
    except (yaml.YAMLError, OSError, pydantic.ValidationError):
        return CosmeticAppliedState()
```

(The exact import set depends on the file. `yaml` is already imported; `pydantic` may need an import for `ValidationError`. Check the file and add the import if missing.)

- [ ] **Step 3: Apply the equivalent BLE001 fix to the other 7 sites**

For each remaining BLE001 site, read the context and replace `except Exception:` (or `except BaseException:`) with a specific exception tuple. The right tuple depends on what the try-block does:

- `src/mage/cli.py:336,488` — narrow to `(OSError, yaml.YAMLError)` or `(click.UsageError, yaml.YAMLError)` depending on context. Read the file.
- `src/mage/orchestration/cosmetic_apply.py:137,159` — narrow to `(yaml.YAMLError, OSError)`.
- `src/mage/orchestration/cosmetic_watcher.py:96,116` — narrow to `(OSError, ValueError, KeyError)`.

For `test_cli.py:110` (BLE001 `except BaseException`), narrow to `(OSError,)` or similar.

- [ ] **Step 4: Fix S110 at `tests/unit/test_cli.py:248`**

The pattern is `try: ... except: pass`. Replace with:

```python
try:
    # original body
except (OSError, ValueError) as e:
    # log or document the deliberate no-op
    pass
```

Read the file for the exact try-block and choose the right exception types.

- [ ] **Step 5: Fix S112 at `src/mage/orchestration/cosmetic_watcher.py:96`**

The pattern is `try: ... except: continue`. Replace with:

```python
try:
    # original body
except (OSError, ValueError) as e:
    logger.debug("continuing after %s in cosmetic watcher: %s", type(e).__name__, e)
    continue
```

The `logger` is already imported in this file. Use the existing logger.

- [ ] **Step 6: Fix B017 at `tests/unit/test_host_overrides.py:59`**

The pattern is `pytest.raises(Exception)`. Replace with the specific exception class the test intends to catch. Read the test and the function-under-test to determine the right class.

- [ ] **Step 7: Verify the cluster count is 0**

Run: `cd <worktree> && uv run ruff check src tests --select BLE001,S110,S112,B017`
Expected: 0 errors.

- [ ] **Step 8: Run full test suite**

Run: `cd <worktree> && make test`
Expected: all tests pass (output pristine for new errors; 7 pre-existing `PytestCollectionWarning` for `TestabilityReviewer` may still appear, that's pre-existing).

- [ ] **Step 9: Stash comparison (no-regression check)**

Run:

```bash
cd <worktree> && git stash push -u -m "plan19-task1-wip"
uv run ruff check src tests --output-format=concise 2>&1 | tail -3
git stash pop
```

Expected: the clean baseline shows the same 41 ruff errors (or fewer) and the post-fix count drops to 28 (41 - 13 = 28). If post-fix is HIGHER than baseline, an error was introduced — STOP and investigate.

- [ ] **Step 10: Commit**

```bash
cd <worktree> && git add src tests
git commit -m "refactor: narrow exception handling (BLE001, B017, S110, S112)"
```

---

