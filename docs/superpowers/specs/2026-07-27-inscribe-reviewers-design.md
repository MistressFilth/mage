# HAILERIS v2 — Inscribe + 7 Reviewers + Verdict Format Design (Plan 3)

**Status:** DRAFT — initial brainstorming concluded 2026-07-27. Resolved decisions integrated. Awaiting user review and writing-plans transition.

**Plan 3 of 6.** Builds on Plan 1 (Foundation) and Plan 2 (Decomposition + Plan). Plan 2 shipped the `mage` package with `MappingArtifact`, `Base85BID`, `FileStatePersistence`, `EventsLog`, `PipelineContext`, `StageNode`, `PipelineGraph`, `MechanicalVerifier`, `HostConfig`, `DecompositionStage`, `PlanArtifact`, and the behavior enumeration sub-step.

## Vision

Build the Inscribe stage of the HAILERIS v2 pipeline: per-scenario, drive each behavior's scenarios from `INSCRIBING` through the mechanical pre-check and 7 judgmental reviewers to `APPROVED`. Provide the structured verdict format (per-reviewer + aggregate), a digest-pinned `VerdictArtifact`, the seven reviewer dimensions, and the CLI surface for inspecting verdicts and resuming after budget-exhaustion halts.

## Resolved Structural Decisions

The following decisions were resolved through brainstorming and are binding for Plan 3's implementation. They extend the parent v2 design doc and Plan 2's R1–R10.

### R11. Inscribe loop unit — full per-scenario lifecycle in one stage

`InscribeStage` runs **once per feature**, looping internally over each behavior from `behaviors.yaml`. For each behavior, it iterates over its scenarios, running each scenario through: draft → mechanical pre-check → 7 reviewers → decision gate → mapping update. The `iteration` counter in `PipelineContext` persists across scenarios of the same feature; mechanical pre-check and 7 reviewers share the same counter (per the Three Amigos author-judge resolution).

Splitting into separate `MechanicalPreCheckStage` / `ReviewerStage` / `ApprovalStage` stages would force each to re-load behavior context, repeat file I/O, and complicate the iteration counter's lifecycle. One stage, internal loop, shared state.

### R12. Sub-BID assignment — at APPROVED transition

Sub-BIDs are assigned **at the moment a scenario transitions to APPROVED**, not at draft time. Rationale: a sub-BID is a permanent identifier for an approved behavior unit; draft text is mutable and may be revised. Assignment happens via `Base85BID.derive(parent_base_bid, scenario_index)` (Plan 3 utility — Plan 1's `Base85BID` gains a derive method). The `sub_bid_assigned` mechanical check is satisfied only after this point.

This locks in the memory's resolution: "Base BID = 5-digit Base85, project-monotonic, assigned in Decomposition. Sub-BID per scenario, also Base85 (uniform encoding, no lowercase-letter rollover)."

### R13. The 7 reviewer dimensions

| # | Dimension | What it checks (judgmental — MechanicalVerifier handles structural) |
|---|---|---|
| 1 | `spec_compliance` | Scenario implements the parent behavior spec; honors `depends_on` and `cross_behavior_links`. |
| 2 | `scenario_clarity` | Given/When/Then readable; single intent; no wandering prose. |
| 3 | `step_grammar` | Declarative phrasing (no imperative leakage like "click" / "type"); step bodies reuse defined steps where applicable. |
| 4 | `testability` | Scenario can become a red/green unit test as written (no hidden coupling, no untestable assertions). |
| 5 | `determinism` | No I/O, time, randomness outside fixtures; deterministic for replay. |
| 6 | `naming_idiom` | Scenario name + tag names follow host conventions (kebab-case, project vocabulary). |
| 7 | `lifecycle_tags` | Required `@status`, `@sub-bid`, and `@cross-behavior-*` tags present and well-formed. |

Each is a separate Pydantic-AI subagent under `agents/inscribe.py` (or `verification/reviewers/<dimension>.py`); all share the same input (draft scenario + spec context + mapping excerpt) and produce the same `ReviewerVerdict` schema.

### R14. Verdict format — per-reviewer + aggregate, digest-pinned

**Per-reviewer verdict** (one file per dimension per draft iteration):

```yaml
dimension: spec_compliance
outcome: pass | fail
draft_hash: <sha256 of (scenario_text + spec_context)>
reviewed_at: <iso8601>
reviewer_id: spec_compliance@v1
findings:
  - id: <uuid>
    severity: critical | major | minor
    location: <line or span ref into scenario draft>
    issue: <one-sentence statement>
    rationale: <why this fails the dimension — mandatory>
    suggestion: <specific fix>
    citations: [<spec/plan refs>]
notes: <freeform reviewer commentary>
```

**Aggregate verdict** (one file per draft iteration, after all 7 reviewers run):

```yaml
draft_hash: <sha256>
aggregated_at: <iso8601>
iteration: <int>
per_dimension:
  spec_compliance:
    outcome: pass
    reviewer_verdict_ref: .haileris/verdicts/<draft_hash>/spec_compliance.yaml
    findings_count: 0
  ...
decision: approved | needs_refactor | needs_human_review
reasoning: <auto-derived explanation citing per_dimension outcomes>
```

Storage path: `<project_dir>/.haileris/verdicts/<draft_hash>.aggregate.yaml` and per-dimension files alongside it.

`VerdictArtifact.finalize/load/revise` mirror `PlanArtifact`'s API surface (digest-pinned, atomic write, event emission). New `VERDICT_RECORDED` / `VERDICT_AGGREGATE_RECORDED` events record every record in the events log.

### R15. Decision gate rules

| Condition | Decision | Action |
|---|---|---|
| All 7 dimensions `pass` | `approved` | Append `ScenarioEntry(sub_bid, scenario_text_hash, lifecycle_status=APPROVED, tests=[], derivations=[])` to parent `BaseBIDEntry.scenarios`; emit `SCENARIO_APPROVED`. |
| Any dimension `fail` AND `iteration < max_iterations` | `needs_refactor` | Increment `iteration`; emit `SCENARIO_NEEDS_REFACTOR`; loop back to draft. |
| Any dimension `fail` AND `iteration >= max_iterations` | `needs_human_review` | Emit `REVIEW_HALT_PERSISTED`; raise `PlanRevisionRequired` (re-using Plan 2's halt mechanism) or a new `ReviewBudgetExhausted` exception — **decision in Plan 6** (deferred). |

`max_iterations` defaults to 3 (per memory), host-configurable via `HostConfig.max_iterations`. Severity (`critical` / `major` / `minor`) affects refactor priority (e.g., critical → revise whole scenario vs minor → revise just the offending step) but **does not** change the gate outcome — any fail triggers refactor regardless of severity.

Rationale is mandatory per finding (memory R4). Refactor step gets the union of `author_verification` (mechanical) findings + 7-reviewer findings with originating gate tagged.

### R16. Approved-gate scope — six rules

Per the memory's approved-gate resolution (now Plan 3's R16, lifting from memory):

1. **Per-scenario independence** — each scenario is approved on its own; one scenario's failure doesn't block siblings.
2. **Sequential per-scenario cycles** — within a behavior, scenarios are processed in source order. (Concurrency deferred to Plan 6.)
3. **Approved before any Etch/Realize sub-phase** — Plan 4 cannot start a scenario's TDD cycle until Inscribe has emitted `SCENARIO_APPROVED`.
4. **Decomposition closed before per-scenario cycle starts** — `INSCRIBE_STARTED` is gated on `DECOMPOSITION_COMPLETED` (Plan 5/6 enforcement; Plan 3 emits the event but doesn't enforce).
5. **Revision re-applies gate** — when Plan 2's `mage plan revise` runs, all scenarios return to `INSCRIBING` for re-approval (Plan 5 territory).
6. **Reversion logged in mapping artifact** — every APPROVED → INSCRIBING transition emits a `ReversionLogEntry` with `sub_bid, timestamp, reason, originating_stage`.

The "approved gate" is the only judgmental gate; `red-test-exists` and `outer-green` (Plan 4) are mechanical.

### R17. Inscribe draft shape — `ScenarioSpec` per behavior

The Inscribe agent receives (per behavior):

- Behavior spec (`name`, `description`, `depends_on`, `notes`, `cross_behavior_links`, BIDs now resolved)
- Existing scenarios under that behavior (so the agent doesn't duplicate)
- Mapping excerpt (read-only: names of sibling behaviors, NOT their BIDs)
- Host config (`enabled_reviewers`, `naming_conventions` if present)

Returns `list[ScenarioSpec]`:

```python
class ScenarioSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str                                # unique within behavior
    gherkin_body: str                        # full Given/When/Then block
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    cross_behavior_tags: list[str] = Field(default_factory=list)
```

System assigns `sub_bid` and `scenario_text_hash` only at APPROVED.

## Architecture

### Module layout (Plan 3 additions)

```
src/mage/
├── artifacts/
│   ├── mapping.py              (Plan 1+2, extended with helper to append ScenarioEntry)
│   ├── plan.py                 (Plan 2, unchanged)
│   └── verdict.py              (Plan 3 NEW — VerdictArtifact + schemas)
├── agents/
│   ├── decomposition.py        (Plan 2, unchanged)
│   └── inscribe.py             (Plan 3 NEW — InscribeAgent + 7 ReviewerAgent subclasses)
├── orchestration/
│   ├── decomposition.py        (Plan 2, unchanged)
│   └── inscribe.py             (Plan 3 NEW — InscribeStage)
├── verification/
│   ├── mechanical.py           (Plan 1, reused unchanged)
│   ├── host_overrides.py       (extended: max_iterations, enabled_reviewers)
│   └── reviewers/              (Plan 3 NEW directory)
│       ├── __init__.py
│       ├── base.py             (ReviewerAgent ABC + shared prompt scaffolding)
│       ├── spec_compliance.py
│       ├── scenario_clarity.py
│       ├── step_grammar.py
│       ├── testability.py
│       ├── determinism.py
│       ├── naming_idiom.py
│       └── lifecycle_tags.py
└── cli.py                      (extended: mage review show, mage review resume)
```

### `InscribeStage` (orchestration)

A `StageNode` (extends Plan 1's `StageNode`) that runs **once per feature** after `DecompositionStage`. Position: after `DECOMPOSITION_COMPLETED`, before any per-scenario `Etch`/`Realize` sub-phase.

**Inputs (from `PipelineContext`):**

- `project_dir: Path`
- `mapping: MappingArtifact`
- `events_log: EventsLog`
- `plan_path: Path`
- `iteration: int` (already incremented by prior halt-resume cycles)
- `host_config: HostConfig`

**Outputs (to disk):**

- `<project_dir>/.haileris/verdicts/<draft_hash>/{dimension}.yaml` (×7 per iteration)
- `<project_dir>/.haileris/verdicts/<draft_hash>.aggregate.yaml`
- `<project_dir>/mapping.yaml` (updated with new `ScenarioEntry` objects)
- `<project_dir>/scenarios/<base_bid>/<scenario_name>.feature` (each approved scenario written to its own file)

**Stage flow:**

1. **Emit `INSCRIBE_STARTED`** with `{feature_id, behavior_count, iteration}`.
2. **Load `behaviors.yaml`** from disk.
3. **For each behavior** in Plan-order (topological order from Plan 2):
   1. Emit `BEHAVIOR_INSCRIBE_STARTED` with `{base_bid, behavior_name}`.
   2. Loop until all scenarios of this behavior are APPROVED:
      1. **Draft** — call `InscribeAgent.run(behavior, existing_scenarios, mapping)`. Returns `list[ScenarioSpec]` (one behavior may produce multiple scenarios).
      2. Emit `SCENARIO_DRAFTED` with `{base_bid, scenario_name, draft_hash}` per scenario.
      3. **Mechanical pre-check** — call `MechanicalVerifier.run(draft_path)` (Plan 1). If any fail:
         - Emit `MECHANICAL_PRECHECK_FAILED` with `{draft_hash, findings}`.
         - Mark the offending scenarios for revision (annotate ScenarioSpec with finding refs).
         - Continue to reviewer step (don't short-circuit; Plan 6 will revisit if it should).
      4. If mechanical passes: emit `MECHANICAL_PRECHECK_PASSED`.
      5. **7 Reviewers** — for each enabled reviewer dimension:
         - Call `ReviewerAgent.run(draft, spec_context)`. Returns `ReviewerVerdict`.
         - Persist verdict via `VerdictArtifact.finalize(verdict_path, content, events_log)`.
         - Emit `REVIEWER_VERDICT_RECORDED` with `{dimension, draft_hash, outcome, findings_count}`.
      6. **Aggregate** — derive `ReviewerAggregate` from the 7 verdicts. Persist via `VerdictArtifact.finalize(aggregate_path, content, events_log)`. Emit `REVIEW_AGGREGATE_RECORDED`.
      7. **Decision gate** (R15 rules):
         - `approved` → for each scenario: assign sub-BID via `Base85BID.derive(parent_base_bid, index)`; append `ScenarioEntry(sub_bid, scenario_text_hash, lifecycle_status=APPROVED, tests=[], derivations=[])` to the parent `BaseBIDEntry.scenarios`; emit `SCENARIO_APPROVED`; write scenario to `<project_dir>/scenarios/<base_bid>/<scenario_name>.feature`; advance.
         - `needs_refactor` → increment `PipelineContext.iteration`; revise drafts per findings union; re-loop (max `max_iterations`).
         - `needs_human_review` → emit `REVIEW_HALT_PERSISTED`; persist halt via the existing Plan 2 mechanism (deferred exception choice to Plan 6); exit cleanly.
      8. Emit `BEHAVIOR_INSCRIBE_COMPLETED` with `{base_bid, scenario_count, iteration}`.
4. **Persist updated mapping** atomically.
5. **Emit `INSCRIBE_COMPLETED`** with `{feature_id, scenario_count, approved_sub_bids, iteration, verdicts_dir}`.

**Disposal / partial-failure semantics:**

- If Inscribe fails mid-behavior: scenarios already APPROVED remain APPROVED (each was committed atomically before moving on). Failed behavior's scenarios remain `INSCRIBING`. Next pipeline run detects `INSCRIBE_STARTED` without matching `INSCRIBE_COMPLETED`, resumes per host config (re-enter Inscribe, re-loop from the failing behavior).
- Mapping updates are append-only on `BaseBIDEntry.scenarios` — concurrent re-entry doesn't conflict (Plan 6 concern, not Plan 3).
- Verdicts are immutable once recorded — revisions create new files keyed by new `draft_hash`.

### `VerdictArtifact` (`artifacts/verdict.py`)

```python
class ReviewerVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)
    dimension: str
    outcome: Literal["pass", "fail"]
    draft_hash: str
    reviewed_at: datetime
    reviewer_id: str
    findings: list[ReviewerFinding] = Field(default_factory=list)
    notes: str = ""

class ReviewerFinding(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    severity: Literal["critical", "major", "minor"]
    location: str
    issue: str
    rationale: str
    suggestion: str = ""
    citations: list[str] = Field(default_factory=list)

class ReviewerAggregate(BaseModel):
    model_config = ConfigDict(frozen=True)
    draft_hash: str
    aggregated_at: datetime
    iteration: int
    per_dimension: dict[str, DimensionSummary]
    decision: Literal["approved", "needs_refactor", "needs_human_review"]
    reasoning: str = ""

class DimensionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: Literal["pass", "fail"]
    reviewer_verdict_ref: str
    findings_count: int

class VerdictArtifact:
    @staticmethod
    def finalize(path: Path, content: BaseModel, events_log: EventsLog) -> str:
        """Write verdict file atomically; emit VERDICT_RECORDED event with digest."""
        ...

    @staticmethod
    def load(path: Path, events_log: EventsLog) -> BaseModel:
        """Load verdict with digest verification against most recent event."""
        ...
```

Mirrors `PlanArtifact`'s API surface — same digest mechanism, same atomic-write pattern, same event emission. Storage layout:

```
.haileris/verdicts/
  <draft_hash>/
    spec_compliance.yaml
    scenario_clarity.yaml
    step_grammar.yaml
    testability.yaml
    determinism.yaml
    naming_idiom.yaml
    lifecycle_tags.yaml
  <draft_hash>.aggregate.yaml
```

### Inscribe Agent (`agents/inscribe.py`)

Pydantic-AI agent with structured output. Receives:

- Behavior spec (with BIDs resolved by stage — agent never sees BIDs as raw strings for *assignment*, but receives parent `base_bid` for context)
- Existing scenarios under that behavior (so duplicates aren't drafted)
- Mapping excerpt (read-only names of sibling behaviors)
- Host config (enabled reviewers, naming conventions)

Returns `list[ScenarioSpec]` (no sub-BIDs, no hashes — system assigns).

```python
class InscribeOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
    scenarios: list[ScenarioSpec]
```

Agent prompt instructs: "Draft scenarios that fully cover the behavior's description. Honor `depends_on` and `cross_behavior_links`. Each scenario has `name` (unique within behavior), `gherkin_body` (full Given/When/Then block), `tags`, `notes`, `cross_behavior_tags`. Reuse existing scenarios where possible — only draft new ones if the existing set has gaps."

### Reviewer Agents (`verification/reviewers/<dimension>.py`)

Seven subclasses of `ReviewerAgent` (one base class in `verification/reviewers/base.py`):

```python
class ReviewerAgent(ABC):
    dimension: str

    def __init__(self, model: Model | None = None) -> None:
        self.model = model or self._default_model()

    @abstractmethod
    def _system_prompt(self) -> str:
        """Dimension-specific rubric and examples."""
        ...

    def run(self, draft: ScenarioSpec, spec_context: SpecContext) -> ReviewerVerdict:
        # Shared: build prompt, run Pydantic-AI agent, validate output,
        # hash draft, emit verdict via VerdictArtifact.
        ...
```

Each reviewer file provides the dimension-specific rubric and example pass/fail scenarios. Shared scaffolding (hashing, event emission, output validation) lives in `base.py`.

For deterministic tests, use Pydantic-AI's `TestModel` with `custom_output_args` returning canned `ReviewerVerdict` objects.

### HostConfig Extension

```python
class HostConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    # Plan 1 fields
    enabled_checks: list[str] | None = None

    # Plan 2 fields
    require_plan_approval: bool = True
    plan_template_path: Path | None = None

    # Plan 3 fields
    max_iterations: int = 3
    enabled_reviewers: list[str] | None = None  # None = all 7 enabled
```

Override file (`<project_dir>/.haileris/config.yaml`):

```yaml
max_iterations: 5
enabled_reviewers:
  - spec_compliance
  - testability
  - lifecycle_tags
```

### Event Type Additions

Extend `EventType` enum (Plan 1+2's `orchestration/events.py`):

```python
class EventType(str, Enum):
    # Plan 1+2 members unchanged

    # Plan 3 — Inscribe stage
    INSCRIBE_STARTED = "inscribe_started"
    INSCRIBE_COMPLETED = "inscribe_completed"
    BEHAVIOR_INSCRIBE_STARTED = "behavior_inscribe_started"
    BEHAVIOR_INSCRIBE_COMPLETED = "behavior_inscribe_completed"
    SCENARIO_DRAFTED = "scenario_drafted"
    MECHANICAL_PRECHECK_PASSED = "mechanical_precheck_passed"
    MECHANICAL_PRECHECK_FAILED = "mechanical_precheck_failed"
    REVIEWER_VERDICT_RECORDED = "reviewer_verdict_recorded"
    REVIEW_AGGREGATE_RECORDED = "review_aggregate_recorded"
    SCENARIO_APPROVED = "scenario_approved"
    SCENARIO_NEEDS_REFACTOR = "scenario_needs_refactor"
    REVIEW_HALT_PERSISTED = "review_halt_persisted"
```

### Mapping Model Extension (small)

Add helper method to `BaseBIDEntry` (or to `MappingArtifact`) for atomic scenario append — YAGNI: keep it as a plain method, no new fields beyond what Plan 2 already has:

```python
# In artifacts/mapping.py (Plan 3 addition)
class MappingArtifact(BaseModel):
    # ... existing fields ...

    def append_scenario(self, base_bid: str, scenario: ScenarioEntry) -> "MappingArtifact":
        """Return a new MappingArtifact with the scenario appended to the matching BaseBIDEntry."""
        new_entries = []
        for entry in self.base_bids:
            if entry.base_bid == base_bid:
                new_entries.append(entry.model_copy(update={"scenarios": [*entry.scenarios, scenario]}))
            else:
                new_entries.append(entry)
        return self.model_copy(update={"base_bids": new_entries})
```

`Base85BID.derive(parent: Base85BID, scenario_index: int) -> Base85BID` — new classmethod on Plan 1's `Base85BID`.

### CLI Commands

**`mage review show`** — display verdict aggregate for a scenario.

```bash
mage review show [--feature <feature_id>] [--base-bid <base_bid>] [--sub-bid <sub_bid>] [--project-dir <path>]
```

Behavior: find latest aggregate by `(base_bid, scenario_name)` or by `sub_bid`, print aggregate + per-dimension summaries. Errors clearly when no verdict found.

**`mage review resume`** — after halt for budget exhaustion or human intervention.

```bash
mage review resume [--project-dir <path>]
```

Behavior: verify a `REVIEW_HALT_PERSISTED` event exists; verify `mapping` shows scenarios in non-`APPROVED` state; re-enter Inscribe stage from halted behavior (or first behavior if not specified).

### Test Strategy

**Unit tests (~34):**

- `test_verdict.py` — `ReviewerVerdict` / `ReviewerFinding` / `DimensionSummary` / `ReviewerAggregate` schema validation, digest pin, decision derivation (12 tests).
- `test_inscribe_models.py` — `ScenarioSpec`, `Base85BID.derive`, mapping `append_scenario` (8 tests).
- `tests/test_reviewers/test_<dimension>.py` — one per reviewer with mocked scenarios covering pass / fail / each severity tier / missing-rationale rejection (14 tests = 2 per dimension).

**Integration tests (~6):**

- `test_inscribe_stage.py` — full happy path with `TestModel` + fake reviewers. Verifies per-behavior loop, draft → pre-check → 7 reviewers → aggregate → APPROVED mapping update. Also covers: needs_refactor with budget remaining, mechanical pre-check failures, needs_human_review halt.

**End-to-end tests (~3):**

- `test_e2e_inscribe.py` — Decomposition → Inscribe end-to-end. Mocks Ascertain + Decomposition outputs, runs full Inscribe, verifies all scenarios APPROVED, mapping updated, events emitted.
- Halt-on-budget-exhausted e2e: verify `max_iterations=2`, force reviewer failure, confirm `REVIEW_HALT_PERSISTED` + halt record.
- Enabled-reviewers subset e2e: verify `enabled_reviewers=[spec_compliance, testability]` skips the other 5 dimensions.

**Test count target:**

~43 new tests in Plan 3. Combined with prior plans' 128 tests, total **~171 tests by end of Plan 3**. Maintain ≥90% line coverage on new code.

## Cross-Plan Dependencies

### What Plan 3 needs from prior plans (already built)

- **`MappingArtifact`, `BaseBIDEntry`, `ScenarioEntry`, `LifecycleStatus`** (Plan 1+2) — for scenario registration and lifecycle transitions.
- **`Base85BID`** (Plan 1) — `Plan 3` extends with `.derive(parent, index)` classmethod.
- **`MechanicalVerifier`** (Plan 1) — reused as-is for the mechanical pre-check; Plan 3 wires it into the Inscribe flow.
- **`FileStatePersistence`, `EventsLog`, `PipelineContext`** (Plan 1+2) — for halt persistence and event emission.
- **`StageNode`, `PipelineGraph`** (Plan 1+2) — Inscribe extends `StageNode`.
- **`PlanArtifact`** (Plan 2) — Plan 3's `VerdictArtifact` mirrors its API surface.
- **`DecompositionStage` outputs** (Plan 2) — `behaviors.yaml`, `mapping.yaml` with `BaseBIDEntry`s, `Plan` (digest-pinned).

### What Plan 3 outputs to downstream plans

- **Inscribe's mapping updates** — every approved scenario is now a `ScenarioEntry` with `lifecycle_status=APPROVED` and a `sub_bid`. Plan 4's Etch reads these.
- **Verdict artifacts** — Plan 5's Settle reads verdict directories to route findings (cosmetic vs spec vs code).
- **Approved-gate scope rules** — Plan 4's Etch refuses to start without `SCENARIO_APPROVED` for that `sub_bid`.
- **`InscribeStage`** — the third stage in the pipeline; Plan 4's `EtchStage` runs after.

## Out of Scope (deferred)

- **Parallel reviewer dispatch** — sequential in Plan 3; concurrency + multi-scenario parallel processing deferred to Plan 6.
- **Settle routing of verdict findings** — Plan 5 decides what to do with the union of mechanical + 7-reviewer findings beyond the immediate revise loop.
- **Forward-only ordering enforcement** (Three Practices) — Plan 6.
- **Reviewer prompt tuning beyond skeleton rubrics** — Plan 3 ships dimension names + minimum rubric; deep prompt iteration deferred.
- **ReviewBudgetExhausted exception vs reusing `PlanRevisionRequired`** — Plan 3 emits `REVIEW_HALT_PERSISTED` and persists halt via the Plan 2 mechanism; whether a new exception type is warranted is Plan 6's call.
- **`mage plan revise` triggering scenario re-inscription** — Plan 5.
- **Per-scenario Etch/Realize sub-phases** — Plan 4.

## Spec Self-Review

1. **Placeholder scan:** No "TBD"/"TODO"/incomplete sections. All decisions pinned.
2. **Internal consistency:** R11–R17 align with architecture and test sections. The 7 dimensions in R13 match the per-dimension tests. Decision gate in R15 matches aggregate schema in R14.
3. **Scope check:** Single plan focus — Inscribe stage + 7 reviewers + verdict format. Etch/Realize (Plan 4), Inspect/Settle (Plan 5), concurrency/Three-Practices enforcement (Plan 6) are all explicitly out of scope.
4. **Ambiguity check:**
   - "Sub-BID at APPROVED transition" (R12) — explicit about timing.
   - "Severity doesn't affect gate outcome" (R15) — explicit that any fail triggers refactor regardless of severity.
   - "Per-scenario independence + sequential per-behavior" (R16) — explicit; concurrency deferred.
   - "Iteration counter persists across scenarios of the same feature" (R11) — explicit about the counter's lifecycle.

## Implementation Notes

Plan 3 follows the writing-plans skill after this spec is approved. Expected task count: ~22–28 (modeled on Plan 2's 22 tasks). Subagent-driven execution recommended per the project's pattern.
