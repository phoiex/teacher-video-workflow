"""Restart a failed course from its saved workflow and inputs.

The browser supplies only a run ID. Published versions and course IDs come from
tenant-scoped execution records. Redis serializes duplicate retry submissions;
the native workflow executor still owns all node execution and human input.
"""

import json
import re
import time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import Conflict, NotFound, ServiceUnavailable

from core.app.entities.app_invoke_entities import InvokeFrom
from extensions.ext_database import db
from extensions.ext_redis import redis_client
from models import Account, App
from models.enums import CreatorUserRole
from models.model import EndUser
from models.workflow import Workflow, WorkflowNodeExecutionModel, WorkflowRun


def retry_inputs(inputs, node_outputs, *, supports_course_resume):
    """Use the saved course when available; otherwise retain the original input files."""
    values = {key: value for key, value in inputs.items() if not key.startswith("sys.")}
    if supports_course_resume:
        candidates = [values.get("resume_course")]
        for output in node_outputs:
            if not isinstance(output, dict):
                continue
            candidates.append(output.get("course_id"))
            try:
                body = json.loads(output.get("body", "{}"))
                if isinstance(body, dict):
                    candidates.append(body.get("course_id"))
            except (ValueError, TypeError):
                pass
        course_id = next((value for value in candidates
                          if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{24}", value)), None)
        if course_id:
            return {"inputs": {"resume_course": course_id}, "files": []}
    return {"inputs": values, "files": inputs.get("sys.files", []) or []}


def validate_retry_source(run, workflow, app_model, user, *, public):
    """Admit the original owner chain before inspecting any recovery mapping."""
    if run is None or run.tenant_id != app_model.tenant_id or run.app_id != app_model.id:
        raise NotFound("Workflow run not found")
    if public and (run.created_by_role != CreatorUserRole.END_USER or run.created_by != user.id):
        raise NotFound("Workflow run not found")
    if workflow is None or workflow.tenant_id != app_model.tenant_id or workflow.app_id != app_model.id:
        raise NotFound("Original workflow version not found")
    if run.status not in ("failed", "stopped"):
        return False
    if workflow.version != run.version or workflow.graph_dict != run.graph_dict:
        raise Conflict("原运行的流程配置已变更。请保留原课程，使用新测试入口运行修改后的流程。")
    return True


def _load_plan(app_model, user, run_id, public):
    from services.app_generate_service import AppGenerateService
    from tasks.app_generate.workflow_execute_task import AppExecutionParams

    with Session(db.engine, expire_on_commit=False) as session:
        run = session.scalar(select(WorkflowRun).where(
            WorkflowRun.id == run_id, WorkflowRun.tenant_id == app_model.tenant_id,
            WorkflowRun.app_id == app_model.id))
        workflow = session.scalar(select(Workflow).where(
            Workflow.id == run.workflow_id, Workflow.tenant_id == app_model.tenant_id,
            Workflow.app_id == app_model.id)) if run else None
        restart = validate_retry_source(run, workflow, app_model, user, public=public)
        if not restart:
            return None
        # Preserve the end-user identity when an editor retries a published run.
        owner_model = EndUser if run.created_by_role == CreatorUserRole.END_USER else Account
        owner = session.get(owner_model, run.created_by)
        if owner is None:
            raise NotFound("Original workflow user not found")
        nodes = workflow.graph_dict.get("nodes", [])
        supports_resume = any(variable.get("variable") == "resume_course"
                              for node in nodes if node.get("data", {}).get("type") == "start"
                              for variable in node["data"].get("variables", []))
        outputs = session.scalars(select(WorkflowNodeExecutionModel).where(
            WorkflowNodeExecutionModel.tenant_id == app_model.tenant_id,
            WorkflowNodeExecutionModel.app_id == app_model.id,
            WorkflowNodeExecutionModel.workflow_run_id == run_id,
            WorkflowNodeExecutionModel.node_id.in_(("create_data", "create")),
        )).all()
        args = retry_inputs(run.inputs_dict, [node.outputs_dict for node in outputs],
                            supports_course_resume=supports_resume)
        invoke_from = InvokeFrom.WEB_APP if isinstance(owner, EndUser) else InvokeFrom.DEBUGGER
        AppGenerateService._ensure_workflow_service_mode_available(workflow=workflow, invoke_from=invoke_from)
        plan = AppExecutionParams.new(app_model=app_model, workflow=workflow, user=owner,
                                      args=args, invoke_from=invoke_from, workflow_run_id=str(uuid4()))
        lookup_url = None
        if (supports_resume and not args["inputs"].get("resume_course")
                and any(node.node_id == "create" for node in outputs)
                and any(node["id"] == "create" and node.get("data", {}).get("type") == "http-request"
                        for node in nodes)):
            tool_url = next((variable.value for variable in workflow.environment_variables
                             if variable.name == "LOCAL_TOOL_URL"), None)
            if tool_url:
                lookup_url = str(tool_url).rstrip("/") + "/stage-status/" + run_id
    # The creation response may have been lost after the course was already saved.
    # Ask the same configured local tool only after closing the database session.
    if lookup_url:
        from core.helper import ssrf_proxy

        response = ssrf_proxy.get(lookup_url, timeout=5)
        response.raise_for_status()
        plan.args = retry_inputs(args["inputs"], [response.json()], supports_course_resume=True)
        if not plan.args["inputs"].get("resume_course"):
            plan.args = args
    return plan.model_dump_json()


def _enqueue(app_model, payload_json):
    from services.app_generate_service import AppGenerateService
    from tasks.app_generate.workflow_execute_task import workflow_retry_execution_task

    def enqueue(_rate_limit, _request_id):
        workflow_retry_execution_task.apply_async(
            args=[payload_json], task_id=json.loads(payload_json)["workflow_run_id"])
    AppGenerateService._run_with_guardrails(app_model=app_model, streaming=False, action=enqueue)


def retry_workflow(app_model: App, user: Account | EndUser, run_id: str, *, public: bool):
    """Create at most one successor for a source run; reconnect to it after a lost response."""
    # This also checks public ownership on repeat clicks, before the Redis lookup.
    plan = _load_plan(app_model, user, run_id, public)
    if plan is None:
        return {"workflow_run_id": run_id, "reused": True}
    key = f"course-workflow-retry:{app_model.tenant_id}:{app_model.id}:{run_id}"
    with redis_client.lock(key + ":lock", timeout=20, blocking_timeout=5):
        previous = redis_client.get(key)
        if previous:
            record = json.loads(previous)
            plan = record["payload"]
        else:
            record = {"payload": plan, "dispatched": False}
            redis_client.set(key, json.dumps(record))
        if not record["dispatched"]:
            _enqueue(app_model, plan)
            record["dispatched"] = True
            redis_client.set(key, json.dumps(record))
    destination_id = json.loads(plan)["workflow_run_id"]
    # The native events endpoint requires a persisted run. Never return an ID the
    # browser cannot yet subscribe to; a repeat request reuses the queued task.
    for _ in range(40):
        with Session(db.engine) as session:
            ready = session.scalar(select(WorkflowRun.id).where(
                WorkflowRun.id == destination_id,
                WorkflowRun.tenant_id == app_model.tenant_id,
                WorkflowRun.app_id == app_model.id))
        if ready:
            return {"workflow_run_id": destination_id, "reused": previous is not None}
        time.sleep(0.1)
    raise ServiceUnavailable("恢复请求已提交，正在等待执行。请稍后点击重试查看进度。")
