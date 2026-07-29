"""Three Practices discipline enforcement.

Package contents:
- policy: pure functions for the six Approved Gate Scope rules + revision +
  supersession + cosmetic guard.
- stage: DisciplineStage (Pydantic-Graph node) that wires policy into the
  event stream.
"""

from __future__ import annotations
