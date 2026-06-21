from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class StudySpec:
    """Explicit causal study configuration for an SCCA run."""

    name: str
    unit_id: str
    exposure: str
    outcome: str
    baseline_outcome: str | None = None
    population: str | None = None
    confounders: tuple[str, ...] = field(default_factory=tuple)
    context_columns: tuple[str, ...] = field(default_factory=tuple)
    coordinate_columns: tuple[str, str] | None = None
    subgroup_column: str | None = None

    @classmethod
    def snow8_default(cls) -> "StudySpec":
        return cls(
            name="south_london_cholera_supplier",
            unit_id="sub_ID",
            exposure="perc_sou",
            outcome="rate1854",
            baseline_outcome="rate1849",
            population="pop1854",
            confounders=("rate1849", "pop_house", "pop1851"),
            context_columns=("d_sou", "d_lam", "d_pump", "d_thames", "d_unasc"),
            subgroup_column="district",
        )

    @classmethod
    def soho_default(cls) -> "StudySpec":
        return cls(
            name="soho_broad_street_pump_mechanism",
            unit_id="ID",
            exposure="bspump_proximity",
            outcome="deaths",
            baseline_outcome=None,
            population=None,
            confounders=("dis_pestf", "dis_sewers", "pestfield"),
            context_columns=("COORD_X", "COORD_Y"),
            coordinate_columns=("COORD_X", "COORD_Y"),
            subgroup_column=None,
        )

    @classmethod
    def county_social_capital_default(cls) -> "StudySpec":
        return cls(
            name="county_social_capital_longevity_validation",
            unit_id="FIPS",
            exposure="SocialAssoc",
            outcome="AveAgeDeath",
            baseline_outcome=None,
            population=None,
            confounders=(
                "UnemployRate",
                "pHHinPoverty",
                "pNoHealthInsur",
                "MentalHealth",
                "pAdultSmoking",
                "pAdultObesity",
                "FastFood",
                "pInsufficientSleep",
                "pAlcohol",
                "pSuicideDeaths",
                "AirPollution",
            ),
            context_columns=("Shape_Length", "Shape_Area"),
            coordinate_columns=None,
            subgroup_column="STATE_NAME",
        )


@dataclass(frozen=True)
class SCCAPaths:
    """Output paths for one SCCA experiment run."""

    output_dir: Path

    def ensure(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def data_profile(self) -> Path:
        return self.output_dir / "data_profile.json"

    @property
    def variable_candidates(self) -> Path:
        return self.output_dir / "variable_candidates.csv"

    @property
    def context_features(self) -> Path:
        return self.output_dir / "context_features.csv"

    @property
    def context_manifest(self) -> Path:
        return self.output_dir / "context_feature_manifest.json"

    @property
    def design_plan(self) -> Path:
        return self.output_dir / "design_plan.json"

    @property
    def effect_estimates(self) -> Path:
        return self.output_dir / "effect_estimates.csv"

    @property
    def erf_curve(self) -> Path:
        return self.output_dir / "erf_curve.csv"

    @property
    def model_diagnostics(self) -> Path:
        return self.output_dir / "model_diagnostics.json"

    @property
    def balance_summary(self) -> Path:
        return self.output_dir / "balance_summary.csv"

    @property
    def overlap_summary(self) -> Path:
        return self.output_dir / "overlap_summary.json"

    @property
    def spatial_robustness(self) -> Path:
        return self.output_dir / "spatial_robustness.csv"

    @property
    def spatial_diagnostics(self) -> Path:
        return self.output_dir / "spatial_diagnostics.json"

    @property
    def spatial_bootstrap_robustness(self) -> Path:
        return self.output_dir / "spatial_bootstrap_robustness.csv"

    @property
    def spatial_bootstrap_summary(self) -> Path:
        return self.output_dir / "spatial_bootstrap_summary.json"

    @property
    def spatial_graph_sensitivity(self) -> Path:
        return self.output_dir / "spatial_graph_sensitivity.csv"

    @property
    def spatial_graph_sensitivity_summary(self) -> Path:
        return self.output_dir / "spatial_graph_sensitivity_summary.json"

    @property
    def spatial_slx_estimates(self) -> Path:
        return self.output_dir / "spatial_slx_estimates.csv"

    @property
    def spatial_slx_summary(self) -> Path:
        return self.output_dir / "spatial_slx_summary.json"

    @property
    def spatial_spillover_decomposition(self) -> Path:
        return self.output_dir / "spatial_spillover_decomposition.csv"

    @property
    def spatial_spillover_summary(self) -> Path:
        return self.output_dir / "spatial_spillover_summary.json"

    @property
    def spatial_exposure_mapping(self) -> Path:
        return self.output_dir / "spatial_exposure_mapping.csv"

    @property
    def spatial_exposure_mapping_summary(self) -> Path:
        return self.output_dir / "spatial_exposure_mapping_summary.json"

    @property
    def credibility_report(self) -> Path:
        return self.output_dir / "credibility_report.json"

    @property
    def analysis_report(self) -> Path:
        return self.output_dir / "analysis_report.md"

    @property
    def result_summary_markdown(self) -> Path:
        return self.output_dir / "result_summary.md"

    @property
    def manifest(self) -> Path:
        return self.output_dir / "manifest.json"
