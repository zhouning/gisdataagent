"""Abu Dhabi urban-flood world-model candidate adapter."""

from .anuga_adapter import AnugaQualityPolicy, evaluate_anuga_quality, execute_anuga
from .contracts import (
    DrainageLink,
    FloodAction,
    FloodNetwork,
    FloodState,
    RainfallForcing,
    SurfacePatch,
)
from .data_request_readiness import (
    build_data_request_readiness,
    render_data_request_readiness_markdown,
    write_data_request_readiness,
    write_data_request_readiness_markdown,
)
from .impact_assessment import (
    ExposureImpactUnit,
    FloodImpactAssessmentPolicy,
    FloodImpactAssessmentWindow,
    InundationImpactUnit,
    build_flood_impact_receipt,
    evaluate_flood_impact,
    verify_flood_impact_receipt,
)
from .k0_data_request import (
    K0DataRequestItem,
    K0DataRequestPackage,
    build_k0_data_request_receipt,
    default_k0_data_request_package,
    evaluate_k0_data_request,
    verify_k0_data_request_receipt,
)
from .lisflood_adapter import (
    LisfloodQualityPolicy,
    evaluate_lisflood_quality,
    execute_lisflood,
    parse_lisflood_ascii_grid,
    parse_lisflood_mass,
    parse_lisflood_parameters,
    parse_lisflood_stdout,
)
from .registered_anuga_diagnostic import (
    RegisteredAnugaDiagnosticPolicy,
    audit_local_contours,
    build_anuga_maximum_depth_layer,
    compile_registered_anuga_diagnostic,
    parse_swmm_node_coordinates,
)
from .simulator import (
    AbuDhabiFloodWorldModel,
    FloodModelConfig,
    FloodRollout,
    FloodStepTrace,
)
from .swmm_adapter import evaluate_swmm_quality, execute_swmm, parse_swmm_report
from .swmm_anuga_coupling import (
    SolverWindowBalance,
    SwmmAnugaCouplingInterface,
    SwmmAnugaCouplingQualityPolicy,
    SwmmAnugaCouplingWindow,
    SwmmAnugaTransfer,
    build_swmm_anuga_coupling_receipt,
    evaluate_swmm_anuga_coupling,
)
from .traditional_solver import (
    TraditionalSolverExecutionError,
    TraditionalSolverQualityPolicy,
    TraditionalSolverRunRequest,
)

__all__ = [
    "AbuDhabiFloodWorldModel",
    "AnugaQualityPolicy",
    "DrainageLink",
    "ExposureImpactUnit",
    "FloodAction",
    "FloodImpactAssessmentPolicy",
    "FloodImpactAssessmentWindow",
    "FloodModelConfig",
    "FloodNetwork",
    "FloodRollout",
    "FloodState",
    "FloodStepTrace",
    "LisfloodQualityPolicy",
    "InundationImpactUnit",
    "K0DataRequestItem",
    "K0DataRequestPackage",
    "build_data_request_readiness",
    "RainfallForcing",
    "RegisteredAnugaDiagnosticPolicy",
    "SolverWindowBalance",
    "SurfacePatch",
    "SwmmAnugaCouplingInterface",
    "SwmmAnugaCouplingQualityPolicy",
    "SwmmAnugaCouplingWindow",
    "SwmmAnugaTransfer",
    "TraditionalSolverExecutionError",
    "TraditionalSolverQualityPolicy",
    "TraditionalSolverRunRequest",
    "evaluate_swmm_quality",
    "evaluate_anuga_quality",
    "evaluate_lisflood_quality",
    "evaluate_swmm_anuga_coupling",
    "build_swmm_anuga_coupling_receipt",
    "build_flood_impact_receipt",
    "build_k0_data_request_receipt",
    "build_anuga_maximum_depth_layer",
    "compile_registered_anuga_diagnostic",
    "execute_anuga",
    "execute_lisflood",
    "execute_swmm",
    "evaluate_flood_impact",
    "evaluate_k0_data_request",
    "parse_swmm_report",
    "parse_swmm_node_coordinates",
    "parse_lisflood_ascii_grid",
    "parse_lisflood_mass",
    "parse_lisflood_parameters",
    "parse_lisflood_stdout",
    "verify_flood_impact_receipt",
    "verify_k0_data_request_receipt",
    "render_data_request_readiness_markdown",
    "write_data_request_readiness",
    "write_data_request_readiness_markdown",
    "default_k0_data_request_package",
    "audit_local_contours",
]
