"""Execution policy for the local microcourse workflow."""
from collections.abc import Mapping
from typing import Any


def is_teacher_production_workflow(graph_config: Mapping[str, Any]) -> bool:
    nodes = {node.get("id"): node.get("data", {}) for node in graph_config.get("nodes", [])}
    routes = {
        "create": "/api/new",
        "storyboard_show": "/api/storyboard/show",
        "production_start": "/api/production/start",
        "result": "/api/result",
    }
    return all(
        nodes.get(node_id, {}).get("type") == "http-request"
        and nodes[node_id].get("method", "").lower() == "post"
        and str(nodes[node_id].get("url", "")).split("?", 1)[0].endswith(route)
        for node_id, route in routes.items()
    )
