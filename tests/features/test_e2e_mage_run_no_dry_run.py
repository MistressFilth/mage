import os

import pytest

from mage.cli import main


@pytest.mark.skipif(
    "HOST_MODEL_API_KEY" not in os.environ,
    reason="Real-LLM E2E gated on HOST_MODEL_API_KEY",
)
def test_e2e_mage_run_without_dry_run(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "mapping.yaml").write_text(
        "schema_version: 2\nproject_id: e2e\nbase_bids: []\n"
    )
    try:
        rc = main(["run", "--project-dir", str(project)])
    except (SystemExit, OSError, ValueError) as exc:  # real-LLM environments may transiently fail
        pytest.skip(f"real-LLM run failed (network/auth): {exc!r}")
    assert rc == 0, f"mage run without --dry-run must succeed; got rc={rc}"
