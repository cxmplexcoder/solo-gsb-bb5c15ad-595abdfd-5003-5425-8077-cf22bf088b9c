"""Tests for the batch annotation rule engine. Run: python -m pytest backend/"""
import pytest

from app.rules import (
    apply_rule, clean_config, match_segments, preview_rule, undo_run,
)

SEG = lambda sid, s, e, sp="受访者", t="改制": {
    "id": sid, "start": s, "end": e, "speaker": sp, "text": t}


def doc(segs=(), anns=()):
    return {"segments": list(segs), "annotations": list(anns)}


def rule(**over):
    base = {
        "name": "改制", "speaker": "", "matchMode": "keyword",
        "pattern": "改制", "minDuration": 0,
        "mergeAdjacent": True, "mergeGap": 2.0,
        "topic": "改制主题", "noteTemplate": "{{rule}} {{matched}}",
    }
    base.update(over)
    return clean_config(base)


SEGMENTS = [
    SEG("s1", 0, 3, t="我进厂改制"),
    SEG("s2", 3, 6, t="后来改制下岗"),
    SEG("s3", 6, 6.5, sp="访谈者", t="嗯"),
    SEG("s4", 20, 24, t="改制改制"),
]


def test_config_validates_regex_and_numbers():
    with pytest.raises(ValueError):
        clean_config({"name": "r", "matchMode": "regex", "pattern": "["})
    with pytest.raises(ValueError):
        clean_config({"name": ""})
    with pytest.raises(ValueError):
        clean_config({"name": "r", "minDuration": -1})
    with pytest.raises(ValueError):
        clean_config({"name": "r", "mergeGap": -1})
    cfg = clean_config({"name": "r", "matchMode": "regex", "pattern": r"\d+"})
    assert cfg["matchMode"] == "regex"


def test_speaker_duration_and_keyword_filters():
    cfg = rule(speaker="受访者", minDuration=1)
    matched = match_segments(cfg, SEGMENTS)
    assert [s["id"] for s in matched] == ["s1", "s2", "s4"]  # s3 too short + speaker
    cfg = rule(speaker="")
    assert [s["id"] for s in match_segments(cfg, SEGMENTS)] == ["s1", "s2", "s4"]


def test_regex_match_mode():
    cfg = rule(matchMode="regex", pattern=r"改[制置]")
    assert len(match_segments(cfg, SEGMENTS)) == 3
    cfg = rule(matchMode="regex", pattern=r"^\d+$")
    assert match_segments(cfg, SEGMENTS) == []


def test_adjacent_merge_and_template():
    cfg = rule(mergeAdjacent=True, mergeGap=5,
               noteTemplate="{{rule}}:{{matched}}:{{speaker}}")
    pv = preview_rule(cfg, "rule-x", doc(SEGMENTS), None)
    assert len(pv["annotations"]) == 2
    first = pv["annotations"][0]
    assert first["start"] == 0 and first["end"] == 6
    assert first["segmentIds"] == ["s1", "s2"]
    assert first["note"] == "改制:2:受访者"
    assert pv["stats"]["create"] == 2


def test_no_merge_emits_one_annotation_per_segment():
    cfg = rule(mergeAdjacent=False)
    out = apply_rule(cfg, "r1", "run1", doc(SEGMENTS), None)
    assert len(out["generated"]) == 3
    assert out["generated"][0]["ruleId"] == "r1"
    assert out["generated"][0]["ruleRunId"] == "run1"


def test_empty_pattern_matches_all_segments():
    cfg = rule(pattern="", minDuration=2)
    matched = match_segments(cfg, SEGMENTS)
    assert [s["id"] for s in matched] == ["s1", "s2", "s4"]


def test_rerun_replaces_only_its_intact_outputs():
    cfg = rule(mergeGap=5)
    out1 = apply_rule(cfg, "r1", "run1", doc(SEGMENTS), None)
    out2 = apply_rule(cfg, "r1", "run2", out1["document"], out1["snapshot"])
    assert out2["stats"]["replace"] == 2 and out2["stats"]["create"] == 0
    ids1 = {a["id"] for a in out1["document"]["annotations"]}
    ids2 = {a["id"] for a in out2["document"]["annotations"]}
    assert ids1.isdisjoint(ids2)
    # undo restores run1 outputs exactly
    undone = undo_run({"id": "run2", "summary": out2["snapshot"]},
                      out2["document"])
    assert undone["removed"] == 2 and undone["restored"] == 2
    assert {a["id"] for a in undone["document"]["annotations"]} == ids1


def test_hand_edited_output_detaches_and_is_not_overwritten():
    cfg = rule(mergeGap=5)
    out1 = apply_rule(cfg, "r1", "run1", doc(SEGMENTS), None)
    edited_id = out1["generated"][0]["id"]
    out1["document"]["annotations"][0]["note"] = "手工改过"
    out2 = apply_rule(cfg, "r1", "run2", out1["document"], out1["snapshot"])
    assert out2["stats"]["keepManual"] == 1
    edited = next(a for a in out2["document"]["annotations"]
                  if a["id"] == edited_id)
    assert edited["note"] == "手工改过" and "ruleId" not in edited
    # a third run must not recreate the detached group either
    out3 = apply_rule(cfg, "r1", "run3", out2["document"], out2["snapshot"])
    assert out3["stats"]["create"] == 0
    assert "手工改过" in [a["note"] for a in out3["document"]["annotations"]]


def test_user_deleted_output_is_not_recreated():
    cfg = rule(mergeAdjacent=False)
    out1 = apply_rule(cfg, "r1", "run1", doc(SEGMENTS), None)
    remaining = out1["document"]["annotations"][1:]  # delete first
    d2 = doc(SEGMENTS, remaining)
    out2 = apply_rule(cfg, "r1", "run2", d2, out1["snapshot"])
    assert out2["stats"]["skipDeleted"] == 1
    assert out2["stats"]["create"] == 0
    assert len(out2["document"]["annotations"]) == 2


def test_manual_annotations_are_never_touched():
    manual = {"id": "m1", "start": 0, "end": 1, "speaker": "X",
              "topic": "手", "note": "手工备注"}
    d = doc(SEGMENTS, [dict(manual)])
    out = apply_rule(rule(), "r1", "run1", d, None)
    kept = next(a for a in out["document"]["annotations"] if a["id"] == "m1")
    assert kept == manual
    assert out["stats"]["skipOverlap"] >= 1  # proposal overlapping manual skipped


def test_undo_first_run_removes_outputs():
    out = apply_rule(rule(mergeGap=5), "r1", "run1", doc(SEGMENTS), None)
    undone = undo_run({"id": "run1", "summary": out["snapshot"]},
                      out["document"])
    assert undone["removed"] == 2 and undone["restored"] == 0
    assert undone["document"]["annotations"] == []


def test_stale_groups_are_removed_when_rule_changes():
    cfg1 = rule(mergeGap=5)
    out1 = apply_rule(cfg1, "r1", "run1", doc(SEGMENTS), None)
    assert len(out1["generated"]) == 2
    cfg2 = rule(mergeGap=5, pattern="不存在的关键词")
    out2 = apply_rule(cfg2, "r1", "run2", out1["document"], out1["snapshot"])
    assert out2["stats"]["removedStale"] == 2
    assert [a for a in out2["document"]["annotations"]
            if a.get("ruleId") == "r1"] == []


def test_merge_to_split_shape_change_removes_old_merged_interval():
    cfg_merged = rule(mergeAdjacent=True, mergeGap=5)
    out1 = apply_rule(cfg_merged, "r1", "run1", doc(SEGMENTS), None)
    assert [a["end"] for a in out1["generated"] if a["start"] == 0] == [6]
    cfg_split = rule(mergeAdjacent=False)
    out2 = apply_rule(cfg_split, "r1", "run2", out1["document"],
                      out1["snapshot"])
    # merged (s1,s2) interval -> two per-segment intervals (2 creates +
    # 1 stale removal); standalone s4 interval is an exact replace
    assert out2["stats"]["create"] == 2
    assert out2["stats"]["replace"] == 1
    assert out2["stats"]["removedStale"] == 1
    ids = [a["id"] for a in out1["generated"]]
    assert not any(a["id"] in ids for a in out2["document"]["annotations"])
    # undo restores the merged interval exactly
    undone = undo_run({"id": "run2", "summary": out2["snapshot"]},
                      out2["document"])
    assert undone["removed"] == 3 and undone["restored"] == 2
    restored = undone["document"]["annotations"]
    assert len(restored) == 2  # merged s1/s2 interval + standalone s4
    assert [a["end"] for a in restored if a["start"] == 0] == [6]


def test_intact_interval_kept_when_overlapping_proposals_are_all_skipped():
    # first run matches only s2 (keyword exclusive to it); before re-running
    # with a broader keyword, a manual annotation covers s1: the new s1
    # proposal overlaps manual work (skipped), while the unchanged s2 group
    # is exactly replaced and never mistaken for a stale removal.
    segs = [
        SEG("s1", 0, 3, t="改制了"),
        SEG("s2", 30, 33, t="后来下岗"),
    ]
    cfg1 = rule(mergeAdjacent=False, pattern="下岗")
    out1 = apply_rule(cfg1, "r1", "run1", doc(segs), None)
    assert len(out1["generated"]) == 1
    manual = {"id": "m1", "start": 0, "end": 30, "speaker": "X",
              "topic": "手工覆盖开头", "note": "手工"}
    d2 = doc(segs, list(out1["generated"]) + [manual])
    cfg2 = rule(mergeAdjacent=False, pattern="")
    out2 = apply_rule(cfg2, "r1", "run2", d2, out1["snapshot"])
    assert out2["stats"]["skipOverlap"] == 1, out2["stats"]
    assert out2["stats"]["replace"] == 1
    assert out2["stats"]["create"] == 0
    assert out2["stats"]["removedStale"] == 0
    assert any(a["id"] == "m1" for a in out2["document"]["annotations"])
