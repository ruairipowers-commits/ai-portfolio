"""Content checks (OBS-02 grounding, EVAL-02 thresholds), builds, publishing and versions."""
import pytest

from crash_course import builder, catalog, checks, evals
from crash_course.config import LEVELS


def test_every_tech_page_has_a_familiar_level():
    assert set(catalog.bundled()) == {p.parent.name for p in (catalog.sources_dir().parents[1] / "courses").glob("*/familiar.yaml")}
    assert len(catalog.bundled()) >= 38


def test_every_bundled_level_passes_every_check(s):
    courses = catalog.bundled()
    failing = []
    for slug, c in courses.items():
        lv = catalog.load_level(slug, "familiar", include_drafts=True)
        rep = checks.check_level(lv, c, s)
        assert rep.stats["minutes"] <= 15
        if not rep.ok:
            failing.append((slug, rep.problems))
    assert not failing


@pytest.mark.parametrize("how", ["ungrounded_evidence", "duplicate_option", "pad_reading", "drop_interview",
                                 "http_link", "small_bank", "all_above"])
def test_broken_levels_are_caught(s, how):
    c = catalog.bundled()["streamlit"]
    lv = catalog.load_level("streamlit", "familiar", include_drafts=True)
    assert not checks.check_level(evals._mutate(lv, how), c, s).ok


def test_bundled_levels_are_drafts_until_published(conn, s):
    assert catalog.load_level("dbt", "familiar") is None
    assert catalog.has_pending_draft("dbt", "familiar")
    ok, _ = builder.publish(conn, s, "dbt", "familiar", "Owner")
    lv = catalog.load_level("dbt", "familiar")
    assert ok and lv.status == "published" and lv.provenance.approved_by == "Owner"
    assert not catalog.has_pending_draft("dbt", "familiar")


@pytest.mark.parametrize("level", LEVELS[1:])
def test_mock_build_is_held_for_the_owner(conn, s, level):
    lv, rep, err = builder.build(conn, s, "streamlit", level)
    assert not err and rep.ok and lv.status == "draft" and lv.provenance.prompt_hash
    assert catalog.load_level("streamlit", level) is None                   # not visible to learners
    ok, _ = builder.publish(conn, s, "streamlit", level, "Owner")
    assert ok and catalog.load_level("streamlit", level).version == lv.version


def test_a_newer_draft_never_hides_the_published_version(conn, s, published):
    v1 = catalog.load_level("streamlit", "familiar")
    lv, rep, _ = builder.build(conn, s, "streamlit", "familiar")             # a rewrite, v2 draft
    assert lv.version == v1.version + 1
    assert catalog.load_level("streamlit", "familiar").version == v1.version  # learners still get v1
    assert catalog.has_pending_draft("streamlit", "familiar")


def test_failing_draft_cannot_be_published(conn, s, published):
    lv = catalog.load_level("streamlit", "familiar")
    broken = evals._mutate(lv, "ungrounded_evidence").model_copy(update={"version": lv.version + 1, "status": "draft"})
    catalog.save_level(broken)
    ok, problems = builder.publish(conn, s, "streamlit", "familiar", "Owner")
    assert not ok and any("evidence" in p for p in problems)
