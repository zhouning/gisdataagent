"""Deployment-profile contracts and fail-closed runtime verification."""

from .deployment_profile import DeploymentProfile, load_deployment_profile
from .runtime_probe import DeploymentProfileVerifier, VerificationReport

__all__ = [
    "DeploymentProfile",
    "DeploymentProfileVerifier",
    "VerificationReport",
    "load_deployment_profile",
]
