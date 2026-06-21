from __future__ import annotations


class GeoCausalError(Exception):
    """Base class for user-facing GeoCausal failures."""


class GeoCausalConfigError(GeoCausalError):
    """Raised when an analysis YAML file is invalid."""


class GeoCausalInputError(GeoCausalError):
    """Raised when an input dataset cannot be loaded or validated."""


class GeoCausalPipelineError(GeoCausalError):
    """Raised when an analysis cannot be completed."""
