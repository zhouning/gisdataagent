"""
MCP Tool Registry — Defines and registers GIS tools for the MCP Server.

Wraps existing GIS tool functions with MCP-safe error handling and
registers them with a FastMCP server instance.
"""

import functools
import inspect
import json
from typing import Callable, List, Dict, Any

from mcp.types import ToolAnnotations

# ---------------------------------------------------------------------------
# Wrapper factory
# ---------------------------------------------------------------------------


def _wrap_tool(fn: Callable) -> Callable:
    """Create MCP-safe wrapper: dict→JSON string, exceptions→error JSON.

    Uses functools.wraps to preserve __name__ and __doc__.
    Explicitly builds __signature__ with original input params but ``str``
    return type, since the wrapper always serializes results to strings.
    This avoids Pydantic errors from annotations like ``dict[str, any]``
    (lowercase ``any`` = built-in function).
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> str:
        try:
            from .governed_external_access import GovernedExternalAccessService
            from .governed_query_security import (
                resolve_governed_query_security_ports,
            )
            from .user_context import (
                current_tenant_id,
                current_user_id,
                current_user_role,
            )

            tenant_id = current_tenant_id.get().strip()
            role = current_user_role.get().strip() or "anonymous"
            subject_id = current_user_id.get().strip() or "mcp-agent"
            security_ports = resolve_governed_query_security_ports(tenant_id)
            result = GovernedExternalAccessService().execute(
                tenant_id=tenant_id,
                actor_subject=f"agent:{subject_id}",
                roles=(role,),
                channel="mcp",
                adapter_id="gda.mcp.local-tool.v1",
                access_mode="invoke",
                resource_refs=(f"mcp:local/tools/{fn.__name__}",),
                request_payload={"args": args, "kwargs": kwargs},
                action="mcp.tool.invoke",
                operation=lambda: fn(*args, **kwargs),
                security_reader=security_ports[0] if security_ports else None,
            )
            if isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False, default=str)
            return str(result)
        except Exception as e:
            return json.dumps(
                {"status": "error", "message": str(e)},
                ensure_ascii=False,
            )

    # Build a clean signature: keep original input params, force return=str.
    # This prevents inspect.signature() from following __wrapped__ back to
    # the original function (which may have problematic return annotations).
    try:
        orig_sig = inspect.signature(fn)
        wrapper.__signature__ = orig_sig.replace(return_annotation=str)
    except (ValueError, TypeError):
        pass

    # Also update __annotations__ for any code that reads it directly
    ann = {}
    for name, param in inspect.signature(fn).parameters.items():
        if param.annotation is not inspect.Parameter.empty:
            ann[name] = param.annotation
    ann["return"] = str
    wrapper.__annotations__ = ann

    return wrapper


# ---------------------------------------------------------------------------
# Lazy imports — avoid importing heavy GIS libraries at registry definition
# ---------------------------------------------------------------------------

# --- High-level wrapper functions (v13.1) ---


def _mcp_list_skills() -> str:
    """列出所有可用的内置 ADK 技能（Skills），包括名称、描述、领域和触发关键词。

    Returns:
        JSON格式的技能列表。
    """
    from .capabilities import list_builtin_skills

    skills = list_builtin_skills()
    return json.dumps({"skills": skills, "count": len(skills)}, ensure_ascii=False)


def _mcp_list_toolsets() -> str:
    """列出所有可用的工具集（Toolsets），每个工具集包含多个专业 GIS 分析工具。

    Returns:
        JSON格式的工具集列表。
    """
    from .capabilities import list_toolsets

    toolsets = list_toolsets()
    return json.dumps({"toolsets": toolsets, "count": len(toolsets)}, ensure_ascii=False)


def _mcp_list_virtual_sources() -> str:
    """列出当前用户可访问的虚拟数据源（WFS/STAC/OGC API/自定义API），包括共享源。

    Returns:
        JSON格式的虚拟数据源列表。
    """
    from .virtual_sources import list_virtual_sources
    from .user_context import current_user_id

    username = current_user_id.get("mcp_user")
    sources = list_virtual_sources(username, include_shared=True)
    return json.dumps({"sources": sources, "count": len(sources)}, ensure_ascii=False)


def _mcp_run_pipeline(prompt: str, pipeline_type: str = "general") -> str:
    """执行完整的 GIS 分析管线。支持通用分析、治理报告、优化布局三种管线。

    Args:
        prompt: 用户分析需求描述（自然语言，如"分析北京市土地利用变化趋势"）。
        pipeline_type: 管线类型（general=通用分析, governance=治理报告, optimization=DRL优化）。

    Returns:
        JSON格式的分析结果，包含报告文本、生成文件、工具执行日志、Token消耗等。
    """
    import asyncio

    try:
        from .pipeline_runner import run_pipeline_headless
        from .user_context import current_user_id, current_session_id
        from .agent import general_pipeline, governance_pipeline, data_pipeline
        from google.adk.sessions import InMemorySessionService

        user_id = current_user_id.get("mcp_user")
        session_id = current_session_id.get(f"mcp_{user_id}")

        agents = {
            "general": general_pipeline,
            "governance": governance_pipeline,
            "optimization": data_pipeline,
        }
        agent = agents.get(pipeline_type, general_pipeline)
        session_service = InMemorySessionService()

        result = asyncio.run(
            run_pipeline_headless(
                agent=agent,
                session_service=session_service,
                user_id=user_id,
                session_id=session_id,
                prompt=prompt,
                pipeline_type=pipeline_type,
                intent=pipeline_type.upper(),
            )
        )

        return json.dumps(
            {
                "status": "ok",
                "report": result.report_text[:5000],
                "files": result.generated_files,
                "pipeline_type": result.pipeline_type,
                "duration_seconds": round(result.duration_seconds, 1),
                "input_tokens": result.total_input_tokens,
                "output_tokens": result.total_output_tokens,
                "error": result.error,
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def _mcp_execute_governed_query(
    request_id: str,
    question: str,
    purpose: str,
    channel: str = "auto",
    purpose_code: str | None = None,
    resource_version_refs: list[dict[str, Any]] | None = None,
    budget: dict[str, Any] | None = None,
    ontology_key: str = "natural-resource-one-map",
    ontology_plan: dict[str, Any] | None = None,
    metric_request: dict[str, Any] | None = None,
    metric_execution_mode: str = "plan_only",
    nl2sql_request: dict[str, Any] | None = None,
    gis_request: dict[str, Any] | None = None,
    rag_request: dict[str, Any] | None = None,
    allow_non_equivalent_fallback: bool = False,
) -> str:
    """Execute the canonical tenant-bound semantic query contract."""
    from .governed_query import GovernedQueryRequest, execute_governed_query
    from .platform_contracts import SubjectContext, SubjectType
    from .user_context import current_tenant_id, current_user_id, current_user_role

    tenant_id = current_tenant_id.get().strip()
    if not tenant_id:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for governed queries",
            },
            ensure_ascii=False,
        )
    payload: dict[str, Any] = {
        "request_id": request_id,
        "question": question,
        "purpose": purpose,
        "channel": channel,
        "ontology_key": ontology_key,
        "metric_execution_mode": metric_execution_mode,
        "allow_non_equivalent_fallback": allow_non_equivalent_fallback,
    }
    if purpose_code is not None:
        payload["purpose_code"] = purpose_code
    if resource_version_refs is not None:
        payload["resource_version_refs"] = resource_version_refs
    if budget is not None:
        payload["budget"] = budget
    if ontology_plan is not None:
        payload["ontology_plan"] = ontology_plan
    if metric_request is not None:
        payload["metric_request"] = metric_request
    if nl2sql_request is not None:
        payload["nl2sql_request"] = nl2sql_request
    if gis_request is not None:
        payload["gis_request"] = gis_request
    if rag_request is not None:
        payload["rag_request"] = rag_request
    request = GovernedQueryRequest.model_validate(payload)
    role = current_user_role.get().strip()
    subject = SubjectContext(
        tenant_id=tenant_id,
        subject_id=current_user_id.get().strip() or "mcp-agent",
        subject_type=SubjectType.AGENT,
        roles=(role,) if role else (),
        purpose=request.purpose,
        trace_id=request.request_id,
    )
    return json.dumps(
        execute_governed_query(request, subject).model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
    )


def _mcp_ingest_entity_authority_batch(
    batch_type: str,
    tenant_id: str,
    idempotency_key: str,
    items: list[dict[str, Any]],
    batch_size: int = 250,
) -> str:
    """Ingest one governed entity-authority batch through the canonical contract."""
    from pydantic import ValidationError

    from .entity_authority_batch import (
        EntityAuthorityBatchRequest,
        execute_entity_authority_batch,
    )
    from .entity_link_authority import EntityLinkAuthorityError
    from .temporal_entity_authority import TemporalEntityAuthorityError
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for entity authority ingestion",
            },
            ensure_ascii=False,
        )
    role = current_user_role.get().strip()
    if role not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    if tenant_id != context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_mismatch",
                "message": "Request tenant_id must match the MCP tenant",
            },
            ensure_ascii=False,
        )
    try:
        request = EntityAuthorityBatchRequest.model_validate(
            {
                "batch_type": batch_type,
                "tenant_id": tenant_id,
                "idempotency_key": idempotency_key,
                "batch_size": batch_size,
                "items": items,
            }
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    actor_ref = f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
    actor_field = "created_by" if request.batch_type == "link_types" else "recorded_by"
    if any(getattr(item, actor_field) != actor_ref for item in request.items):
        return json.dumps(
            {
                "status": "error",
                "code": "actor_mismatch",
                "message": f"{actor_field} must match the MCP agent identity",
            },
            ensure_ascii=False,
        )
    try:
        result = execute_entity_authority_batch(request)
    except (EntityLinkAuthorityError, TemporalEntityAuthorityError) as exc:
        return json.dumps(
            {
                "status": "error",
                "code": exc.code,
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_reconcile_entity_data_package(
    tenant_id: str,
    previous_baseline: dict[str, Any],
    desired_baseline: dict[str, Any],
    effective_at: str,
    evaluated_at: str,
    idempotency_key: str,
    recorded_by: str,
    batch_size: int = 250,
    verify_replay: bool = True,
) -> str:
    """Reconcile a sealed Chongqing package through the canonical authority."""
    from pydantic import ValidationError

    from .chongqing_data_package_reconciliation import (
        ChongqingDataPackageReconciliationError,
    )
    from .chongqing_data_package_reconciliation_service import (
        ChongqingDataPackageReconciliationRequest,
        ChongqingDataPackageReconciliationServiceError,
        execute_chongqing_data_package_reconciliation,
    )
    from .entity_link_authority import EntityLinkAuthorityError
    from .temporal_entity_authority import TemporalEntityAuthorityError
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for data-package reconciliation",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    if tenant_id != context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_mismatch",
                "message": "Request tenant_id must match the MCP tenant",
            },
            ensure_ascii=False,
        )
    actor_ref = f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
    if recorded_by != actor_ref:
        return json.dumps(
            {
                "status": "error",
                "code": "actor_mismatch",
                "message": "recorded_by must match the MCP agent identity",
            },
            ensure_ascii=False,
        )
    try:
        request = ChongqingDataPackageReconciliationRequest.model_validate(
            {
                "tenant_id": tenant_id,
                "previous_baseline": previous_baseline,
                "desired_baseline": desired_baseline,
                "effective_at": effective_at,
                "evaluated_at": evaluated_at,
                "batch_size": batch_size,
                "verify_replay": verify_replay,
                "idempotency_key": idempotency_key,
                "recorded_by": recorded_by,
            }
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    try:
        result = execute_chongqing_data_package_reconciliation(request)
    except ChongqingDataPackageReconciliationServiceError as exc:
        return json.dumps(
            {"status": "error", "code": exc.code, "message": str(exc)},
            ensure_ascii=False,
        )
    except ChongqingDataPackageReconciliationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "chongqing_data_package_reconciliation_conflict",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except (EntityLinkAuthorityError, TemporalEntityAuthorityError) as exc:
        return json.dumps(
            {"status": "error", "code": exc.code, "message": str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_execute_postgis_projection_repair(
    plan: dict[str, Any],
    checkpointed_by: str,
    rows: list[dict[str, Any]] | None = None,
) -> str:
    """Execute a sealed PostGIS repair plan through the canonical service."""
    from pydantic import ValidationError

    from .postgis_projection_service import (
        PostGISProjectionRepairRequest,
        PostGISProjectionServiceError,
        execute_postgis_projection_repair,
    )
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for PostGIS projection repair",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    actor_ref = f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
    if checkpointed_by != actor_ref:
        return json.dumps(
            {
                "status": "error",
                "code": "checkpoint_actor_mismatch",
                "message": "checkpointed_by must match the MCP subject",
            },
            ensure_ascii=False,
        )
    try:
        request = PostGISProjectionRepairRequest.model_validate(
            {
                "plan": plan,
                "rows": rows or [],
                "checkpointed_by": checkpointed_by,
            }
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    if request.plan.tenant_id != context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_mismatch",
                "message": "Repair plan tenant_id must match the MCP tenant",
            },
            ensure_ascii=False,
        )
    try:
        result = execute_postgis_projection_repair(request)
    except PostGISProjectionServiceError as exc:
        return json.dumps(
            {"status": "error", "code": exc.code, "message": str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_generate_federated_projection_compensation_proposal(
    plans: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> str:
    """Generate a read-only compensation proposal from sealed recovery evidence.

    The MCP tenant and role are mandatory.  The tool only builds a deterministic
    proposal; it never persists, selects, approves, or executes a mutation.
    """

    from pydantic import ValidationError

    from .cross_store_projection_compensation_proposal import (
        FederatedProjectionCompensationProposalError,
        FederatedProjectionCompensationProposalRequest,
        build_federated_projection_compensation_proposal,
    )
    from .user_context import current_tenant_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for compensation proposal generation",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    try:
        request = FederatedProjectionCompensationProposalRequest.model_validate(
            {"plans": plans, "snapshot": snapshot}
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    if request.snapshot.tenant_id != context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_mismatch",
                "message": "Recovery snapshot tenant_id must match the MCP tenant",
            },
            ensure_ascii=False,
        )
    try:
        proposal = build_federated_projection_compensation_proposal(
            request.plans,
            request.snapshot,
        )
    except FederatedProjectionCompensationProposalError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "compensation_proposal_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    return json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False)


def _mcp_get_federated_projection_compensation_proposal(run_id: str) -> str:
    """Read persisted proposal current/history for one federated recovery run.

    The tenant and platform role come only from MCP context.  This query never
    records, selects, approves, or executes a compensation candidate.

    Args:
        run_id: Exact non-empty federated recovery run identifier recorded by
            the proposal authority, for example ``cq-federated-run``. Tenant
            identity must not be embedded in or supplied alongside this value.
    """

    from pydantic import ValidationError

    from .cross_store_projection_compensation_proposal import (
        FederatedProjectionCompensationProposalReadRequest,
    )
    from .cross_store_projection_compensation_proposal_authority import (
        FederatedProjectionCompensationProposalAuthorityError,
        FederatedProjectionCompensationProposalConfigurationError,
        FederatedProjectionCompensationProposalForbiddenError,
        FederatedProjectionCompensationProposalValidationError,
        PostgresFederatedProjectionCompensationProposalStore,
    )
    from .user_context import current_tenant_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for compensation proposal lookup",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    try:
        query = FederatedProjectionCompensationProposalReadRequest(run_id=run_id)
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    try:
        result = PostgresFederatedProjectionCompensationProposalStore(
            context_tenant
        ).lookup(query.run_id)
    except FederatedProjectionCompensationProposalConfigurationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "compensation_proposal_authority_unavailable",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except FederatedProjectionCompensationProposalForbiddenError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "compensation_proposal_authority_forbidden",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except FederatedProjectionCompensationProposalValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "compensation_proposal_lookup_invalid",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except FederatedProjectionCompensationProposalAuthorityError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "compensation_proposal_authority_error",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    if result is None:
        return json.dumps(
            {
                "status": "error",
                "code": "compensation_proposal_not_found",
                "message": (
                    "No persisted compensation proposal exists for this federated run"
                ),
            },
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_get_federated_projection_compensation_rules(
    rule_id: str | None = None,
) -> str:
    """Read tenant-scoped current/history customer rule authority evidence."""

    from pydantic import ValidationError

    from .cross_store_projection_compensation_rule_authority import (
        CustomerCompensationRuleAuthorityConfigurationError,
        CustomerCompensationRuleAuthorityError,
        CustomerCompensationRuleAuthorityForbiddenError,
        CustomerCompensationRuleAuthorityValidationError,
        PostgresCustomerCompensationRuleAuthorityStore,
    )
    from .cross_store_projection_compensation_rule_contract import (
        CustomerCompensationRuleAuthorityReadRequest,
    )
    from .user_context import current_tenant_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for compensation rule lookup",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    try:
        query = CustomerCompensationRuleAuthorityReadRequest(rule_id=rule_id)
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    try:
        result = PostgresCustomerCompensationRuleAuthorityStore(
            context_tenant
        ).lookup(query.rule_id)
    except CustomerCompensationRuleAuthorityConfigurationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_compensation_rule_authority_unavailable",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except CustomerCompensationRuleAuthorityForbiddenError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_compensation_rule_authority_forbidden",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except CustomerCompensationRuleAuthorityValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_compensation_rule_lookup_invalid",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except CustomerCompensationRuleAuthorityError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_compensation_rule_authority_error",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    if query.rule_id is not None and result.rule_count == 0:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_compensation_rule_not_found",
                "message": (
                    "No persisted customer compensation rule exists for this rule_id"
                ),
            },
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_assess_federated_projection_compensation_rules(
    proposal: dict[str, Any],
    rules: list[dict[str, Any]],
) -> str:
    """Assess submitted customer rule contracts without selecting an action.

    Tenant and role come only from MCP context. The tool does not persist a
    rule, create customer approval, call a Provider, or execute any
    compensation candidate. Cryptographic verification is performed by the
    strict rule contract before this tool is reached; customer-key trust is
    resolved only from deployment configuration inside this function.
    """

    from pydantic import ValidationError

    from .cross_store_projection_compensation_rule_contract import (
        CustomerCompensationRuleError,
        FederatedProjectionCompensationRuleAssessmentRequest,
        assess_federated_projection_compensation_rules,
    )
    from .cross_store_projection_compensation_trust import (
        CustomerCompensationApprovalTrustConfigurationError,
        load_customer_compensation_approval_trust_registry,
    )
    from .user_context import current_tenant_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for compensation rule assessment",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    try:
        request = FederatedProjectionCompensationRuleAssessmentRequest.model_validate(
            {"proposal": proposal, "rules": rules}
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    if request.proposal.tenant_id != context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_mismatch",
                "message": "Compensation proposal tenant_id must match the MCP tenant",
            },
            ensure_ascii=False,
        )
    try:
        trust_registry = load_customer_compensation_approval_trust_registry()
        result = assess_federated_projection_compensation_rules(
            request.proposal,
            request.rules,
            trust_registry,
        )
    except CustomerCompensationApprovalTrustConfigurationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_approval_trust_registry_configuration_error",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except CustomerCompensationRuleError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "compensation_rule_assessment_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_assess_persisted_federated_projection_compensation_rules(
    run_id: str,
) -> str:
    """Assess persisted proposal/rule authority current state by run ID only."""

    from pydantic import ValidationError

    from .cross_store_projection_compensation_rule_authority import (
        CustomerCompensationRuleAuthorityConfigurationError,
        CustomerCompensationRuleAuthorityError,
        CustomerCompensationRuleAuthorityForbiddenError,
        CustomerCompensationRuleAuthorityValidationError,
        PostgresCustomerCompensationRuleAuthorityStore,
    )
    from .cross_store_projection_compensation_rule_contract import (
        FederatedProjectionCompensationRuleAuthorityAssessmentRequest,
    )
    from .cross_store_projection_compensation_trust import (
        CustomerCompensationApprovalTrustConfigurationError,
    )
    from .user_context import current_tenant_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for persisted rule assessment",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    try:
        query = FederatedProjectionCompensationRuleAuthorityAssessmentRequest(
            run_id=run_id
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    try:
        result = PostgresCustomerCompensationRuleAuthorityStore(
            context_tenant
        ).assess_current(query.run_id)
    except CustomerCompensationApprovalTrustConfigurationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_approval_trust_registry_configuration_error",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except CustomerCompensationRuleAuthorityConfigurationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_compensation_rule_authority_unavailable",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except CustomerCompensationRuleAuthorityForbiddenError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_compensation_rule_authority_forbidden",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except CustomerCompensationRuleAuthorityValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_compensation_rule_assessment_invalid",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    except CustomerCompensationRuleAuthorityError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "customer_compensation_rule_authority_error",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    if result is None:
        return json.dumps(
            {
                "status": "error",
                "code": "compensation_proposal_not_found",
                "message": (
                    "No persisted compensation proposal exists for this federated run"
                ),
            },
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_request_federated_projection_compensation_approval(
    run_id: str,
    candidate_sha256: str,
    idempotency_key: str,
    request_reason: str,
    requested_at: str,
    expires_at: str,
) -> str:
    """Request review of one trusted persisted compensation candidate."""

    import os

    from pydantic import ValidationError

    from .approval_case_authority import (
        ApprovalCaseAuthority,
        ApprovalCaseAuthorityError,
        ApprovalCaseConfigurationError,
        ApprovalCaseConflictError,
        ApprovalCaseForbiddenError,
        ApprovalCaseValidationError,
    )
    from .cross_store_projection_compensation_approval import (
        FederatedProjectionCompensationApprovalCaseRequest,
        FederatedProjectionCompensationApprovalError,
        FederatedProjectionCompensationApprovalNotFoundError,
        FederatedProjectionCompensationApprovalService,
    )
    from .cross_store_projection_compensation_rule_authority import (
        CustomerCompensationRuleAuthorityConfigurationError,
        CustomerCompensationRuleAuthorityError,
        CustomerCompensationRuleAuthorityForbiddenError,
        CustomerCompensationRuleAuthorityValidationError,
        PostgresCustomerCompensationRuleAuthorityStore,
    )
    from .cross_store_projection_compensation_trust import (
        CustomerCompensationApprovalTrustConfigurationError,
    )
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for compensation review",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    try:
        request = FederatedProjectionCompensationApprovalCaseRequest.model_validate(
            {
                "run_id": run_id,
                "candidate_sha256": candidate_sha256,
                "idempotency_key": idempotency_key,
                "request_reason": request_reason,
                "requested_at": requested_at,
                "expires_at": expires_at,
            }
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    try:
        result = FederatedProjectionCompensationApprovalService(
            PostgresCustomerCompensationRuleAuthorityStore(context_tenant),
            ApprovalCaseAuthority(),
        ).request_review(
            request,
            requester_subject=(
                f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
            ),
            owner_ref=os.environ.get(
                "GDA_APPROVAL_CASE_OWNER_REF",
                "team:data-platform",
            ),
        )
    except FederatedProjectionCompensationApprovalNotFoundError as exc:
        code = "compensation_proposal_not_found"
        status = "not_found"
        message = str(exc)
    except FederatedProjectionCompensationApprovalError as exc:
        code = "compensation_approval_not_reviewable"
        status = "invalid"
        message = str(exc)
    except CustomerCompensationApprovalTrustConfigurationError as exc:
        code = "customer_approval_trust_registry_configuration_error"
        status = "error"
        message = str(exc)
    except CustomerCompensationRuleAuthorityConfigurationError as exc:
        code = "customer_compensation_rule_authority_unavailable"
        status = "error"
        message = str(exc)
    except CustomerCompensationRuleAuthorityForbiddenError as exc:
        code = "customer_compensation_rule_authority_forbidden"
        status = "forbidden"
        message = str(exc)
    except CustomerCompensationRuleAuthorityValidationError as exc:
        code = "customer_compensation_rule_assessment_invalid"
        status = "invalid"
        message = str(exc)
    except ApprovalCaseConfigurationError as exc:
        code = exc.code
        status = "error"
        message = str(exc)
    except ApprovalCaseForbiddenError as exc:
        code = exc.code
        status = "forbidden"
        message = str(exc)
    except ApprovalCaseConflictError as exc:
        code = exc.code
        status = "conflict"
        message = str(exc)
    except ApprovalCaseValidationError as exc:
        code = exc.code
        status = "invalid"
        message = str(exc)
    except CustomerCompensationRuleAuthorityError as exc:
        code = "customer_compensation_rule_authority_error"
        status = "error"
        message = str(exc)
    except ApprovalCaseAuthorityError as exc:
        code = exc.code
        status = "error"
        message = str(exc)
    else:
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    return json.dumps(
        {"status": status, "code": code, "message": message},
        ensure_ascii=False,
    )


def _mcp_request_federated_projection_compensation_execution_approval(
    run_id: str,
    candidate_sha256: str,
    review_approval_case_ref: str,
    idempotency_key: str,
    request_reason: str,
    requested_at: str,
    expires_at: str,
) -> str:
    """Request a second human verdict without consuming or executing it."""

    import os

    from pydantic import ValidationError

    from .approval_case_authority import (
        ApprovalCaseAuthority,
        ApprovalCaseAuthorityError,
        ApprovalCaseConfigurationError,
        ApprovalCaseConflictError,
        ApprovalCaseForbiddenError,
        ApprovalCaseNotFoundError,
        ApprovalCaseValidationError,
    )
    from .cross_store_projection_compensation_approval import (
        FederatedProjectionCompensationApprovalError,
        FederatedProjectionCompensationApprovalNotFoundError,
        FederatedProjectionCompensationExecutionApprovalRequest,
        FederatedProjectionCompensationExecutionApprovalService,
    )
    from .cross_store_projection_compensation_rule_authority import (
        CustomerCompensationRuleAuthorityConfigurationError,
        CustomerCompensationRuleAuthorityError,
        CustomerCompensationRuleAuthorityForbiddenError,
        CustomerCompensationRuleAuthorityValidationError,
        PostgresCustomerCompensationRuleAuthorityStore,
    )
    from .cross_store_projection_compensation_trust import (
        CustomerCompensationApprovalTrustConfigurationError,
    )
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for compensation execution review",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    try:
        request = FederatedProjectionCompensationExecutionApprovalRequest.model_validate(
            {
                "run_id": run_id,
                "candidate_sha256": candidate_sha256,
                "review_approval_case_ref": review_approval_case_ref,
                "idempotency_key": idempotency_key,
                "request_reason": request_reason,
                "requested_at": requested_at,
                "expires_at": expires_at,
            }
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    try:
        result = FederatedProjectionCompensationExecutionApprovalService(
            PostgresCustomerCompensationRuleAuthorityStore(context_tenant),
            ApprovalCaseAuthority(),
        ).request_execution_authorization(
            request,
            requester_subject=(
                f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
            ),
            owner_ref=os.environ.get(
                "GDA_APPROVAL_CASE_OWNER_REF",
                "team:data-platform",
            ),
        )
    except FederatedProjectionCompensationApprovalNotFoundError as exc:
        code = "compensation_proposal_not_found"
        status = "not_found"
        message = str(exc)
    except FederatedProjectionCompensationApprovalError as exc:
        code = "compensation_execution_approval_not_reviewable"
        status = "invalid"
        message = str(exc)
    except CustomerCompensationApprovalTrustConfigurationError as exc:
        code = "customer_approval_trust_registry_configuration_error"
        status = "error"
        message = str(exc)
    except CustomerCompensationRuleAuthorityConfigurationError as exc:
        code = "customer_compensation_rule_authority_unavailable"
        status = "error"
        message = str(exc)
    except CustomerCompensationRuleAuthorityForbiddenError as exc:
        code = "customer_compensation_rule_authority_forbidden"
        status = "forbidden"
        message = str(exc)
    except CustomerCompensationRuleAuthorityValidationError as exc:
        code = "customer_compensation_rule_assessment_invalid"
        status = "invalid"
        message = str(exc)
    except ApprovalCaseConfigurationError as exc:
        code = exc.code
        status = "error"
        message = str(exc)
    except ApprovalCaseNotFoundError as exc:
        code = exc.code
        status = "not_found"
        message = str(exc)
    except ApprovalCaseForbiddenError as exc:
        code = exc.code
        status = "forbidden"
        message = str(exc)
    except ApprovalCaseConflictError as exc:
        code = exc.code
        status = "conflict"
        message = str(exc)
    except ApprovalCaseValidationError as exc:
        code = exc.code
        status = "invalid"
        message = str(exc)
    except CustomerCompensationRuleAuthorityError as exc:
        code = "customer_compensation_rule_authority_error"
        status = "error"
        message = str(exc)
    except ApprovalCaseAuthorityError as exc:
        code = exc.code
        status = "error"
        message = str(exc)
    else:
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    return json.dumps(
        {"status": status, "code": code, "message": message},
        ensure_ascii=False,
    )


def _mcp_execute_vector_projection_repair(
    plan: dict[str, Any],
    checkpointed_by: str,
    rows: list[dict[str, Any]] | None = None,
) -> str:
    """Execute a sealed pgvector repair plan through the canonical service."""
    from pydantic import ValidationError

    from .user_context import current_tenant_id, current_user_id, current_user_role
    from .vector_projection_service import (
        VectorProjectionRepairRequest,
        VectorProjectionServiceError,
        execute_vector_projection_repair,
    )

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for vector projection repair",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    actor_ref = f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
    if checkpointed_by != actor_ref:
        return json.dumps(
            {
                "status": "error",
                "code": "checkpoint_actor_mismatch",
                "message": "checkpointed_by must match the MCP subject",
            },
            ensure_ascii=False,
        )
    try:
        request = VectorProjectionRepairRequest.model_validate(
            {
                "plan": plan,
                "rows": rows or [],
                "checkpointed_by": checkpointed_by,
            }
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    if request.plan.tenant_id != context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_mismatch",
                "message": "Repair plan tenant_id must match the MCP tenant",
            },
            ensure_ascii=False,
        )
    try:
        result = execute_vector_projection_repair(request)
    except VectorProjectionServiceError as exc:
        return json.dumps(
            {"status": "error", "code": exc.code, "message": str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_execute_rdf_projection_repair(
    plan: dict[str, Any],
    checkpointed_by: str,
) -> str:
    """Execute a sealed RDF repair plan through the canonical service."""
    from pydantic import ValidationError

    from .rdf_projection_service import (
        RDFProjectionRepairRequest,
        RDFProjectionServiceError,
        execute_rdf_projection_repair,
    )
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for RDF projection repair",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    actor_ref = f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
    if checkpointed_by != actor_ref:
        return json.dumps(
            {
                "status": "error",
                "code": "checkpoint_actor_mismatch",
                "message": "checkpointed_by must match the MCP subject",
            },
            ensure_ascii=False,
        )
    try:
        request = RDFProjectionRepairRequest.model_validate(
            {
                "plan": plan,
                "checkpointed_by": checkpointed_by,
            }
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    if request.plan.tenant_id != context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_mismatch",
                "message": "Repair plan tenant_id must match the MCP tenant",
            },
            ensure_ascii=False,
        )
    try:
        result = execute_rdf_projection_repair(request)
    except RDFProjectionServiceError as exc:
        return json.dumps(
            {"status": "error", "code": exc.code, "message": str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_execute_lakehouse_projection_repair(
    plan: dict[str, Any],
    checkpointed_by: str,
) -> str:
    """Execute a sealed Iceberg repair plan through the canonical service."""
    from pydantic import ValidationError

    from .lakehouse_projection_service import (
        LakehouseProjectionRepairRequest,
        LakehouseProjectionServiceError,
        execute_lakehouse_projection_repair,
    )
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for lakehouse projection repair",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    actor_ref = f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
    if checkpointed_by != actor_ref:
        return json.dumps(
            {
                "status": "error",
                "code": "checkpoint_actor_mismatch",
                "message": "checkpointed_by must match the MCP subject",
            },
            ensure_ascii=False,
        )
    try:
        request = LakehouseProjectionRepairRequest.model_validate(
            {"plan": plan, "checkpointed_by": checkpointed_by}
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    if request.plan.tenant_id != context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_mismatch",
                "message": "Repair plan tenant_id must match the MCP tenant",
            },
            ensure_ascii=False,
        )
    try:
        result = execute_lakehouse_projection_repair(request)
    except LakehouseProjectionServiceError as exc:
        return json.dumps(
            {"status": "error", "code": exc.code, "message": str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_execute_object_projection_repair(
    plan: dict[str, Any],
    checkpointed_by: str,
) -> str:
    """Execute a sealed S3 object repair plan through the canonical service."""
    from pydantic import ValidationError

    from .object_projection_service import (
        ObjectProjectionRepairRequest,
        ObjectProjectionServiceError,
        execute_object_projection_repair,
    )
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for object projection repair",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    actor_ref = f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
    if checkpointed_by != actor_ref:
        return json.dumps(
            {
                "status": "error",
                "code": "checkpoint_actor_mismatch",
                "message": "checkpointed_by must match the MCP subject",
            },
            ensure_ascii=False,
        )
    try:
        request = ObjectProjectionRepairRequest.model_validate(
            {
                "plan": plan,
                "checkpointed_by": checkpointed_by,
            }
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    if request.plan.tenant_id != context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_mismatch",
                "message": "Repair plan tenant_id must match the MCP tenant",
            },
            ensure_ascii=False,
        )
    try:
        result = execute_object_projection_repair(request)
    except ObjectProjectionServiceError as exc:
        return json.dumps(
            {"status": "error", "code": exc.code, "message": str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_submit_entity_data_package_reconciliation(
    tenant_id: str,
    previous_baseline: dict[str, Any],
    desired_baseline: dict[str, Any],
    effective_at: str,
    evaluated_at: str,
    idempotency_key: str,
    recorded_by: str,
    batch_size: int = 250,
    verify_replay: bool = True,
) -> str:
    """Submit a durable asynchronous Chongqing reconciliation job."""
    from pydantic import ValidationError

    from .chongqing_data_package_reconciliation_job import (
        ChongqingDataPackageReconciliationJobError,
        submit_chongqing_data_package_reconciliation_job,
    )
    from .chongqing_data_package_reconciliation_service import (
        ChongqingDataPackageReconciliationRequest,
    )
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    actor_ref = f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
    if not context_tenant:
        return json.dumps({"status": "error", "code": "tenant_context_required"})
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps({"status": "error", "code": "platform_role_required"})
    if tenant_id != context_tenant:
        return json.dumps({"status": "error", "code": "tenant_mismatch"})
    if recorded_by != actor_ref:
        return json.dumps({"status": "error", "code": "actor_mismatch"})
    try:
        submission = ChongqingDataPackageReconciliationRequest.model_validate(
            {
                "tenant_id": tenant_id,
                "previous_baseline": previous_baseline,
                "desired_baseline": desired_baseline,
                "effective_at": effective_at,
                "evaluated_at": evaluated_at,
                "batch_size": batch_size,
                "verify_replay": verify_replay,
                "idempotency_key": idempotency_key,
                "recorded_by": recorded_by,
            }
        )
        result = submit_chongqing_data_package_reconciliation_job(submission)
    except ValidationError as exc:
        return json.dumps(
            {"status": "error", "code": "contract_validation_failed", "message": str(exc)},
            ensure_ascii=False,
        )
    except ChongqingDataPackageReconciliationJobError as exc:
        return json.dumps(
            {"status": "error", "code": exc.code, "message": str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_get_entity_data_package_reconciliation_job(
    tenant_id: str,
    job_id: str,
) -> str:
    """Read asynchronous Chongqing reconciliation job status."""
    from pydantic import ValidationError
    from uuid import UUID

    from .chongqing_data_package_reconciliation_job import (
        ChongqingDataPackageReconciliationJobError,
        ChongqingDataPackageReconciliationJobQuery,
        get_chongqing_data_package_reconciliation_job,
    )
    from .user_context import current_tenant_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps({"status": "error", "code": "tenant_context_required"})
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps({"status": "error", "code": "platform_role_required"})
    if tenant_id != context_tenant:
        return json.dumps({"status": "error", "code": "tenant_mismatch"})
    try:
        result = get_chongqing_data_package_reconciliation_job(
            ChongqingDataPackageReconciliationJobQuery(job_id=UUID(job_id)),
            tenant_id=tenant_id,
        )
    except (ValidationError, ValueError) as exc:
        return json.dumps(
            {"status": "error", "code": "contract_validation_failed", "message": str(exc)}
        )
    except ChongqingDataPackageReconciliationJobError as exc:
        return json.dumps({"status": "error", "code": exc.code, "message": str(exc)})
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_cancel_entity_data_package_reconciliation_job(
    tenant_id: str,
    job_id: str,
    reason: str,
) -> str:
    """Request cooperative asynchronous reconciliation cancellation."""
    from pydantic import ValidationError
    from uuid import UUID

    from .chongqing_data_package_reconciliation_job import (
        ChongqingDataPackageReconciliationJobCancelRequest,
        ChongqingDataPackageReconciliationJobError,
        cancel_chongqing_data_package_reconciliation_job,
    )
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    actor_ref = f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
    if not context_tenant:
        return json.dumps({"status": "error", "code": "tenant_context_required"})
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps({"status": "error", "code": "platform_role_required"})
    if tenant_id != context_tenant:
        return json.dumps({"status": "error", "code": "tenant_mismatch"})
    try:
        result = cancel_chongqing_data_package_reconciliation_job(
            ChongqingDataPackageReconciliationJobCancelRequest(
                job_id=UUID(job_id),
                requested_by=actor_ref,
                reason=reason,
            ),
            tenant_id=tenant_id,
        )
    except (ValidationError, ValueError) as exc:
        return json.dumps(
            {"status": "error", "code": "contract_validation_failed", "message": str(exc)}
        )
    except ChongqingDataPackageReconciliationJobError as exc:
        return json.dumps({"status": "error", "code": exc.code, "message": str(exc)})
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _mcp_record_entity_lineage_event(
    tenant_id: str,
    event_ref: str,
    lineage_kind: str,
    effective_at: str,
    source_entity_refs: list[str],
    target_entity_refs: list[str],
    source_version_refs: list[str],
    link_propagations: list[dict[str, Any]],
    source_identity_redirects: list[dict[str, Any]],
    idempotency_key: str,
    owner_subject: str,
    recorded_by: str,
    reason: str,
) -> str:
    """Record one governed entity merge, split, or replacement atomically."""
    from pydantic import ValidationError

    from .entity_lineage_authority import (
        EntityLineageAuthority,
        EntityLineageAuthorityError,
        EntityLineageRequest,
    )
    from .user_context import current_tenant_id, current_user_id, current_user_role

    context_tenant = current_tenant_id.get().strip()
    if not context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_context_required",
                "message": "MCP_TENANT is required for entity lineage",
            },
            ensure_ascii=False,
        )
    if current_user_role.get().strip() not in {"admin", "platform_operator"}:
        return json.dumps(
            {
                "status": "error",
                "code": "platform_role_required",
                "message": "Platform operator role is required",
            },
            ensure_ascii=False,
        )
    if tenant_id != context_tenant:
        return json.dumps(
            {
                "status": "error",
                "code": "tenant_mismatch",
                "message": "Request tenant_id must match the MCP tenant",
            },
            ensure_ascii=False,
        )
    actor_ref = f"agent:{current_user_id.get().strip() or 'mcp-agent'}"
    if recorded_by != actor_ref:
        return json.dumps(
            {
                "status": "error",
                "code": "actor_mismatch",
                "message": "recorded_by must match the MCP agent identity",
            },
            ensure_ascii=False,
        )
    try:
        request = EntityLineageRequest.model_validate(
            {
                "tenant_id": tenant_id,
                "event_ref": event_ref,
                "lineage_kind": lineage_kind,
                "effective_at": effective_at,
                "source_entity_refs": source_entity_refs,
                "target_entity_refs": target_entity_refs,
                "source_version_refs": source_version_refs,
                "link_propagations": link_propagations,
                "source_identity_redirects": source_identity_redirects,
                "idempotency_key": idempotency_key,
                "owner_subject": owner_subject,
                "recorded_by": recorded_by,
                "reason": reason,
            }
        )
    except ValidationError as exc:
        return json.dumps(
            {
                "status": "error",
                "code": "contract_validation_failed",
                "message": str(exc),
            },
            ensure_ascii=False,
        )
    try:
        result = EntityLineageAuthority().record(request)
    except EntityLineageAuthorityError as exc:
        return json.dumps(
            {"status": "error", "code": exc.code, "message": str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _get_tool_functions() -> Dict[str, Callable]:
    """Lazy-import all tool functions. Called once during registration."""
    from .toolsets.exploration_tools import (
        describe_geodataframe,
        reproject_spatial_data,
        engineer_spatial_features,
    )
    from .gis_processors import (
        perform_clustering,
        create_buffer,
        overlay_difference,
        summarize_within,
        find_within_distance,
        generate_tessellation,
        raster_to_polygon,
        pairwise_clip,
        check_topology,
        check_field_standards,
        polygon_neighbors,
        add_field,
        add_join,
        calculate_field,
        summary_statistics,
        surface_parameters,
        zonal_statistics_as_table,
        generate_heatmap,
    )
    from .geocoding import (
        batch_geocode,
        reverse_geocode,
        calculate_driving_distance,
        search_nearby_poi,
        search_poi_by_keyword,
        get_admin_boundary,
    )
    from .toolsets.visualization_tools import (
        visualize_geodataframe,
        visualize_interactive_map,
        generate_choropleth,
        generate_bubble_map,
        compose_map,
    )
    from .database_tools import (
        query_database,
        list_tables,
        describe_table,
    )
    from .remote_sensing import (
        describe_raster,
        calculate_ndvi,
        raster_band_math,
        classify_raster,
        visualize_raster,
    )
    from .spatial_statistics import (
        spatial_autocorrelation,
        local_moran,
        hotspot_analysis,
    )
    from .data_catalog import search_data_assets, get_data_lineage
    from .capabilities import list_builtin_skills, list_toolsets

    return {
        "describe_geodataframe": describe_geodataframe,
        "reproject_spatial_data": reproject_spatial_data,
        "engineer_spatial_features": engineer_spatial_features,
        "perform_clustering": perform_clustering,
        "create_buffer": create_buffer,
        "overlay_difference": overlay_difference,
        "summarize_within": summarize_within,
        "find_within_distance": find_within_distance,
        "generate_tessellation": generate_tessellation,
        "raster_to_polygon": raster_to_polygon,
        "pairwise_clip": pairwise_clip,
        "check_topology": check_topology,
        "check_field_standards": check_field_standards,
        "polygon_neighbors": polygon_neighbors,
        "add_field": add_field,
        "add_join": add_join,
        "calculate_field": calculate_field,
        "summary_statistics": summary_statistics,
        "surface_parameters": surface_parameters,
        "zonal_statistics_as_table": zonal_statistics_as_table,
        "generate_heatmap": generate_heatmap,
        "batch_geocode": batch_geocode,
        "reverse_geocode": reverse_geocode,
        "calculate_driving_distance": calculate_driving_distance,
        "search_nearby_poi": search_nearby_poi,
        "search_poi_by_keyword": search_poi_by_keyword,
        "get_admin_boundary": get_admin_boundary,
        "visualize_geodataframe": visualize_geodataframe,
        "visualize_interactive_map": visualize_interactive_map,
        "generate_choropleth": generate_choropleth,
        "generate_bubble_map": generate_bubble_map,
        "compose_map": compose_map,
        "query_database": query_database,
        "list_tables": list_tables,
        "describe_table": describe_table,
        "describe_raster": describe_raster,
        "calculate_ndvi": calculate_ndvi,
        "raster_band_math": raster_band_math,
        "classify_raster": classify_raster,
        "visualize_raster": visualize_raster,
        "spatial_autocorrelation": spatial_autocorrelation,
        "local_moran": local_moran,
        "hotspot_analysis": hotspot_analysis,
        # --- High-level metadata tools (v13.1) ---
        "search_catalog": search_data_assets,
        "get_data_lineage": get_data_lineage,
        "list_skills": _mcp_list_skills,
        "list_toolsets": _mcp_list_toolsets,
        "list_virtual_sources": _mcp_list_virtual_sources,
        "run_analysis_pipeline": _mcp_run_pipeline,
        "execute_governed_query": _mcp_execute_governed_query,
        "ingest_entity_authority_batch": _mcp_ingest_entity_authority_batch,
        "reconcile_entity_data_package": _mcp_reconcile_entity_data_package,
        "execute_postgis_projection_repair": _mcp_execute_postgis_projection_repair,
        "generate_federated_projection_compensation_proposal": (
            _mcp_generate_federated_projection_compensation_proposal
        ),
        "get_federated_projection_compensation_proposal": (
            _mcp_get_federated_projection_compensation_proposal
        ),
        "get_federated_projection_compensation_rules": (
            _mcp_get_federated_projection_compensation_rules
        ),
        "assess_federated_projection_compensation_rules": (
            _mcp_assess_federated_projection_compensation_rules
        ),
        "assess_persisted_federated_projection_compensation_rules": (
            _mcp_assess_persisted_federated_projection_compensation_rules
        ),
        "request_federated_projection_compensation_approval": (
            _mcp_request_federated_projection_compensation_approval
        ),
        "request_federated_projection_compensation_execution_approval": (
            _mcp_request_federated_projection_compensation_execution_approval
        ),
        "execute_vector_projection_repair": _mcp_execute_vector_projection_repair,
        "execute_rdf_projection_repair": _mcp_execute_rdf_projection_repair,
        "execute_lakehouse_projection_repair": _mcp_execute_lakehouse_projection_repair,
        "execute_object_projection_repair": _mcp_execute_object_projection_repair,
        "submit_entity_data_package_reconciliation": (
            _mcp_submit_entity_data_package_reconciliation
        ),
        "get_entity_data_package_reconciliation_job": (
            _mcp_get_entity_data_package_reconciliation_job
        ),
        "cancel_entity_data_package_reconciliation_job": (
            _mcp_cancel_entity_data_package_reconciliation_job
        ),
        "record_entity_lineage_event": _mcp_record_entity_lineage_event,
    }


# ---------------------------------------------------------------------------
# Tool definitions — metadata for each tool
# ---------------------------------------------------------------------------

# Annotation presets
_READ_ONLY = ToolAnnotations(readOnlyHint=True)
_WRITE_SAFE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
_DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
_DESTRUCTIVE_IDEMPOTENT = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
)
_CONTROL_WRITE_IDEMPOTENT = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
)

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    # --- Exploration (read-only) ---
    {
        "name": "describe_geodataframe",
        "description": "数据画像：统计空间数据的要素数、CRS、字段、空值率、坐标异常等质量问题。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "reproject_spatial_data",
        "description": "坐标重投影：将空间数据从当前CRS转换到目标CRS（如 EPSG:4326、EPSG:3857）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "engineer_spatial_features",
        "description": "特征工程：自动计算面积、周长、质心坐标、形状指数等空间特征。",
        "annotations": _WRITE_SAFE,
    },
    # --- Processing ---
    {
        "name": "perform_clustering",
        "description": "DBSCAN空间聚类：对点数据进行密度聚类分析。参数 eps（搜索半径）和 min_samples（最小样本数）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "create_buffer",
        "description": "缓冲区分析：在要素周围创建指定距离的缓冲区，可选融合。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "overlay_difference",
        "description": "叠置擦除：从 input_file 中擦除 erase_file 覆盖的区域。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "summarize_within",
        "description": "区域汇总：统计落在多边形区域内的要素数量和属性统计值。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "find_within_distance",
        "description": "距离筛选：根据与参考要素的距离筛选目标要素（within/outside模式）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "generate_tessellation",
        "description": "格网生成：在输入范围内生成规则格网（SQUARE/HEXAGON/TRIANGLE）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "raster_to_polygon",
        "description": "栅格转面：将栅格数据（.tif）转换为矢量面要素。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "pairwise_clip",
        "description": "要素裁剪：用裁剪要素的范围裁剪输入要素。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "check_topology",
        "description": "拓扑检查：扫描自相交、重叠、多部件几何等拓扑错误。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "check_field_standards",
        "description": "字段标准化检查：验证属性数据是否符合指定的标准模式（字段名、类型、允许值）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "polygon_neighbors",
        "description": "面邻域分析：找出每个面要素的相邻面及共享边界长度。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "add_field",
        "description": "添加字段：在属性表中添加新字段（TEXT/FLOAT/INTEGER/DOUBLE），可设默认值。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "add_join",
        "description": "属性连接：基于共同字段将 join_file 的属性左连接到 target_file。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "calculate_field",
        "description": "字段计算：用表达式计算字段值，支持 !field! 语法引用其他字段。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "summary_statistics",
        "description": "汇总统计：按分组字段计算多种统计量（SUM/MEAN/MIN/MAX/COUNT/STD）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "surface_parameters",
        "description": "地表参数：从DEM栅格计算坡度（SLOPE）或坡向（ASPECT）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "zonal_statistics_as_table",
        "description": "分区统计：计算矢量区域内栅格值的统计摘要（均值、总和、计数等）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "generate_heatmap",
        "description": "核密度热力图：基于点数据生成KDE热力图栅格。",
        "annotations": _WRITE_SAFE,
    },
    # --- Geocoding ---
    {
        "name": "batch_geocode",
        "description": "批量地理编码：将Excel/CSV中的地址列转换为经纬度坐标（高德+Nominatim）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "reverse_geocode",
        "description": "逆地理编码：将坐标转换为详细地址信息。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "calculate_driving_distance",
        "description": "驾车距离计算：计算两点之间的驾车距离和预计时间（高德路径规划API）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "search_nearby_poi",
        "description": "周边POI搜索：搜索指定坐标点附近的兴趣点（银行、学校、医院等）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "search_poi_by_keyword",
        "description": "关键字POI搜索：在指定城市/区域内搜索兴趣点。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_admin_boundary",
        "description": "行政区划边界：下载指定行政区的矢量边界数据（Shapefile）。",
        "annotations": _WRITE_SAFE,
    },
    # --- Visualization ---
    {
        "name": "visualize_geodataframe",
        "description": "静态地图：可视化单份地理数据为PNG图片。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "visualize_interactive_map",
        "description": "交互地图：生成多图层交互式HTML地图（Folium）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "generate_choropleth",
        "description": "等值区域图：按属性值分级着色的专题地图（支持多种分类方法和色带）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "generate_bubble_map",
        "description": "气泡地图：按属性值控制点大小和颜色的专题地图。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "compose_map",
        "description": "多图层合成：将多个数据源叠加为一张交互地图（点、面、等值、热力、气泡图层）。",
        "annotations": _WRITE_SAFE,
    },
    # --- Database ---
    {
        "name": "query_database",
        "description": "SQL查询：对PostgreSQL/PostGIS数据库执行SQL查询，空间结果返回SHP、非空间返回CSV。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_tables",
        "description": "列出数据表：查看当前用户可访问的数据库表（自有+共享）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "describe_table",
        "description": "表结构描述：查看指定数据表的列名和数据类型。",
        "annotations": _READ_ONLY,
    },
    # --- Remote Sensing ---
    {
        "name": "describe_raster",
        "description": "栅格数据画像：统计波段数、CRS、数据类型、NoData值，以及每个波段的统计信息。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "calculate_ndvi",
        "description": "NDVI植被指数计算：从多波段影像计算归一化植被指数。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "raster_band_math",
        "description": "波段代数运算：对栅格波段执行自定义数学表达式（如 (b4-b3)/(b4+b3)）。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "classify_raster",
        "description": "非监督分类：对栅格数据进行KMeans聚类分类，输出分类栅格和类别统计。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "visualize_raster",
        "description": "栅格可视化：将栅格波段渲染为PNG图片（单波段伪彩色或RGB合成）。",
        "annotations": _WRITE_SAFE,
    },
    # --- Spatial Statistics ---
    {
        "name": "spatial_autocorrelation",
        "description": "全局空间自相关检验：计算 Moran's I 统计量，评估属性值的空间聚集/分散模式。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "local_moran",
        "description": "LISA 局部空间自相关：识别 HH（高-高热点）、LL（低-低冷点）等空间聚类，输出 SHP + PNG。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "hotspot_analysis",
        "description": "Getis-Ord Gi* 热点分析：识别统计显著的热点和冷点区域，输出 SHP + PNG。",
        "annotations": _WRITE_SAFE,
    },
    # --- High-level metadata & pipeline tools (v13.1) ---
    {
        "name": "search_catalog",
        "description": "语义搜索数据目录：结合模糊匹配和向量嵌入检索已注册的数据资产（支持自然语言查询）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_data_lineage",
        "description": "数据血缘追踪：查看数据资产的来源链（ancestors）和衍生链（descendants）。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_skills",
        "description": "列出所有内置 ADK 技能：返回名称、描述、领域和触发关键词。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_toolsets",
        "description": "列出所有工具集：返回 24 个专业工具集的名称和功能描述。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_virtual_sources",
        "description": "列出虚拟数据源：返回已注册的远程 WFS/STAC/OGC API/自定义 API 数据源。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "run_analysis_pipeline",
        "description": "执行完整分析管线：将自然语言分析需求交给 GIS Agent 执行（通用分析/治理报告/DRL优化），返回分析报告和文件。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "execute_governed_query",
        "description": "执行受治理语义查询：校验路由计划、租户身份和资源版本，并返回可验证证据。",
        "annotations": _WRITE_SAFE,
    },
    {
        "name": "ingest_entity_authority_batch",
        "description": (
            "写入受治理实体权威批次：支持实体断言、来源身份、"
            "Link 类型和 Link 断言，并强制租户、执行身份、幂等和技术基线边界。"
        ),
        "annotations": _DESTRUCTIVE,
    },
    {
        "name": "reconcile_entity_data_package",
        "description": (
            "对重庆客户数据包执行受治理增量协调：服务内部读取实体、来源身份和 Link "
            "当前权威状态，生成并执行密封计划，返回计划/回执/最终状态哈希及分项计数。"
            "仅用于自然资源本体 2.3.0 的未审定技术基线辅助预审，不产生法定审批结论。"
        ),
        "annotations": _DESTRUCTIVE_IDEMPOTENT,
    },
    {
        "name": "submit_entity_data_package_reconciliation",
        "description": (
            "提交可恢复的重庆客户数据包异步 reconciliation 任务，返回任务状态、"
            "进度、租约恢复和取消证据；仅用于自然资源本体 2.3.0 的技术基线辅助预审。"
        ),
        "annotations": _DESTRUCTIVE_IDEMPOTENT,
    },
    {
        "name": "execute_postgis_projection_repair",
        "description": (
            "执行密封的 PostGIS 投影 checkpoint/rebuild/delete 计划；目标必须由部署侧显式注册，"
            "请求不能提交 SQL 或目标 DDL；回执绑定 plan SHA-256 和幂等键，并自动写入"
            "PostgreSQL checkpoint authority。"
        ),
        "annotations": _DESTRUCTIVE_IDEMPOTENT,
    },
    {
        "name": "generate_federated_projection_compensation_proposal",
        "description": (
            "仅根据密封的 federated recovery snapshot 和 sealed projection plans "
            "生成确定性的补偿候选方案；绑定重庆客户数据与自然资源本体 2.3.0，"
            "只读、不持久化、不选择或执行任何变更。始终返回 technical_baseline_unreviewed "
            "和 assisted_precheck_not_for_production_decision；客户 rollback/delete/restore/"
            "corrective-forward/reconciliation 规则缺失时明确返回待补规则标识。"
        ),
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_federated_projection_compensation_proposal",
        "description": (
            "按 federated recovery run_id 从 PostgreSQL authority 读取认证租户的当前补偿"
            "方案和完整不可变历史；run_id 是唯一工具参数，tenant/role 只能来自 MCP context。"
            "该工具只返回 technical_baseline_unreviewed 辅助预审证据，不记录、不选择、不批准、"
            "不执行任何补偿候选，且 execution_allowed 始终为 false。不存在与 authority 不可用"
            "分别返回明确错误，不能将数据库故障解释为无方案。"
        ),
        "annotations": _READ_ONLY,
    },
    {
        "name": "get_federated_projection_compensation_rules",
        "description": (
            "按 MCP 认证租户读取 PostgreSQL customer compensation rule authority 的 "
            "current/history；可选 rule_id 只用于缩小查询范围。范围固定为重庆客户数据和 "
            "自然资源本体 2.3.0，始终保留 technical_baseline_unreviewed 与 "
            "assisted_precheck_not_for_production_decision。工具只读，不写入、不批准、"
            "不选择、不执行规则；execution_allowed 和 "
            "automatic_mutating_selection_allowed 始终为 false。"
        ),
        "annotations": _READ_ONLY,
    },
    {
        "name": "assess_federated_projection_compensation_rules",
        "description": (
            "只读评估调用方提交的版本化客户补偿规则与 sealed federated proposal 是否匹配；"
            "范围固定为重庆客户数据和自然资源本体 2.3.0，明确区分 missing、draft_unreviewed、"
            "awaiting_customer_approval、approved_but_not_executable 与 invalid_or_drifted。"
            "customer_approved 还必须匹配部署侧按租户注册的 authority、key、算法、公钥指纹、"
            "有效期和撤销状态；请求体不能提交或覆盖该注册表。注册表缺失或配置损坏会明确返回"
            "trust/configuration 错误。工具不持久化、不创建批准、不选择或执行变更；"
            "automatic_mutating_selection_allowed 和 execution_allowed 始终为 false。"
        ),
        "annotations": _READ_ONLY,
    },
    {
        "name": "assess_persisted_federated_projection_compensation_rules",
        "description": (
            "仅按 run_id 在同一 PostgreSQL 快照中读取认证租户的 sealed proposal current "
            "与 customer compensation rule authority current 并评估规则覆盖。调用方不能上传"
            "或覆盖 proposal、rule、tenant 或部署 trust registry。结果明确区分 missing、"
            "draft_unreviewed、awaiting_customer_approval、approved_but_not_executable 和 "
            "invalid_or_drifted；始终只用于 technical_baseline_unreviewed 辅助预审，不写入、"
            "不批准、不选择、不执行补偿动作。"
        ),
        "annotations": _READ_ONLY,
    },
    {
        "name": "request_federated_projection_compensation_approval",
        "description": (
            "为认证租户中已持久化 proposal 的一个操作员显式选择候选申请人工审查。"
            "系统在同一权威快照中校验客户规则 current、部署信任锚、候选与 proposal 的"
            "密封绑定，只创建幂等 ApprovalCase 控制记录；仅支持 corrective-forward、"
            "rollback、delete、restore。该案例始终是 technical_baseline_unreviewed 辅助"
            "预审，不代表客户、专家、生产或法定批准，不自动选择候选，也不调用 Provider "
            "或授予执行权限。"
        ),
        "annotations": _CONTROL_WRITE_IDEMPOTENT,
    },
    {
        "name": "request_federated_projection_compensation_execution_approval",
        "description": (
            "在 review-only ApprovalCase 已由人工批准后，重新从认证租户的 proposal current "
            "和客户规则 current 构建同一候选绑定，并申请第二个独立人工执行裁决案例。该工具"
            "只创建幂等控制记录，不消费裁决、不调用 Provider、不执行补偿动作；review 批准"
            "本身不是执行权限，第二个案例也不是 Provider 执行结果。输出始终保留 "
            "technical_baseline_unreviewed 与 assisted_precheck_not_for_production_decision，"
            "不代表客户、专家、生产或法定批准。"
        ),
        "annotations": _CONTROL_WRITE_IDEMPOTENT,
    },
    {
        "name": "execute_vector_projection_repair",
        "description": (
            "执行密封的 pgvector 投影 checkpoint/rebuild/delete 计划；目标及向量维度必须由"
            "部署侧显式注册，请求不能提交 SQL 或目标 DDL；回执绑定 plan SHA-256 和幂等键，"
            "并自动写入 PostgreSQL checkpoint authority。"
        ),
        "annotations": _DESTRUCTIVE_IDEMPOTENT,
    },
    {
        "name": "execute_rdf_projection_repair",
        "description": (
            "执行密封的 RDF 投影 checkpoint/rebuild/delete 计划；Fuseki 目标和自然资源本体"
            "包必须由部署侧显式注册，请求不能提交 RDF 内容、端点、凭据或图标识；回执绑定"
            "plan SHA-256 和幂等键，并自动写入 PostgreSQL checkpoint authority。"
        ),
        "annotations": _DESTRUCTIVE_IDEMPOTENT,
    },
    {
        "name": "execute_lakehouse_projection_repair",
        "description": (
            "执行密封的 Spark/Iceberg 湖仓投影 checkpoint/rebuild/delete 计划；warehouse、"
            "catalog、table、Spark 配置和重庆客户 artifact 必须由部署侧显式注册，请求不能"
            "提交行数据、存储端点、凭据或表标识；回执绑定 Iceberg snapshot、plan SHA-256"
            "和幂等键，并自动写入 PostgreSQL checkpoint authority。"
        ),
        "annotations": _DESTRUCTIVE_IDEMPOTENT,
    },
    {
        "name": "execute_object_projection_repair",
        "description": (
            "执行密封的 S3/MinIO 对象投影 checkpoint/rebuild/delete 计划；目标和客户重庆"
            "artifact 必须由部署侧显式注册，请求不能提交对象字节、端点、凭据、bucket、key"
            "或本地路径；回执绑定不可变 VersionId、plan SHA-256 和幂等键，并自动写入"
            "PostgreSQL checkpoint authority。"
        ),
        "annotations": _DESTRUCTIVE_IDEMPOTENT,
    },
    {
        "name": "get_entity_data_package_reconciliation_job",
        "description": "查询重庆数据包异步 reconciliation 任务状态、进度、取消证据和最终回执。",
        "annotations": _READ_ONLY,
    },
    {
        "name": "cancel_entity_data_package_reconciliation_job",
        "description": (
            "请求在下一个原子 authority 批次边界取消重庆数据包 reconciliation；已提交批次不回滚。"
        ),
        "annotations": _DESTRUCTIVE_IDEMPOTENT,
    },
    {
        "name": "record_entity_lineage_event",
        "description": (
            "原子记录实体合并、拆分或替代：完整校验并退役源实体、撤回旧 Link、"
            "创建或去重新 Link、追加来源身份重定向；任何未分配 Link、来源身份、"
            "类型/基数/自环冲突都会整笔失败，结果仅限技术基线辅助预审。"
        ),
        "annotations": _DESTRUCTIVE,
    },
]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_all_tools(mcp_server) -> int:
    """Register all GIS tools with a FastMCP server instance.

    Returns:
        Number of tools registered.
    """
    fn_map = _get_tool_functions()
    count = 0
    for defn in TOOL_DEFINITIONS:
        name = defn["name"]
        fn = fn_map.get(name)
        if fn is None:
            print(f"[MCP Registry] WARNING: function '{name}' not found, skipping.")
            continue
        wrapped = _wrap_tool(fn)
        mcp_server.add_tool(
            wrapped,
            name=name,
            description=defn.get("description"),
            annotations=defn.get("annotations"),
        )
        count += 1
    return count
