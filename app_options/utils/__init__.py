"""Utility package."""

from app_options.utils.connectivity import (
    check_internet,
    is_transient_network_error,
    wait_for_internet,
)

__all__ = ["check_internet", "is_transient_network_error", "wait_for_internet"]
