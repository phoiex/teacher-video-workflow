"""Shared response for authenticated workflow recovery endpoints."""

from fields.base import ResponseModel


class WorkflowRetryResponse(ResponseModel):
    workflow_run_id: str
    reused: bool
