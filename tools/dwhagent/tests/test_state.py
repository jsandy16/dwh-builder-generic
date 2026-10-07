"""Stage detection on a fresh pipeline: what the agent will do next depends only on what is on disk."""
from __future__ import annotations

from dwhagent import state as S


def test_fresh_pipeline_waits_for_request_and_data(scratch_repo):
    st = S.detect(scratch_repo, scratch_repo / "pipelines" / "demo")
    assert st.stage == S.SETUP
    assert "request" in st.why and "data/raw" in st.why
    assert st.stage in S.PERSON_STAGES


def test_template_request_does_not_count_as_written(scratch_repo):
    st = S.detect(scratch_repo, scratch_repo / "pipelines" / "demo")
    assert st.facts["request_written"] is False


def test_request_and_data_start_the_draft(scratch_repo, tmp_path):
    import shutil
    repo = tmp_path / "r"
    shutil.copytree(scratch_repo, repo, symlinks=True)
    p = repo / "pipelines" / "demo"
    (p / "requirements" / "request.md").write_text(
        "# Request\n\nThe finance team wants monthly revenue per region from the shop exports, refreshed daily.\n")
    st = S.detect(repo, p)
    assert st.stage == S.SETUP and "data/raw" in st.why and "request" not in st.why
    (p / "data" / "raw" / "orders.csv").write_text("id,amount\n1,10\n")
    st = S.detect(repo, p)
    assert st.stage == S.DRAFT, st
    assert st.facts["raw_files"] == 1
