"""Gatehold local admission-control core."""

from .admission import GateholdService
from .config import GateholdConfig

__all__ = ["GateholdConfig", "GateholdService"]
__version__ = "0.1.0"
