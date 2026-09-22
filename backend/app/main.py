"""FastAPI application: project CRUD, transcript import, three-way merge."""
from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, importer, rules
from .merge import merge_documents
from .schemas import (
    DocumentIn, MergeRequest, ProjectIn, ProjectUpdate,
    RuleApplyRequest, RuleIn, RulePreviewRequest,
)

app = FastAPI(title="访谈音频校注", version="1.0.0")

STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")


@app.on_event("startup")
def _startup() -> None:
    db.init()


def _doc(payload: DocumentIn | None) -> dict | None:
    if payload is None:
        return None
    return {"segments": payload.segments, "annotations": payload.annotations}


def _get_or_404(project_id: str) -> dict:
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


# ---------- projects ----------

@app.get("/api/projects")
def list_projects() -> list[dict]:
    return db.list_projects()


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectIn) -> dict:
    return db.create_project(payload.name.strip())


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    return _get_or_404(project_id)


@app.put("/api/projects/{project_id}")
def save_project(project_id: str, payload: ProjectUpdate) -> dict:
    _get_or_404(project_id)
    name = payload.name.strip() if payload.name else None
    project = db.update_project(project_id, name, _doc(payload.document))
    return project


@app.delete("/api/projects/{project_id}", status_code=204)
def remove_project(project_id: str):
    if not db.delete_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    return JSONResponse(status_code=204, content=None)


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str):
    from urllib.parse import quote

    project = _get_or_404(project_id)
    fname = quote(f"{project['name']}-annotations.json")
    return JSONResponse(
        content=project["document"],
        media_type="application/json",
        headers={
            "Content-Disposition":
                f"attachment; filename=annotations.json; filename*=UTF-8''{fname}"
        },
    )


# ---------- import ----------

def _run_import(content: Any) -> dict:
    try:
        return importer.parse_document(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _parse_uploaded(filename: str, raw: bytes) -> dict:
    text = raw.decode("utf-8-sig")
    if filename.lower().endswith((".txt", ".srt", ".vtt")):
        return _run_import(text)
    try:
        return _run_import(json.loads(text))
    except json.JSONDecodeError:
        return _run_import(text)


@app.post("/api/import")
async def import_transcript(request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        file = form.get("file")
        if file is None or not hasattr(file, "filename"):
            raise HTTPException(status_code=400, detail="表单中缺少 file")
        return _parse_uploaded(file.filename or "upload.txt",
                               await file.read())
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="请上传文件或提供 text/data")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return _run_import(body.decode("utf-8-sig"))
    if isinstance(payload, dict) and (payload.get("text")
                                      or payload.get("data") is not None):
        return _run_import(payload["data"] if payload.get("data") is not None
                           else payload["text"])
    return _run_import(payload)


@app.post("/api/projects/{project_id}/import")
async def import_into_project(project_id: str, request: Request) -> dict:
    project = _get_or_404(project_id)
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        file = form.get("file")
        if file is None or not hasattr(file, "filename"):
            raise HTTPException(status_code=400, detail="表单中缺少 file")
        doc = _parse_uploaded(file.filename or "upload.txt", await file.read())
    else:
        body = await request.body()
        if not body:
            raise HTTPException(status_code=400, detail="请上传文件或提供 text/data")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            doc = _run_import(body.decode("utf-8-sig"))
        else:
            if isinstance(payload, dict) and (payload.get("text")
                                              or payload.get("data") is not None):
                doc = _run_import(payload["data"]
                                  if payload.get("data") is not None
                                  else payload["text"])
            else:
                doc = _run_import(payload)
    # import replaces the transcript but preserves existing annotations
    doc["annotations"] = project["document"].get("annotations", [])
    return db.update_project(project_id, None, doc)


# ---------- three-way merge ----------

@app.post("/api/merge")
def merge(payload: MergeRequest) -> dict:
    base = _doc(payload.base) if payload.base is not None else None
    if base is None:
        if not payload.projectId:
            raise HTTPException(
                status_code=400,
                detail="需要提供 base 文档，或用 projectId 指定基准项目",
            )
        base = _get_or_404(payload.projectId)["document"]

    resolutions = None
    if payload.resolutions:
        resolutions = {k: v.model_dump() for k, v in payload.resolutions.items()}

    result = merge_documents(base, _doc(payload.a), _doc(payload.b), resolutions)

    if payload.saveAsProject:
        created = db.create_project(payload.saveAsProject.strip(),
                                    result["document"])
        result["savedProject"] = {"id": created["id"], "name": created["name"]}
    elif payload.projectId and not result["unresolved"] and not result["errors"]:
        # fully resolved merge writes back to the base project
        project = db.update_project(payload.projectId, None, result["document"])
        result["savedProject"] = {"id": project["id"], "name": project["name"]}
    return result


# ---------- batch annotation rules ----------

def _get_rule_or_404(project_id: str, rule_id: str) -> dict:
    rule = db.get_rule(rule_id)
    if rule is None or rule["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="规则不存在")
    return rule


def _latest_run_snapshot(rule_id: str) -> dict | None:
    """Snapshot of the most recent run of the rule (for re-run semantics)."""
    rule = db.get_rule(rule_id)
    last = rule and rule.get("lastRun")
    if not last:
        return None
    full = db.get_rule_run(last["id"])
    return full["summary"] if full else None


def _request_doc(payload, project: dict) -> dict:
    """Document the request operates on: body document else saved project."""
    return _doc(payload.document) if payload.document is not None \
        else project["document"]


@app.get("/api/projects/{project_id}/rules")
def list_project_rules(project_id: str) -> list[dict]:
    _get_or_404(project_id)
    return db.list_rules(project_id)


@app.post("/api/projects/{project_id}/rules", status_code=201)
def create_rule(project_id: str, payload: RuleIn) -> dict:
    _get_or_404(project_id)
    try:
        config = rules.clean_config(payload.config.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return db.create_rule(project_id, config)


@app.put("/api/projects/{project_id}/rules/{rule_id}")
def update_rule(project_id: str, rule_id: str, payload: RuleIn) -> dict:
    _get_rule_or_404(project_id, rule_id)
    try:
        config = rules.clean_config(payload.config.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return db.update_rule(rule_id, config)


@app.delete("/api/projects/{project_id}/rules/{rule_id}", status_code=204)
def remove_rule(project_id: str, rule_id: str):
    _get_rule_or_404(project_id, rule_id)
    if not db.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="规则不存在")
    return JSONResponse(status_code=204, content=None)


@app.post("/api/projects/{project_id}/rules/{rule_id}/preview")
def preview_rule(project_id: str, rule_id: str,
                 payload: RulePreviewRequest) -> dict:
    rule_row = _get_rule_or_404(project_id, rule_id)
    project = db.get_project(project_id)
    document = _request_doc(payload, project)
    prev_snapshot = _latest_run_snapshot(rule_id)
    result = rules.preview_rule(rule_row["config"], rule_id, document,
                                prev_snapshot)
    result["ruleId"] = rule_id
    return result


@app.post("/api/projects/{project_id}/rules/{rule_id}/apply")
def apply_rule(project_id: str, rule_id: str,
               payload: RuleApplyRequest) -> dict:
    rule_row = _get_rule_or_404(project_id, rule_id)
    project = _get_or_404(project_id)
    document = _request_doc(payload, project)
    prev_snapshot = _latest_run_snapshot(rule_id)
    run_id = db.new_id("run")
    result = rules.apply_rule(rule_row["config"], rule_id, run_id,
                              document, prev_snapshot)
    saved = db.update_project(project_id, None, result["document"])
    run = db.add_rule_run(rule_id, len(result["snapshot"]["entries"]),
                          result["snapshot"], run_id=run_id)
    return {
        "document": saved["document"],
        "project": {"id": saved["id"], "name": saved["name"],
                    "updatedAt": saved["updatedAt"]},
        "run": run,
        "stats": result["stats"],
        "generated": result["generated"],
    }


@app.post("/api/projects/{project_id}/runs/{run_id}/undo")
def undo_rule_run(project_id: str, run_id: str) -> dict:
    project = _get_or_404(project_id)
    run = db.get_rule_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="应用记录不存在")
    rule_row = db.get_rule(run["ruleId"])
    if rule_row is None or rule_row["projectId"] != project_id:
        raise HTTPException(status_code=404, detail="应用记录不存在")
    if run.get("undone"):
        raise HTTPException(status_code=409, detail="该次应用已经撤销过了")
    result = rules.undo_run(run, project["document"])
    saved = db.update_project(project_id, None, result["document"])
    db.mark_run_undone(run_id)
    return {
        "document": saved["document"],
        "project": {"id": saved["id"], "name": saved["name"],
                    "updatedAt": saved["updatedAt"]},
        "removed": result["removed"],
        "restored": result["restored"],
        "detached": result["detached"],
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# ---------- static frontend (served in the Docker image) ----------

if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
