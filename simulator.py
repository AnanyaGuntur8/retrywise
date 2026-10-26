"""Synthetic payment service and bounded retry policies used by the notebook."""

from dataclasses import dataclass

from collections import Counter

from typing import Dict, List, Tuple

import random

import pandas as pd

SEED = 2027

OUTCOMES = ("ok", "rate_limit", "server_error", "timeout_before_commit", "timeout_after_commit", "card_declined")

TRANSIENT = {"rate_limit", "server_error", "timeout_before_commit", "timeout_after_commit"}

@dataclass(frozen=True)
class Payment:
    payment_id: str
    amount_cents: int
    script: Tuple[str, ...]

def make_sample_payments(n=600, seed=SEED):
    rng = random.Random(seed)
    payments = []
    for i in range(n):
        amount = rng.randint(500, 20000)
        initial = rng.choices(
            OUTCOMES,
            weights=[70, 7, 7, 7, 4, 5],
            k=1,
        )[0]
        # Script outcomes for up to five attempts; later attempts are usually successful.
        followups = tuple(rng.choices(OUTCOMES, weights=[84, 3, 4, 3, 2, 4], k=4))
        payments.append(Payment(f"pay_{i:04d}", amount, (initial,) + followups))
    return payments

class SimulatedPaymentService:
    def __init__(self):
        self.success_by_key: Dict[str, int] = {}
        self.charge_count: Counter = Counter()
        self.attempts: Counter = Counter()

    def request(self, payment: Payment, key: str, *, use_idempotency=True):
        self.attempts[payment.payment_id] += 1
        number = self.attempts[payment.payment_id]

        if use_idempotency and key in self.success_by_key:
            if self.success_by_key[key] != payment.amount_cents:
                return "idempotency_conflict"
            return "ok_cached"

        # Repeat the final scripted outcome if attempts exceed the script length.
        outcome = payment.script[min(number - 1, len(payment.script) - 1)]
        if outcome in {"ok", "timeout_after_commit"}:
            self.charge_count[payment.payment_id] += 1
            if use_idempotency:
                self.success_by_key[key] = payment.amount_cents
        return outcome

@dataclass(frozen=True)
class RetryPolicy:
    name: str
    max_attempts: int = 4
    base_delay_ms: float = 100.0
    max_delay_ms: float = 1000.0
    jitter: bool = True
    use_idempotency: bool = True

def run_policy(payments: List[Payment], policy: RetryPolicy, seed=SEED):
    rng = random.Random(seed)
    service = SimulatedPaymentService()
    rows = []
    attempt_log = []
    for payment in payments:
        key = payment.payment_id  # unchanged across all attempts of this operation
        elapsed_ms = 0.0
        final = None
        for attempt in range(1, policy.max_attempts + 1):
            outcome = service.request(payment, key, use_idempotency=policy.use_idempotency)
            elapsed_ms += 45.0  # synthetic per-request network + processing time
            retryable = outcome in TRANSIENT
            should_retry = retryable and attempt < policy.max_attempts
            delay_ms = 0.0
            if should_retry:
                bound = min(policy.base_delay_ms * (2 ** (attempt - 1)), policy.max_delay_ms)
                delay_ms = rng.uniform(0, bound) if policy.jitter else bound
                elapsed_ms += delay_ms
            attempt_log.append({"payment_id": payment.payment_id, "attempt": attempt,
                                "outcome": outcome, "backoff_ms": delay_ms,
                                "retry_scheduled": should_retry})
            final = outcome
            if not should_retry:
                break
        charges = service.charge_count[payment.payment_id]
        rows.append({"payment_id": payment.payment_id, "amount_usd": payment.amount_cents / 100,
                     "final_outcome": final, "success": final in {"ok", "ok_cached"},
                     "attempts": service.attempts[payment.payment_id],
                     "elapsed_ms": elapsed_ms, "charges": charges,
                     "duplicate_charges": max(charges - 1, 0),
                     "exhausted": final in TRANSIENT and service.attempts[payment.payment_id] == policy.max_attempts})
    return pd.DataFrame(rows), pd.DataFrame(attempt_log)

NO_RETRY = RetryPolicy("No retries", max_attempts=1)

SAFE_RETRY = RetryPolicy("Retries with idempotency")

NO_IDEMPOTENCY = RetryPolicy("Retries without idempotency", use_idempotency=False)

def summarize(frame, label):
    return {"Policy": label,
            "Success rate (%)": round(100 * frame.success.mean(), 1),
            "Duplicate charges": int(frame.duplicate_charges.sum()),
            "Retry exhausted": int(frame.exhausted.sum()),
            "Total API attempts": int(frame.attempts.sum()),
            "Mean latency (ms)": round(frame.elapsed_ms.mean(), 1),
            "p95 latency (ms)": round(frame.elapsed_ms.quantile(.95), 1)}
