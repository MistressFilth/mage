"""Tests for Ascertain output schema."""

from __future__ import annotations

from pathlib import Path

import pytest

ASCERTAIN_FULL = """---
feature_id: feat-001
feature_name: User authentication
scope_statement: Users authenticate with email/password; OAuth is out of scope.
in_scope:
  - Email/password login
  - Password reset
out_of_scope:
  - OAuth providers
  - Multi-factor auth
success_criteria:
  - User can log in with valid credentials
  - User sees clear error on invalid credentials
resolved_ambiguities:
  - question: Should we support OAuth?
    decision: No, out of scope for v1.
    rationale: Reduces scope; can add later.
    resolved_by: alice
deferred_questions:
  - "When does password reset expire?"
constraints:
  - "Must work with existing user table."
three_amigos:
  product: "Product perspective: focus on simplest happy path first."
  tester: "Tester perspective: verify error states."
  developer: "Developer perspective: integrate with existing auth middleware."
---

# Ascertain Session

We discussed scope, ambiguities, and constraints. The team agreed on email/password for v1.
"""

ASCERTAIN_MINIMAL = """---
feature_id: feat-002
feature_name: Minimal feature
scope_statement: Just the basics.
---"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "ascertain.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_ascertain_full(tmp_path):
    from mage.artifacts.ascertain import parse_ascertain

    path = _write(tmp_path, ASCERTAIN_FULL)
    out = parse_ascertain(path)
    assert out.feature_id == "feat-001"
    assert out.feature_name == "User authentication"
    assert "Email/password login" in out.in_scope
    assert "OAuth providers" in out.out_of_scope
    assert len(out.success_criteria) == 2
    assert len(out.resolved_ambiguities) == 1
    assert out.resolved_ambiguities[0].question == "Should we support OAuth?"
    assert out.three_amigos.product.startswith("Product perspective")


def test_parse_ascertain_minimal(tmp_path):
    from mage.artifacts.ascertain import parse_ascertain

    path = _write(tmp_path, ASCERTAIN_MINIMAL)
    out = parse_ascertain(path)
    assert out.feature_id == "feat-002"
    assert out.feature_name == "Minimal feature"
    assert out.in_scope == []
    assert out.out_of_scope == []
    assert out.three_amigos.product == ""


def test_parse_ascertain_body_is_preserved(tmp_path):
    from mage.artifacts.ascertain import parse_ascertain

    path = _write(tmp_path, ASCERTAIN_FULL)
    out = parse_ascertain(path)
    assert "We discussed scope" in out.body


def test_parse_ascertain_missing_frontmatter_raises(tmp_path):
    from mage.artifacts.ascertain import AscertainSchemaError, parse_ascertain

    path = tmp_path / "bad.md"
    path.write_text("No frontmatter here.\n", encoding="utf-8")
    with pytest.raises(AscertainSchemaError):
        parse_ascertain(path)
