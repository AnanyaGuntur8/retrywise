"""Behavior checks for the payment retry simulator."""
import unittest

from simulator import (
    Payment, SimulatedPaymentService, SAFE_RETRY, NO_IDEMPOTENCY, run_policy,
)


class RetryTests(unittest.TestCase):
    def test_timeout_after_commit_does_not_double_charge(self):
        p = Payment("timeout_case", 1200, ("timeout_after_commit", "ok", "ok"))
        frame, log = run_policy([p], SAFE_RETRY)
        assert frame.iloc[0].success
        assert frame.iloc[0].charges == 1
        assert frame.iloc[0].duplicate_charges == 0
        assert list(log.outcome) == ["timeout_after_commit", "ok_cached"]

    def test_removing_idempotency_can_double_charge(self):
        p = Payment("unsafe_case", 1200, ("timeout_after_commit", "ok", "ok"))
        frame, _ = run_policy([p], NO_IDEMPOTENCY)
        assert frame.iloc[0].duplicate_charges == 1

    def test_decline_is_terminal(self):
        p = Payment("decline_case", 1200, ("card_declined", "ok"))
        frame, _ = run_policy([p], SAFE_RETRY)
        assert not frame.iloc[0].success
        assert frame.iloc[0].attempts == 1

    def test_retry_cap_and_exhaustion(self):
        p = Payment("always_failing", 1200, ("server_error",) * 5)
        frame, log = run_policy([p], SAFE_RETRY)
        assert frame.iloc[0].attempts == SAFE_RETRY.max_attempts
        assert frame.iloc[0].exhausted
        assert len(log) == SAFE_RETRY.max_attempts
        assert log.iloc[-1].backoff_ms == 0

    def test_full_jitter_bounds_and_reproducibility(self):
        p = Payment("retry_case", 1200, ("rate_limit", "server_error", "ok"))
        one, log1 = run_policy([p], SAFE_RETRY, seed=42)
        two, log2 = run_policy([p], SAFE_RETRY, seed=42)
        assert one.equals(two) and log1.equals(log2)
        assert 0 <= log1.iloc[0].backoff_ms <= 100
        assert 0 <= log1.iloc[1].backoff_ms <= 200

    def test_stable_key_replay_and_conflict(self):
        svc = SimulatedPaymentService()
        a = Payment("a", 1200, ("timeout_after_commit",))
        assert svc.request(a, "key-a") == "timeout_after_commit"
        assert svc.request(a, "key-a") == "ok_cached"
        b = Payment("b", 1500, ("ok",))
        assert svc.request(b, "key-a") == "idempotency_conflict"
        assert sum(svc.charge_count.values()) == 1
