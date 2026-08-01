"""Exact-commit adapter for the official t-route Muskingum-Cunge kernel."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Protocol

import numpy as np


T_ROUTE_COMMIT = "12a8eae0cdfed437143c590659fa7077605a5e70"
T_ROUTE_MC_SOURCE_SCHEMA = "gwm.geotransport.t_route_mc_source_audit.v1"
T_ROUTE_MC_BUILD_SCHEMA = "gwm.geotransport.t_route_mc_runtime_build.v1"
T_ROUTE_MC_INITIALIZED_DIAGNOSTIC_BUILD_SCHEMA = (
    "gwm.geotransport.t_route_mc_initialized_diagnostic_runtime.v1"
)
T_ROUTE_MC_ADAPTER_SCHEMA = "gwm.geospatial_kernel.t_route_mc_baseline.v1"
T_ROUTE_MC_INITIALIZED_DIAGNOSTIC_PATCH_ID = (
    "explicit_secant_carry_initialization_v1"
)


@dataclass(frozen=True)
class TrouteMuskingumCungeParameters:
    feature_ids: tuple[int, ...]
    length_m: tuple[float, ...]
    bottom_width_m: tuple[float, ...]
    top_width_m: tuple[float, ...]
    compound_top_width_m: tuple[float, ...]
    manning_n: tuple[float, ...]
    compound_manning_n: tuple[float, ...]
    channel_side_slope_chslp: tuple[float, ...]
    bed_slope: tuple[float, ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if not self.feature_ids or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in self.feature_ids
        ):
            raise ValueError("t_route_mc_feature_ids_must_be_positive_integers")
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("t_route_mc_feature_ids_must_be_unique")
        fields = (
            "length_m",
            "bottom_width_m",
            "top_width_m",
            "compound_top_width_m",
            "manning_n",
            "compound_manning_n",
            "channel_side_slope_chslp",
            "bed_slope",
        )
        count = len(self.feature_ids)
        for name in fields:
            values = tuple(float(value) for value in getattr(self, name))
            if len(values) != count:
                raise ValueError("t_route_mc_parameter_count_mismatch")
            if not np.isfinite(values).all() or (np.asarray(values) <= 0.0).any():
                raise ValueError(f"t_route_mc_{name}_must_be_positive_finite")
            object.__setattr__(self, name, values)
        if not self.provenance_id.strip():
            raise ValueError("t_route_mc_parameter_provenance_required")

    @property
    def side_slope_horizontal_per_vertical(self) -> tuple[float, ...]:
        return tuple(1.0 / value for value in self.channel_side_slope_chslp)


@dataclass(frozen=True)
class TrouteMuskingumCungeState:
    feature_ids: tuple[int, ...]
    discharge_m3s: tuple[float, ...]
    velocity_mps: tuple[float, ...]
    depth_m: tuple[float, ...]
    provenance_id: str

    def __post_init__(self) -> None:
        count = len(self.feature_ids)
        if count == 0 or any(
            len(values) != count
            for values in (self.discharge_m3s, self.velocity_mps, self.depth_m)
        ):
            raise ValueError("t_route_mc_state_axis_mismatch")
        for values in (self.discharge_m3s, self.velocity_mps, self.depth_m):
            numeric = np.asarray(values, dtype=float)
            if not np.isfinite(numeric).all() or (numeric < 0.0).any():
                raise ValueError("t_route_mc_state_must_be_nonnegative_finite")
        if not self.provenance_id.strip():
            raise ValueError("t_route_mc_state_provenance_required")


@dataclass(frozen=True)
class TrouteMuskingumCungeStepResult:
    next_state: TrouteMuskingumCungeState
    boundary_previous_m3s: float
    boundary_current_m3s: float
    lateral_inflow_m3s: tuple[float, ...]
    celerity_mps: tuple[float, ...]
    courant_number: tuple[float, ...]
    muskingum_x: tuple[float, ...]
    local_reconstructed_equation_residual_m3: tuple[float, ...]
    network_reconstructed_equation_residual_m3: float
    network_reconstructed_mc_storage_increment_m3: float
    network_flux_balance_volume_m3: float
    assume_short_timestep: bool
    returned_ck_x_authoritative_for_equation_reconstruction: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": T_ROUTE_MC_ADAPTER_SCHEMA,
            "feature_ids": list(self.next_state.feature_ids),
            "discharge_m3s": list(self.next_state.discharge_m3s),
            "velocity_mps": list(self.next_state.velocity_mps),
            "depth_m": list(self.next_state.depth_m),
            "boundary_previous_m3s": self.boundary_previous_m3s,
            "boundary_current_m3s": self.boundary_current_m3s,
            "lateral_inflow_m3s": list(self.lateral_inflow_m3s),
            "celerity_mps": list(self.celerity_mps),
            "courant_number": list(self.courant_number),
            "muskingum_x": list(self.muskingum_x),
            "local_reconstructed_equation_residual_m3": list(
                self.local_reconstructed_equation_residual_m3
            ),
            "network_reconstructed_equation_residual_m3": (
                self.network_reconstructed_equation_residual_m3
            ),
            "network_reconstructed_mc_storage_increment_m3": (
                self.network_reconstructed_mc_storage_increment_m3
            ),
            "network_flux_balance_volume_m3": (
                self.network_flux_balance_volume_m3
            ),
            "assume_short_timestep": self.assume_short_timestep,
            "returned_ck_x_authoritative_for_equation_reconstruction": (
                self.returned_ck_x_authoritative_for_equation_reconstruction
            ),
        }


class MuskingumCungeSegmentKernel(Protocol):
    source_commit: str

    def step_segment(
        self,
        *,
        dt: float,
        qup: float,
        quc: float,
        qdp: float,
        ql: float,
        dx: float,
        bw: float,
        tw: float,
        twcc: float,
        n: float,
        ncc: float,
        cs: float,
        s0: float,
        velp: float,
        depthp: float,
    ) -> tuple[float, float, float, float, float, float]: ...


class CtypesTrouteMuskingumCungeKernel:
    """Load the official bind(C) entrypoint from a verified shared library."""

    source_commit = T_ROUTE_COMMIT

    def __init__(self, build_manifest_path: Path) -> None:
        manifest_body = build_manifest_path.read_bytes()
        manifest = json.loads(manifest_body)
        if (
            manifest.get("schema") != T_ROUTE_MC_BUILD_SCHEMA
            or manifest.get("source_commit") != T_ROUTE_COMMIT
            or manifest.get("official_source_unmodified") is not True
        ):
            raise ValueError("t_route_mc_runtime_build_manifest_invalid")
        descriptor = manifest.get("library_artifact") or {}
        library_path = Path(str(descriptor.get("path", "")))
        if not library_path.is_absolute():
            library_path = build_manifest_path.resolve().parents[3] / library_path
        body = library_path.read_bytes()
        if (
            hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
            or len(body) != descriptor.get("size_bytes")
        ):
            raise ValueError("t_route_mc_runtime_library_identity_mismatch")
        library = ctypes.CDLL(str(library_path))
        function = library.c_muskingcungenwm
        pointer = ctypes.POINTER(ctypes.c_float)
        function.argtypes = [pointer] * 21
        function.restype = None
        self._library = library
        self._function = function
        self.build_manifest_path = build_manifest_path
        self.library_path = library_path

    def step_segment(self, **values: float) -> tuple[float, ...]:
        names = (
            "dt",
            "qup",
            "quc",
            "qdp",
            "ql",
            "dx",
            "bw",
            "tw",
            "twcc",
            "n",
            "ncc",
            "cs",
            "s0",
            "velp",
            "depthp",
        )
        inputs = [ctypes.c_float(values[name]) for name in names]
        outputs = [ctypes.c_float(0.0) for _ in range(6)]
        self._function(
            *(ctypes.byref(value) for value in inputs),
            *(ctypes.byref(value) for value in outputs),
        )
        result = tuple(float(value.value) for value in outputs)
        if (
            not np.isfinite(result).all()
            or (np.asarray(result[:5]) < 0.0).any()
            or not 0.0 <= result[5] <= 0.5
        ):
            raise RuntimeError("t_route_mc_kernel_returned_invalid_state")
        return result


class CtypesInitializedDiagnosticTrouteMuskingumCungeKernel(
    CtypesTrouteMuskingumCungeKernel
):
    """Load the explicitly derived initialization experiment, never as official."""

    source_commit = T_ROUTE_COMMIT

    def __init__(self, build_manifest_path: Path) -> None:
        manifest_body = build_manifest_path.read_bytes()
        manifest = json.loads(manifest_body)
        if (
            manifest.get("schema") != T_ROUTE_MC_INITIALIZED_DIAGNOSTIC_BUILD_SCHEMA
            or manifest.get("source_commit") != T_ROUTE_COMMIT
            or manifest.get("patch_id")
            != T_ROUTE_MC_INITIALIZED_DIAGNOSTIC_PATCH_ID
            or manifest.get("official_source_unmodified") is not False
            or manifest.get("derived_diagnostic_only") is not True
            or manifest.get("claim_boundary", {}).get("official_runtime") is not False
        ):
            raise ValueError("t_route_mc_initialized_diagnostic_manifest_invalid")
        descriptor = manifest.get("library_artifact") or {}
        library_path = Path(str(descriptor.get("path", "")))
        if not library_path.is_absolute():
            library_path = build_manifest_path.resolve().parents[3] / library_path
        body = library_path.read_bytes()
        if (
            hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
            or len(body) != descriptor.get("size_bytes")
        ):
            raise ValueError("t_route_mc_initialized_diagnostic_library_mismatch")
        library = ctypes.CDLL(str(library_path))
        function = library.c_muskingcungenwm
        pointer = ctypes.POINTER(ctypes.c_float)
        function.argtypes = [pointer] * 21
        function.restype = None
        self._library = library
        self._function = function
        self.build_manifest_path = build_manifest_path
        self.library_path = library_path


class TrouteMuskingumCungeAdapter:
    """Advance a directed reach chain using the official t-route segment kernel."""

    def __init__(
        self,
        parameters: TrouteMuskingumCungeParameters,
        kernel: MuskingumCungeSegmentKernel,
        *,
        timestep_seconds: float,
        assume_short_timestep: bool = False,
    ) -> None:
        if kernel.source_commit != T_ROUTE_COMMIT:
            raise ValueError("t_route_mc_kernel_commit_mismatch")
        if not np.isfinite(timestep_seconds) or timestep_seconds <= 0.0:
            raise ValueError("t_route_mc_timestep_must_be_positive")
        if not isinstance(assume_short_timestep, bool):
            raise ValueError("t_route_mc_assume_short_timestep_must_be_boolean")
        self.parameters = parameters
        self.kernel = kernel
        self.timestep_seconds = float(timestep_seconds)
        self.assume_short_timestep = assume_short_timestep

    def zero_state(self, *, provenance_id: str) -> TrouteMuskingumCungeState:
        zeros = (0.0,) * len(self.parameters.feature_ids)
        return TrouteMuskingumCungeState(
            self.parameters.feature_ids, zeros, zeros, zeros, provenance_id
        )

    def step(
        self,
        state: TrouteMuskingumCungeState,
        *,
        boundary_previous_m3s: float,
        boundary_current_m3s: float,
        lateral_inflow_m3s: tuple[float, ...] | None = None,
        provenance_id: str,
    ) -> TrouteMuskingumCungeStepResult:
        if state.feature_ids != self.parameters.feature_ids:
            raise ValueError("t_route_mc_state_feature_axis_mismatch")
        boundary = np.asarray(
            [boundary_previous_m3s, boundary_current_m3s], dtype=float
        )
        if not np.isfinite(boundary).all() or (boundary < 0.0).any():
            raise ValueError("t_route_mc_boundary_must_be_nonnegative_finite")
        count = len(self.parameters.feature_ids)
        lateral = (
            np.zeros(count, dtype=float)
            if lateral_inflow_m3s is None
            else np.asarray(lateral_inflow_m3s, dtype=float)
        )
        if (
            lateral.shape != (count,)
            or not np.isfinite(lateral).all()
            or (lateral < 0.0).any()
        ):
            raise ValueError("t_route_mc_lateral_inflow_invalid")

        current_q: list[float] = []
        current_v: list[float] = []
        current_d: list[float] = []
        celerity: list[float] = []
        courant: list[float] = []
        muskingum_x: list[float] = []
        local_residuals: list[float] = []
        storage_increments: list[float] = []
        flux_balances: list[float] = []
        dt = self.timestep_seconds
        for index in range(count):
            qup = (
                float(boundary_previous_m3s)
                if index == 0
                else float(state.discharge_m3s[index - 1])
            )
            quc = qup if self.assume_short_timestep else (
                float(boundary_current_m3s)
                if index == 0
                else current_q[index - 1]
            )
            qdp = float(state.discharge_m3s[index])
            qdc, velc, depthc, ck, cn, x = self.kernel.step_segment(
                dt=dt,
                qup=qup,
                quc=quc,
                qdp=qdp,
                ql=float(lateral[index]),
                dx=self.parameters.length_m[index],
                bw=self.parameters.bottom_width_m[index],
                tw=self.parameters.top_width_m[index],
                twcc=self.parameters.compound_top_width_m[index],
                n=self.parameters.manning_n[index],
                ncc=self.parameters.compound_manning_n[index],
                cs=self.parameters.channel_side_slope_chslp[index],
                s0=self.parameters.bed_slope[index],
                velp=float(state.velocity_mps[index]),
                depthp=float(state.depth_m[index]),
            )
            k_seconds = (
                dt
                if ck <= 0.0
                else max(dt, self.parameters.length_m[index] / ck)
            )
            storage_increment = (
                k_seconds * x * (quc - qup)
                + k_seconds * (1.0 - x) * (qdc - qdp)
            )
            flux_balance = dt * (
                0.5 * (qup + quc - qdp - qdc) + float(lateral[index])
            )
            current_q.append(qdc)
            current_v.append(velc)
            current_d.append(depthc)
            celerity.append(ck)
            courant.append(cn)
            muskingum_x.append(x)
            storage_increments.append(storage_increment)
            flux_balances.append(flux_balance)
            local_residuals.append(storage_increment - flux_balance)

        next_state = TrouteMuskingumCungeState(
            feature_ids=self.parameters.feature_ids,
            discharge_m3s=tuple(current_q),
            velocity_mps=tuple(current_v),
            depth_m=tuple(current_d),
            provenance_id=provenance_id,
        )
        return TrouteMuskingumCungeStepResult(
            next_state=next_state,
            boundary_previous_m3s=float(boundary_previous_m3s),
            boundary_current_m3s=float(boundary_current_m3s),
            lateral_inflow_m3s=tuple(float(value) for value in lateral),
            celerity_mps=tuple(celerity),
            courant_number=tuple(courant),
            muskingum_x=tuple(muskingum_x),
            local_reconstructed_equation_residual_m3=tuple(local_residuals),
            network_reconstructed_equation_residual_m3=float(
                sum(local_residuals)
            ),
            network_reconstructed_mc_storage_increment_m3=float(
                sum(storage_increments)
            ),
            network_flux_balance_volume_m3=float(sum(flux_balances)),
            assume_short_timestep=self.assume_short_timestep,
        )
