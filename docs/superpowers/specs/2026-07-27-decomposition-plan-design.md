# HAILERIS v2 — Decomposition + Plan Design (Plan 2)

**Status:** DRAFT — initial brainstorming concluded 2026-07-27. Resolved decisions from brainstorming session integrated. Awaiting user review and writing-plans transition.

**Plan 2 of 6.** Builds on Plan 1 (Foundation: `MappingArtifact`, `Base85BID`, `FileStatePersistence`, `EventsLog`, `PipelineContext`, `StageNode`, `PipelineGraph`, `MechanicalVerifier`, `HostConfig`, `mage`/`h2` CLI scaffold).

## Vision

Build the Decomposition stage of the HAILERIS v2 pipeline: from Ascertain's output, produce a decomposition artifact (architectural breakdown), enumerate behaviors (assigning base BIDs deterministically), and finalize an immutable Plan (sequential build order). Plus the supporting machinery for Plan integrity (digest-pinning, immutability, halt-based revision).

## Resolved Structural Decisions

The following decisions were resolved through brainstorming and are binding for Plan 2's implementation.

### R1. Plan authorship — same Decomposition agent

The same Decomposition agent produces the behavior enumeration AND the Plan. Splitting into a separate Plan writer would force the second agent to re-derive dependencies just to order them — duplicating reasoning already done. The Plan's sequencing decisions come out of the same reasoning that produced the behaviors.

### R2. Plan format — Markdown + YAML frontmatter

`plan.md` is Markdown with YAML frontmatter. Frontmatter holds ordered `behavior_ids`, per-behavior blocks (`id`, `name`, `depends_on`, `notes`), and `project_id` / `schema_version`. Markdown body holds the build-order rationale, per-behavior sections, and human-readable context. Mirrors superpowers:writing-plans style the parent spec already references.

### R3. Plan immutability — digest-pinned via events log

At Plan finalization, compute SHA256 of the file content and emit an immutable `PLAN_FINALIZED` event with `{plan_path, plan_sha256}`. On every Plan load (`PlanArtifact.load()`), recompute digest; walk events log for the most recent `PLAN_FINALIZED` or `PLAN_REVISED` event for that path. Raise `PlanDigestMismatchError` on mismatch. The Plan stays at `plan.md`; integrity is the digest, not the name.

### R4. Plan-revision gate — persist-then-exit halt

When a stage raises `PlanRevisionRequired` (Settle/Inspect triggers; Plan 5 owns detection), `PipelineGraph.run()` catches it, persists a halt record, and exits cleanly. The next pipeline run resumes from the stage after the halt. The human edits `plan.md` externally, then runs `mage plan revise --reason "<why>" --approver "<id>"` to record the revision (computes new digest, emits `PLAN_REVISED` event with `{plan_path, old_sha256, new_sha256, reason, human_approver}`). Restart succeeds when `PlanArtifact.load()` finds the matching `PLAN_REVISED` event.

### R5. Decomposition outputs — three separate files

Each artifact has one clear responsibility:

| File | Format | Purpose |
|---|---|---|
| `decomposition.yaml` | YAML | Architectural breakdown: parts, components, layers |
| `behaviors.yaml` | YAML | Behavior enumeration with base BIDs assigned |
| `plan.md` | Markdown + YAML frontmatter | Ordered build sequence, immutable post-finalization |
| `mapping.yaml` | YAML | Updated mapping artifact with new `BaseBIDEntry`s |

Three files = three concerns = three audit surfaces. Plan-revision halts target `plan.md` alone without touching architecture or behaviors.

### R6. Behavior schema — rich behavioral fields

Each behavior entry has:

- `id` (Base85 base BID, system-assigned)
- `name`
- `description`
- `depends_on` (list of base-BIDs that must be built first)
- `notes` (free-form context for the Inscribe author)
- `cross_behavior_links` (list of base-BIDs — declared at enumeration)

Out-of-scope and edge cases go in `description` or `notes` rather than separate fields. YAGNI.

### R7. Plan approval — host-project configurable

`HostConfig.require_plan_approval: bool = True` (default: required). When required, Decomposition pauses via the deferred-tool pattern: "Finalize Plan with N behaviors: <list>? [approve / edit / restart-decomposition]". Host projects can override to skip the pause after building trust with the pipeline.

### R8. BID assignment — agent describes, system assigns

The Decomposition agent outputs structured behaviors (`name`, `description`, `depends_on`, `notes`, `cross_behavior_links`) with no BIDs. The Decomposition stage calls `mapping.next_base_bid()` once per behavior to assign BIDs deterministically. The agent reasons; the system bookkeeps. BIDs never appear in the LLM's context.

### R9. Ascertain output schema — Markdown + YAML frontmatter, rich with Three Amigos

Ascertain's output is consumed by Decomposition. Even though Ascertain itself is built later, the schema is defined now:

```yaml
---
feature_id: <string>
feature_name: <string>
scope_statement: <string>
in_scope: [<string>, ...]
out_of_scope: [<string>, ...]
success_criteria: [<string>, ...]
resolved_ambiguities:
  - question: <string>
    decision: <string>
    rationale: <string>
    resolved_by: <string>
deferred_questions: [<string>, ...]
constraints: [<string>, ...]
three_amigos:
  product: <freeform text>
  tester: <freeform text>
  developer: <freeform text>
---

<freeform Markdown narrative of the Ascertain session>
```

Decomposition reads frontmatter for structured reasoning, body for context.

### R10. CLI tool name — `mage`

The CLI tool is `mage`, not `h2`. Plan 1 shipped `h2` in `pyproject.toml`; Plan 2's first housekeeping task is to rename it.

## Architecture

### Module layout

```
src/haileris_v2/
├── artifacts/
│   ├── bid.py               (Plan 1)
│   ├── mapping.py           (Plan 1, extended)
│   ├── plan.py              (Plan 2 NEW — PlanArtifact)
│   └── enumeration.py       (Plan 2 NEW — behavior enumeration logic)
├── orchestration/
│   ├── persistence.py       (Plan 1)
│   ├── events.py            (Plan 1, extended)
│   ├── nodes.py             (Plan 1, extended)
│   ├── graph.py             (Plan 1, extended with halt handling)
│   ├── decomposition.py     (Plan 2 NEW — DecompositionStage)
│   └── plan_template.md     (Plan 2 NEW — default Plan template)
├── verification/
│   ├── mechanical.py        (Plan 1)
│   └── host_overrides.py    (Plan 1, extended)
├── agents/
│   └── decomposition.py     (Plan 2 NEW — DecompositionAgent)
└── cli.py                   (Plan 1, extended)
```

### DecompositionStage (orchestration)

A `StageNode` (extends Plan 1's `StageNode`) that runs **once per feature**. Position: after Ascertain closes, before any per-scenario cycle.

**Inputs (from `PipelineContext`):**

- `project_dir: Path`
- `mapping: MappingArtifact`
- `events_log: EventsLog`
- `ascertain_path: Path` — path to Ascertain's output

**Outputs (to disk):**

- `<project_dir>/decomposition.yaml`
- `<project_dir>/behaviors.yaml`
- `<project_dir>/plan.md`
- `<project_dir>/mapping.yaml` (updated)

**Stage flow:**

1. **Read Ascertain output** from `ascertain_path`. Validate YAML frontmatter schema; raise `AscertainSchemaError` if malformed. Raise `AscertainNotClosedError` if path missing.
2. **Emit `DECOMPOSITION_STARTED`** with `{feature_id, ascertain_path}`.
3. **Run Decomposition agent** (Pydantic-AI). Inputs: Ascertain frontmatter + body + current mapping state (read-only context). Outputs: `architecture: ArchitectureSpec` + `behaviors: list[BehaviorSpec]` (no BIDs).
4. **Write `decomposition.yaml`** atomically (write-temp-then-rename, same pattern as `MappingArtifact.save`).
5. **Call `enumerate_behaviors(behavior_specs, mapping, project_dir)`** (Section: Behavior Enumeration). Returns updated mapping + behaviors.yaml path.
6. **Generate `plan.md`** from behaviors + host-configurable template. Topologically sort by `depends_on`. Fail on cycle.
7. **Approval gate** (if `HostConfig.require_plan_approval == True`):
   - Pause via deferred-tool pattern.
   - Prompt: "Finalize Plan with N behaviors: <list>? [approve / edit / restart-decomposition]"
   - On approve: continue.
   - On edit: halt with reason "human requested edits"; pipeline restart reads Ascertain output unchanged, but human is expected to have adjusted `behaviors.yaml` or `decomposition.yaml` before resuming.
   - On restart: revert mapping changes (drop the BIDs we appended), restart Decomposition.
8. **Finalize Plan** — `PlanArtifact.finalize(plan_path, content, events_log)`. Writes plan.md atomically + emits `PLAN_FINALIZED`.
9. **Emit `DECOMPOSITION_COMPLETED`** with `{feature_id, behavior_count, plan_path, plan_sha256, behaviors_yaml_path}`.

**Disposal / partial-failure semantics:**

- If step 4 fails after writing `decomposition.yaml` but before `behaviors.yaml`: partial decomposition artifact remains on disk. Next pipeline run detects Decomposition-in-progress (no `DECOMPOSITION_COMPLETED` event), reads existing `decomposition.yaml`, and either resumes or restarts based on host config.
- Mapping is only updated after both `behaviors.yaml` and `mapping.yaml` writes succeed (single atomic operation).
- If Plan generation or finalization fails: mapping changes from step 5 are persisted (BIDs are consumed). Plan can be re-finalized via `mage plan revise` without re-running Decomposition.

### Behavior Enumeration Sub-step

Inputs:
- `behavior_specs: list[BehaviorSpec]` — Decomposition agent's structured output (no BIDs).
- `mapping: MappingArtifact` — current state.
- `project_dir: Path`.

Process (`enumerate_behaviors()` in `artifacts/enumeration.py`):

1. **Validate `depends_on` references.** Every entry must resolve to either an existing `BaseBIDEntry.base_bid` in `mapping`, or a base BID that will be assigned to another behavior spec in this enumeration (resolved by name → pending assignment). Raises `BehaviorDependencyError` if unresolvable.
2. **Validate `cross_behavior_links`.** Same rules as `depends_on`.
3. **Build name → behavior spec map** for in-enumeration dependency resolution.
4. **Detect cycles in `depends_on`.** Builds in-memory graph of pending behaviors. Raises `BehaviorDependencyCycleError` if cycle found.
5. **Assign BIDs in topological order.** Iterate behaviors in topo-sorted order. For each, call `mapping.next_base_bid()`. Build `BaseBIDEntry` with assigned BID + spec fields. Track assigned BIDs in local dict for downstream resolution.
6. **Build updated mapping** — append all new `BaseBIDEntry` objects to `mapping.base_bids`.
7. **Write `behaviors.yaml`** atomically:
   ```yaml
   schema_version: 1
   feature_id: <from Ascertain>
   enumerated_at: <iso8601>
   behaviors:
     - id: "00000"
       name: "..."
       description: "..."
       depends_on: []
       notes: "..."
       cross_behavior_links: []
     ...
   ```
8. **Write updated `mapping.yaml`** atomically.
9. **Emit `BEHAVIORS_ENUMERATED`** with `{count, feature_id, mapping_sha256, behaviors_yaml_path}`.
10. **Return** `(updated_mapping, behaviors_yaml_path)`.

**Edge cases:**

- Empty behavior list → raises `NoBehaviorsError`.
- Duplicate behavior names within enumeration → raises `DuplicateBehaviorNameError`.
- Behavior referencing itself in `depends_on` → caught by cycle detection.

### PlanArtifact (`artifacts/plan.py`)

```python
def finalize(plan_path: Path, content: str, 
             events_log: EventsLog) -> str:
    """Write Plan atomically, compute SHA256, emit PLAN_FINALIZED.
    
    Returns plan_sha256. Idempotent if a prior PLAN_FINALIZED event 
    has a matching digest (re-finalize allowed only on match); raises
    PlanAlreadyFinalizedError on digest mismatch (caller must use revise).
    """

def load(plan_path: Path, events_log: EventsLog) -> str:
    """Read Plan with digest verification.
    
    Returns content on success. Raises PlanDigestMismatchError if 
    on-disk digest != recorded digest in most recent event. Raises 
    PlanNotFinalizedError if no prior FINALIZED/REVISED event exists.
    """

def revise(plan_path: Path, content: str, reason: str, 
           human_approver: str, events_log: EventsLog) -> str:
    """Record a Plan revision after a halt.
    
    Writes Plan atomically, computes new SHA256, emits PLAN_REVISED 
    event with {plan_path, old_sha256, new_sha256, reason, human_approver}.
    Returns new plan_sha256. Used by mage plan revise CLI.
    """
```

**Implementation notes:**

- Atomic write uses write-temp-then-rename pattern (same as `MappingArtifact.save`).
- Digest computation: `hashlib.sha256(content.encode("utf-8")).hexdigest()`.
- Event lookup: walks `events_log.read_all()`, filters by `event_type` and `payload["plan_path"]`, returns most recent (sorted by `timestamp`).
- `load()` performs digest check on every call — cheap (one SHA256 per Plan read) and means tampering is caught immediately.

**Exception types:**

```python
class PlanError(Exception): ...
class PlanAlreadyFinalizedError(PlanError): ...
class PlanNotFinalizedError(PlanError): ...
class PlanDigestMismatchError(PlanError): ...
```

### Plan-Revision Gate Mechanism

**Trigger:** Stage raises `PlanRevisionRequired`.

```python
class PlanRevisionRequired(PlanError):
    def __init__(self, reason: str, originating_stage: str, 
                 affected_behaviors: list[str]) -> None: ...
```

**Halt:** `PipelineGraph.run()` wraps the per-stage loop in try/except:

```python
def run(self, initial_context: PipelineContext) -> PipelineContext:
    context = initial_context
    for stage in self.stages:
        try:
            context = stage.run(context)
        except PlanRevisionRequired as e:
            self._persist_halt(context, e)
            raise SystemExit(0) from e
    return context

def _persist_halt(self, context: PipelineContext, 
                  halt: PlanRevisionRequired) -> None:
    # 1. Emit HALT_PERSISTED event
    halt_event = Event(
        timestamp=datetime.now(timezone.utc),
        event_type=EventType.HALT_PERSISTED,
        payload={
            "reason": halt.reason,
            "originating_stage": halt.originating_stage,
            "affected_behaviors": halt.affected_behaviors,
            "context_snapshot": context.model_dump(mode="json"),
        },
    )
    context.events_log.append(halt_event)
    # 2. Save PipelineContext via FileStatePersistence
    state_persistence = FileStatePersistence(
        state_dir=context.project_dir / ".haileris" / "state",
        state_type=PipelineContext,
    )
    state_persistence.save_state(context)
```

**Reconciliation CLI:** `mage plan revise --reason "<why>" --approver "<id>"`

1. Read current `plan.md` content.
2. Compute new SHA256.
3. Find most recent `PLAN_FINALIZED`/`PLAN_REVISED` event for that path → `old_sha256`.
4. Emit `PLAN_REVISED` event with `{plan_path, old_sha256, new_sha256, reason, human_approver}`.
5. Print confirmation.

**Resume:** Pipeline restart loads halted `PipelineContext`, resumes from stage after the halt. First Plan read in resumed stage calls `PlanArtifact.load()`, which finds the most recent `PLAN_REVISED` event matching the new digest — load succeeds.

### Decomposition Agent (`agents/decomposition.py`)

Pydantic-AI agent with structured output. Receives:
- Ascertain frontmatter + body
- Current mapping state (read-only — names of existing behaviors, but not BIDs)
- Host config

Returns structured output:

```python
class ArchitectureSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    parts: list[str]
    components: list[str]
    layers: list[str]
    notes: str = ""

class DecompositionOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
    architecture: ArchitectureSpec
    behaviors: list[BehaviorSpec]
```

`BehaviorSpec` (no BIDs):

```python
class BehaviorSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    notes: str = ""
    cross_behavior_links: list[str] = Field(default_factory=list)
```

Agent prompt instructs: "Produce an architectural decomposition and a structured list of behaviors. Each behavior has name, description, depends_on (other behavior names), notes, cross_behavior_links. Do not assign or reference BIDs."

### CLI Commands

**`mage plan show`** — display Plan + digest.

```
Plan: <project_dir>/plan.md
Digest: <sha256>
Last event: PLAN_FINALIZED at <timestamp>  (or PLAN_REVISED at <timestamp>)

--- plan content (truncated to first 50 lines) ---
<content>
```

**`mage plan revise`** — record a Plan revision after halt.

```bash
mage plan revise --reason "<why>" --approver "<human-id>"
```

Behavior: read current plan.md, compute new digest, find most recent FINALIZED/REVISED event for that path, emit PLAN_REVISED with `{plan_path, old_sha256, new_sha256, reason, human_approver}`, print confirmation.

Errors:
- No plan file → `mage plan revise: error: plan.md not found at <path>`
- No prior finalization → `mage plan revise: error: no PLAN_FINALIZED event; run mage run to create the Plan first`
- `old_sha256` matches `new_sha256` → `mage plan revise: warning: Plan digest unchanged; recording anyway`

**`mage run`** — run the pipeline with halt handling and resume support.

```bash
mage run [--from <stage-name>] [--project-dir <path>]
```

Behavior:
1. Load `PipelineContext` from `FileStatePersistence`. If halted context exists and no `--from`, resume from stage after halt.
2. If `--from <stage>` given, ignore persisted state and start from that stage.
3. Run `PipelineGraph.run(initial_context)`.
4. On `PlanRevisionRequired`, persist halt record, exit cleanly (exit code 0; user runs `mage plan revise` then `mage run`).

**Backward compatibility with Plan 1:**

- `mage verify` (Plan 1, renamed from `h2 verify`).
- `mage run` (new).
- `mage plan show` (new).
- `mage plan revise` (new).

### Host-Project Config Extension

Extend `HostConfig` (Plan 1's `verification/host_overrides.py`):

```python
class HostConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")
    
    # Plan 1 fields
    enabled_checks: list[str] | None = None
    
    # Plan 2 fields
    require_plan_approval: bool = True
    plan_template_path: Path | None = None  # optional override
```

**Override file format:**

```yaml
# <project_dir>/.haileris/config.yaml
require_plan_approval: false
plan_template_path: ./custom-plan-template.md
```

**Default Plan template** lives at `src/haileris_v2/orchestration/plan_template.md` (shipped):

```markdown
---
behavior_ids:
  - <id-1>
  - <id-2>
  - ...
behaviors:
  - id: <id>
    name: <name>
    depends_on: [...]
    notes: <notes>
project_id: <id>
schema_version: 1
---

# Implementation Plan — <feature_name>

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** <feature scope statement from Ascertain>

**Architecture overview:**

<decomposition.yaml content rendered as Markdown summary>

## Behaviors

<one section per behavior, in topological order>

### <id> — <name>

**Description:** <description>

**Depends on:** <depends_on joined>

**Notes:** <notes>

**Cross-behavior links:** <cross_behavior_links joined>
```

### Event Type Extensions

Extend `EventType` enum (Plan 1's `orchestration/events.py`):

```python
class EventType(str, Enum):
    # Plan 1 — stage lifecycle
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    
    # Plan 2 — Decomposition stage
    DECOMPOSITION_STARTED = "decomposition_started"
    DECOMPOSITION_COMPLETED = "decomposition_completed"
    
    # Plan 2 — behavior enumeration sub-step
    BEHAVIORS_ENUMERATED = "behaviors_enumerated"
    
    # Plan 2 — Plan lifecycle
    PLAN_FINALIZED = "plan_finalized"
    PLAN_REVISED = "plan_revised"
    PLAN_DIGEST_MISMATCH = "plan_digest_mismatch"
    
    # Plan 2 — halt/recovery
    HALT_PERSISTED = "halt_persisted"
    
    # Plan 5 placeholder (defined here so events log schema is stable)
    BEHAVIORS_REVISED = "behaviors_revised"
```

### Mapping Model Extension

Extend `BaseBIDEntry` (Plan 1's `artifacts/mapping.py`):

```python
class BaseBIDEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    base_bid: str
    behavior_name: str
    behavior_description: str
    depends_on: list[str] = Field(default_factory=list)  # NEW
    notes: str = ""  # NEW
    scenarios: list[ScenarioEntry] = Field(default_factory=list)
    reversion_log: list[ReversionLogEntry] = Field(default_factory=list)
    post_live_revisions: list[PostLiveRevisionEntry] = Field(default_factory=list)
    cross_behavior_links: list[str] = Field(default_factory=list)
```

## Test Strategy

### Unit tests (~12)

- `test_plan.py` — `PlanArtifact.finalize`/`load`/`revise`. Digest mismatch, idempotent re-finalization, refuse-to-read-unfinalized.
- `test_behavior_enumeration.py` — dependency resolution, cycle detection, BID assignment, duplicate name detection.
- `test_host_overrides.py` extension — `require_plan_approval` field, default value, override loading.
- `test_decomposition_models.py` — `BehaviorSpec`, `ArchitectureSpec`, updated `BaseBIDEntry`, Ascertain output schema.

### Integration tests (~6)

- `test_decomposition_stage.py` — full stage run with Pydantic-AI's `TestModel`. Mock Ascertain output, run Decomposition, verify all three files written, mapping updated, events emitted.
- `test_halt_recovery.py` — Decomposition halts with `PlanRevisionRequired`, halt record persisted, `mage plan revise` records revision, next `mage run` resumes and verifies.
- `test_cli.py` extension — `mage plan show`, `mage plan revise`, `mage run --from` argument parsing and end-to-end behavior via `typer.testing.CliRunner`.

### End-to-end tests (~3)

- `test_e2e_decomposition.py` — full happy path. Mock Ascertain output → run Decomposition → verify decomposition.yaml, behaviors.yaml, plan.md all written with correct BIDs, mapping updated, events log populated.
- Halt-and-resume e2e: simulate Plan revision via direct edit + `mage plan revise`, verify resume succeeds.
- Approval-gate e2e: verify `require_plan_approval=True` triggers deferred-tool pause; `require_plan_approval=False` skips it.

### Pydantic-AI testing approach

Use `pydantic_ai.models.test.Model` (or `TestModel`) for deterministic tests without real LLM calls. Test fixtures provide canned `BehaviorSpec` lists for happy path, cycles for cycle-detection, unresolvable dependencies for dependency-error tests.

### Test count target

~21 new tests in Plan 2. Combined with Plan 1's 72 tests, total ~93 by end of Plan 2. Maintain ≥90% line coverage on new code.

## Cross-Plan Dependencies

### What Plan 2 needs from Plan 1 (already built)

- `MappingArtifact`, `Base85BID`, `next_base_bid()` — for BID assignment in behavior enumeration.
- `FileStatePersistence` — extended in Plan 2 for halt-record persistence.
- `EventsLog`, `EventType`, `Event` — extended with new event types.
- `PipelineContext`, `StageNode`, `PipelineGraph` — extended with halt handling.
- `MechanicalVerifier`, `HostConfig` — extended with `require_plan_approval` and `plan_template_path`.
- `mage`/`h2` CLI scaffold — extended with new subcommands; renamed to `mage`.

### What Plan 2 outputs to downstream plans

- `PlanArtifact` is used by every Plan-loading stage (Inscribe, etc.) in Plans 3+.
- `DecompositionStage` is the second stage in the pipeline; later stages assume its outputs exist.
- Behavior enumeration writes BIDs into mapping; per-scenario Inscribe (Plan 3) reads them.
- Plan-revision gate mechanism is invoked by Settle (Plan 5) but provided here.
- Ascertain output schema is consumed by Decomposition; Ascertain itself is built in a future plan.

## Out of Scope (deferred)

- **Ascertain stage runtime** — only the output schema is defined. Actual Ascertain agent is built in a future plan.
- **Plan-revision gate trigger detection** — Settle/Inspect (Plan 5) decides when to raise `PlanRevisionRequired`. Plan 2 only provides the mechanism.
- **`mage behaviors revise` CLI** — listed in event types but not implemented; Plan 5 territory.
- **Per-scenario lifecycle** (Inscribe, Etch, Realize) — Plans 3 and 4.
- **Three Practices discipline enforcement** (forward-only ordering, recurrence rules) — Plan 6.

## Spec Self-Review

1. **Placeholder scan:** No "TBD"/"TODO"/incomplete sections. All decisions pinned.
2. **Internal consistency:** Section cross-references verified. R1–R10 align with architecture and test sections.
3. **Scope check:** Single plan focus — Decomposition stage + Plan immutability + halt mechanism. Plan 5 triggers Plan-revision gate but the gate itself is here.
4. **Ambiguity check:**
   - "Agent describes, system assigns BIDs" (R8) — explicit that BIDs never appear in LLM context.
   - "Persist-then-exit halt" (R4) — explicit about SystemExit(0) and how resume detects halt via persisted context.
   - "Digest check on every load" (R3, R5/PlanArtifact) — explicit about cost (one SHA256) and rationale.
   - "Approval gate via deferred-tool" (R7) — explicit about edit/restart semantics.

## Implementation Notes

The first task of Plan 2's implementation phase is a housekeeping fix: rename `h2` → `mage` in `pyproject.toml`. After that, the plan proceeds task-by-task per the writing-plans skill.