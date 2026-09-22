"""Batch annotation rules.

A rule matches transcript *segments* by speaker, keyword / regular
expression and minimum duration, optionally merges adjacent matches into
one interval, and generates *annotations* with a fixed topic and a note
rendered from a small template.

Generated annotations are ordinary document annotations (start, end,
speaker, topic, note) plus provenance fields ``ruleId`` / ``ruleRunId``.
Re-running a rule only replaces the still-intact annotations its previous
run produced:

* unchanged generated annotation for the same segment group -> replaced;
* hand-edited generated annotation -> detached from the rule (provenance
  stripped) and left untouched, no new interval is generated for it;
* user-deleted generated annotation -> respected (not recreated);
* groups the rule no longer produces -> their intact annotations removed;
* purely manual annotations (no ``ruleId``) are never touched.

Every apply is recorded as a *run* with a content snapshot, so the exact
application can later be undone as long as its outputs were not edited.
"""
from __future__ import annotations

import re
from typing import Any

from .db import new_id

ANN_FIELDS = ("start", "end", "speaker", "topic", "note")
_TEMPLATE_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
DEFAULT_MERGE_GAP = 2.0


# ---------- config ----------

def clean_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate a rule config; raises ValueError on bad input."""
    name = str(raw.get("name", "") or "").strip()
    if not name:
        raise ValueError("规则名称不能为空")
    match_mode = raw.get("matchMode", "keyword")
    if match_mode not in ("keyword", "regex"):
        raise ValueError("matchMode 只能是 keyword 或 regex")
    pattern = str(raw.get("pattern", "") or "")
    if match_mode == "regex" and pattern.strip():
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"正则表达式无效：{exc}") from exc
    min_duration = _num(raw.get("minDuration", 0), "最短持续时间")
    merge_gap = _num(raw.get("mergeGap", DEFAULT_MERGE_GAP), "合并间隔")
    if min_duration < 0:
        raise ValueError("最短持续时间不能为负")
    if merge_gap < 0:
        raise ValueError("合并间隔不能为负")
    return {
        "name": name[:100],
        "speaker": str(raw.get("speaker", "") or "").strip(),
        "matchMode": match_mode,
        "pattern": pattern,
        "minDuration": min_duration,
        "mergeAdjacent": bool(raw.get("mergeAdjacent", True)),
        "mergeGap": merge_gap,
        "topic": str(raw.get("topic", "") or "").strip(),
        "noteTemplate": str(raw.get("noteTemplate", "") or ""),
    }


def _num(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} 必须是数字（秒）")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _r3(value: float) -> float:
    return round(value, 3)


# ---------- matching ----------

def _text_matches(rule: dict, text: str) -> bool:
    pat = rule["pattern"]
    if not pat.strip():
        return True  # speaker / duration only
    if rule["matchMode"] == "regex":
        return re.search(pat, text or "") is not None
    return pat in (text or "")


def match_segments(rule: dict, segments: list[dict]) -> list[dict]:
    """Return the segments satisfying every rule condition, time-sorted."""
    matched = []
    for seg in segments or []:
        start, end = _f(seg.get("start")), _f(seg.get("end"))
        if rule["speaker"] and seg.get("speaker") != rule["speaker"]:
            continue
        if end - start < rule["minDuration"]:
            continue
        if not _text_matches(rule, str(seg.get("text", "") or "")):
            continue
        matched.append(seg)
    matched.sort(key=lambda s: (_f(s.get("start")), str(s.get("id", ""))))
    return matched


def group_segments(rule: dict, matched: list[dict]) -> list[list[dict]]:
    """Split matched segments into merge groups (time order).

    Consecutive matches end up in the same group while the gap between
    them is within the rule's merge gap; otherwise a new group starts.
    """
    if not rule.get("mergeAdjacent", True):
        return [[s] for s in matched]
    groups: list[list[dict]] = []
    current: list[dict] = []
    for seg in matched:
        if current and _f(seg.get("start")) - _f(current[-1].get("end")) \
                > rule["mergeGap"]:
            groups.append(current)
            current = []
        current.append(seg)
    if current:
        groups.append(current)
    return groups


def _group_speaker(rule: dict, group: list[dict]) -> str:
    if rule["speaker"]:
        return rule["speaker"]
    speakers = {str(g.get("speaker", "") or "") for g in group}
    return next(iter(speakers)) if len(speakers) == 1 else ""


def _render(template: str, ctx: dict) -> str:
    return _TEMPLATE_RE.sub(
        lambda m: str(ctx.get(m.group(1), m.group(0))), template or "")


def build_proposals(rule: dict, matched: list[dict]) -> list[dict]:
    """Turn matched segments into proposed annotation intervals."""
    proposals = []
    for group in group_segments(rule, matched):
        start = _r3(min(_f(s.get("start")) for s in group))
        end = _r3(max(_f(s.get("end")) for s in group))
        text = " / ".join(str(s.get("text", "") or "") for s in group)
        speaker = _group_speaker(rule, group)
        ctx = {
            "rule": rule["name"],
            "text": text,
            "speaker": speaker,
            "start": start,
            "end": end,
            "matched": len(group),
        }
        proposals.append({
            "segmentIds": [str(s.get("id", "")) for s in group],
            "start": start,
            "end": end,
            "speaker": speaker,
            "topic": rule["topic"],
            "note": _render(rule["noteTemplate"], ctx),
        })
    return proposals


# ---------- provenance / apply ----------

def _snapshot_entries(snapshot: dict | None) -> dict[str, dict]:
    entries = (snapshot or {}).get("entries") or []
    return {e["annotationId"]: e for e in entries}


def _same_content(ann: dict, snapshot_ann: dict) -> bool:
    return all(ann.get(f) == snapshot_ann.get(f) for f in ANN_FIELDS)


def _overlap(a: dict, b: dict) -> bool:
    return _f(a.get("start")) < _f(b.get("end")) and _f(b.get("start")) < _f(a.get("end"))


def plan_proposals(rule_id: str, document: dict, proposals: list[dict],
                   prev_snapshot: dict | None) -> dict:
    """Decide what every proposal would do against the current document.

    Returns {"actions": [...per proposal...], "stats": {...},
             "overlapsManual": [proposal indexes]}.
    """
    annotations = document.get("annotations", []) or []
    present_ids = {a.get("id") for a in annotations}
    prev = _snapshot_entries(prev_snapshot)

    intact_keys: set[tuple] = set()       # groups still owned, unchanged
    edited_keys: set[tuple] = set()       # groups whose output was hand-edited
    manual_groups: set[tuple] = set()     # detached outputs still in document
    intact_anns: list[dict] = []          # still owned by this rule
    manual_anns: list[dict] = []          # anything the rule must not overwrite

    for ann in annotations:
        if ann.get("ruleId") != rule_id:
            manual_anns.append(ann)
            # detached after a hand edit: id remembered from a previous run
            entry = prev.get(ann.get("id"))
            if entry is not None:
                manual_groups.add(tuple(entry["segmentIds"]))
            continue
        entry = prev.get(ann.get("id"))
        if entry is not None and _same_content(ann, entry.get("annotation", {})):
            intact_keys.add(tuple(entry["segmentIds"]))
            intact_anns.append(ann)
        else:
            # edited by hand (or unknown provenance) -> becomes manual
            if entry is not None:
                edited_keys.add(tuple(entry["segmentIds"]))
            manual_anns.append(ann)

    deleted_keys = {
        tuple(e["segmentIds"])
        for e in prev.values() if e["annotationId"] not in present_ids
    }

    actions, stats = [], {
        "matched": 0, "proposed": len(proposals),
        "create": 0, "replace": 0, "keepManual": 0,
        "skipDeleted": 0, "skipOverlap": 0, "removedStale": 0,
    }
    overlaps_manual: list[int] = []
    executing: list[dict] = []  # proposals that will be written
    skipped_keys: set[tuple] = set()  # groups skipped for manual protection
    for i, p in enumerate(proposals):
        key = tuple(p["segmentIds"])
        overlaps = [m for m in manual_anns if _overlap(p, m)]
        if key in deleted_keys:
            actions.append({"action": "skipDeleted"})
            stats["skipDeleted"] += 1
        elif key in edited_keys or key in manual_groups:
            actions.append({"action": "keepManual"})
            stats["keepManual"] += 1
            skipped_keys.add(key)
        elif key in intact_keys:
            # exact re-generation of an existing group: replaces only the
            # rule's own output for that group, regardless of other ranges
            actions.append({"action": "replace"})
            stats["replace"] += 1
            executing.append(p)
        elif overlaps:
            # a new interval would overlap a hand-written / detached
            # annotation -> skip so manual work is never overwritten
            actions.append({"action": "skipOverlap"})
            stats["skipOverlap"] += 1
            skipped_keys.add(key)
        else:
            actions.append({"action": "create"})
            stats["create"] += 1
            executing.append(p)
        if overlaps:
            overlaps_manual.append(i)

    # Decide the fate of every still-owned intact annotation:
    # * exact same segment group as an executing replace proposal -> updated;
    # * overlapped by an executing create proposal (output shape changed,
    #   e.g. merged <-> split) or not covered by any proposal anymore
    #   -> removed as stale;
    # * covered only by proposals skipped for manual protection -> kept.
    executing_keys = {
        tuple(p["segmentIds"])
        for p, a in zip(proposals, actions) if a["action"] in ("create", "replace")
    }
    retained_intact_ids: set = set()
    stale_intact_ids: set = set()
    for ann in intact_anns:
        ann_key = next(
            (tuple(e["segmentIds"]) for e in prev.values()
             if e["annotationId"] == ann.get("id")),
            None)
        if ann_key in executing_keys:
            continue  # counted as a per-proposal "replace"
        if ann_key in skipped_keys:
            retained_intact_ids.add(ann.get("id"))
            continue
        if any(_overlap(p, ann) for p in executing):
            stale_intact_ids.add(ann.get("id"))  # shape change
            stats["removedStale"] += 1
        elif any(_overlap(p, ann) for p in proposals):
            retained_intact_ids.add(ann.get("id"))  # protected overlap
        else:
            stale_intact_ids.add(ann.get("id"))  # no longer produced
            stats["removedStale"] += 1
    return {"actions": actions, "stats": stats,
            "overlapsManual": overlaps_manual,
            "skippedKeys": skipped_keys,
            "retainedIntactIds": retained_intact_ids,
            "staleIntactIds": stale_intact_ids}


def preview_rule(rule: dict, rule_id: str, document: dict,
                 prev_snapshot: dict | None = None) -> dict:
    matched = match_segments(rule, document.get("segments", []))
    proposals = build_proposals(rule, matched)
    plan = plan_proposals(rule_id, document, proposals, prev_snapshot)
    return {
        "matchedSegments": [_seg_view(s) for s in matched],
        "annotations": proposals,
        "actions": plan["actions"],
        "overlapsManual": plan["overlapsManual"],
        "stats": {**plan["stats"], "matched": len(matched)},
    }


def _seg_view(seg: dict) -> dict:
    return {
        "id": str(seg.get("id", "")),
        "start": _r3(_f(seg.get("start"))),
        "end": _r3(_f(seg.get("end"))),
        "speaker": str(seg.get("speaker", "") or ""),
        "text": str(seg.get("text", "") or ""),
    }


def apply_rule(rule: dict, rule_id: str, run_id: str, document: dict,
               prev_snapshot: dict | None = None) -> dict:
    """Apply a rule and return (new document, run snapshot, result meta)."""
    matched = match_segments(rule, document.get("segments", []))
    proposals = build_proposals(rule, matched)
    plan = plan_proposals(rule_id, document, proposals, prev_snapshot)

    annotations = document.get("annotations", []) or []
    prev = _snapshot_entries(prev_snapshot)
    keep_intact_ids = plan["retainedIntactIds"]
    stale_ids = plan["staleIntactIds"]
    executing_keys = {
        tuple(p["segmentIds"])
        for p, a in zip(proposals, plan["actions"])
        if a["action"] in ("create", "replace")
    }
    kept: list[dict] = []
    replaced_entries: list[dict] = []
    for ann in annotations:
        if ann.get("ruleId") != rule_id:
            kept.append(ann)
            continue
        entry = prev.get(ann.get("id"))
        intact = entry is not None and _same_content(
            ann, entry.get("annotation", {}))
        if not intact:
            # hand-edited generated annotation: detach provenance, keep
            kept.append({k: v for k, v in ann.items()
                         if k not in ("ruleId", "ruleRunId")})
            continue
        key = tuple(entry["segmentIds"])
        if ann.get("id") in keep_intact_ids:
            kept.append(dict(ann))  # still rule-owned, untouched this run
        elif key in executing_keys or ann.get("id") in stale_ids:
            # removed by this run (replaced, reshaped, or gone stale);
            # undo of THIS run restores exactly these annotations
            replaced_entries.append({
                "annotationId": ann.get("id"),
                "segmentIds": list(key),
                "annotation": dict(ann),
            })
        else:  # pragma: no cover - plan classifies every intact annotation
            kept.append(dict(ann))

    generated, entries = [], []
    for p, action in zip(proposals, plan["actions"]):
        if action["action"] in ("skipDeleted", "keepManual", "skipOverlap"):
            continue
        ann_id = new_id("ann")
        ann = {
            "id": ann_id,
            "start": p["start"],
            "end": p["end"],
            "speaker": p["speaker"],
            "topic": p["topic"],
            "note": p["note"],
            "ruleId": rule_id,
            "ruleRunId": run_id,
        }
        generated.append(ann)
        entries.append({
            "annotationId": ann_id,
            "segmentIds": list(p["segmentIds"]),
            "annotation": dict(ann),
        })

    new_doc = {
        "segments": document.get("segments", []) or [],
        "annotations": sorted(kept + generated,
                              key=lambda a: (_f(a.get("start")), str(a.get("id")))),
    }
    snapshot = {"ruleName": rule["name"], "entries": entries,
                "replaced": replaced_entries}
    meta = {
        "generated": generated,
        "snapshot": snapshot,
        "stats": {**plan["stats"], "matched": len(matched)},
    }
    return {"document": new_doc, **meta}


def undo_run(run: dict, document: dict) -> dict:
    """Undo a rule application while keeping later hand edits.

    * intact outputs of the run are removed;
    * outputs of an earlier run that this run replaced are restored
      (unless they are still present, e.g. re-attached by a later run);
    * outputs edited by hand are detached from the rule and retained.

    Returns {"document": ..., "removed": n, "restored": n, "detached": n}.
    """
    snapshot = run.get("summary") or {}
    by_id = _snapshot_entries(snapshot)
    run_id = run["id"]
    removed = detached = 0
    kept = []
    for ann in document.get("annotations", []) or []:
        entry = by_id.get(ann.get("id"))
        if entry is None:
            kept.append(ann)
            continue
        if ann.get("ruleRunId") == run_id and _same_content(
                ann, entry.get("annotation", {})):
            removed += 1
            continue
        # edited after the run: strip provenance and keep as manual
        if ann.get("ruleRunId") == run_id:
            ann = {k: v for k, v in ann.items()
                   if k not in ("ruleId", "ruleRunId")}
            detached += 1
        kept.append(ann)

    existing = {a.get("id") for a in kept}
    restored = 0
    for entry in snapshot.get("replaced", []):
        old = entry.get("annotation") or {}
        old_id = old.get("id")
        if not old_id or old_id in existing:
            continue  # a later run still owns it
        kept.append(dict(old))
        existing.add(old_id)
        restored += 1

    kept.sort(key=lambda a: (_f(a.get("start")), str(a.get("id"))))
    new_doc = {
        "segments": document.get("segments", []) or [],
        "annotations": kept,
    }
    return {"document": new_doc, "removed": removed,
            "restored": restored, "detached": detached}
