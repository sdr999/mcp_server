"""Admin endpoints for prompt management and A/B variant retrieval."""
from __future__ import annotations

import logging
from typing import List
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..security import admin_denied

log = logging.getLogger("MCP_logger")


async def list_prompts_handler(request):
    if denied := await admin_denied(request):
        return denied
    repo = getattr(request.app.state, "prompt_repository", None)
    if not repo:
        return JSONResponse({"error": "Prompt Repository not initialized"}, status_code=503)
    return JSONResponse({"prompts": repo.list_prompts()})


async def register_prompt_handler(request):
    if denied := await admin_denied(request):
        return denied
    repo = getattr(request.app.state, "prompt_repository", None)
    if not repo:
        return JSONResponse({"error": "Prompt Repository not initialized"}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    name = body.get("name")
    template = body.get("template")
    if not name or not template:
        return JSONResponse({"error": "Fields 'name' and 'template' are required"}, status_code=400)

    version = body.get("version", "v1.0.0")
    description = body.get("description", "")
    variants = body.get("variants")

    entry = repo.register_prompt(name=name, template=template, version=version, description=description, variants=variants)
    return JSONResponse({"status": "registered", "prompt": entry})


async def get_prompt_variant_handler(request):
    if denied := await admin_denied(request):
        return denied
    repo = getattr(request.app.state, "prompt_repository", None)
    ab_manager = getattr(request.app.state, "ab_test_manager", None)
    if not repo or not ab_manager:
        return JSONResponse({"error": "Prompt engine not initialized"}, status_code=503)

    name = request.path_params.get("name", "")
    version = request.query_params.get("version")
    # Sticky A/B allocation is per-tenant; derive it from the resolved principal
    # (request.state.tenant_id is never set, which made selection effectively global).
    principal = getattr(request.state, "principal", None)
    tenant_id = getattr(principal, "org_id", None) or "default"

    prompt_data = repo.get_prompt(name=name, version=version)
    if not prompt_data:
        return JSONResponse({"error": f"Prompt '{name}' not found"}, status_code=404)

    variant_key, variant_template = ab_manager.select_variant(tenant_id, name, prompt_data.get("variants", {}))
    
    # Optional variable hydration
    vars_param = request.query_params.get("vars", "")
    hydrated = variant_template
    if vars_param:
        try:
            import json
            variables = json.loads(vars_param)
            hydrated = repo.hydrate(variant_template, variables)
        except Exception:
            pass

    return JSONResponse(
        {
            "name": name,
            "version": prompt_data["version"],
            "variant_selected": variant_key,
            "template": variant_template,
            "hydrated_text": hydrated,
        }
    )


def prompt_routes() -> List[Route]:
    return [
        Route("/admin/prompts", endpoint=list_prompts_handler, methods=["GET"]),
        Route("/admin/prompts", endpoint=register_prompt_handler, methods=["POST"]),
        Route("/admin/prompts/{name}/variant", endpoint=get_prompt_variant_handler, methods=["GET"]),
    ]
