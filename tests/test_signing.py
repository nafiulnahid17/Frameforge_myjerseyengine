import time

from frameforge_engine.signing import create_asset_token, verify_asset_token


def test_asset_token_is_job_bound_tamper_resistant_and_expires():
    expiry = int(time.time()) + 60
    token = create_asset_token("a" * 32, "strong-secret", expiry)
    assert verify_asset_token("a" * 32, token, "strong-secret") is True
    assert verify_asset_token("b" * 32, token, "strong-secret") is False
    assert verify_asset_token("a" * 32, token + "x", "strong-secret") is False
    expired = create_asset_token("a" * 32, "strong-secret", int(time.time()) - 1)
    assert verify_asset_token("a" * 32, expired, "strong-secret") is False

