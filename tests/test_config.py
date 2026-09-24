"""Unit tests for config and auth."""

from volta.auth.session import verify_credentials
from volta.config.assets import validate_base


def test_validate_base_ok() -> None:
    assert validate_base("btc") == "BTC"


def test_validate_base_invalid() -> None:
    import pytest

    with pytest.raises(ValueError):
        validate_base("DOGE")


def test_verify_credentials_wrong() -> None:
    assert verify_credentials("admin", "wrong") is False
