"""Deterministic classification of Razorpay failure reasons into recovery categories.

Reason strings come from Razorpay's documented list (data/razorpay_error_reasons.json).
Classification is a lookup, not a judgment call, so no AI is involved here:
a rule table is auditable, testable, and can never hallucinate a retry
against a compliance block.
"""

from dataclasses import dataclass
from enum import Enum


class Category(str, Enum):
    TRANSIENT = "transient"                  # bank/gateway/psp hiccup — safe to auto-retry
    INSUFFICIENT_FUNDS = "insufficient_funds"  # money missing — retry later + nudge
    CUSTOMER_FUMBLE = "customer_fumble"      # bad OTP/PIN/CVV, cancelled — re-invite quickly
    INSTRUMENT_INVALID = "instrument_invalid"  # dead card/account/VPA — ask for another method
    LIMIT_EXCEEDED = "limit_exceeded"        # daily/txn limits — retry next day
    DO_NOT_RETRY = "do_not_retry"            # risk/compliance/duplicates — humans only
    MERCHANT_CONFIG = "merchant_config"      # our-side misconfiguration — alert merchant
    AMBIGUOUS = "ambiguous"                  # bank tells us nothing — LLM decides


REASON_CATEGORY: dict[str, Category] = {
    # -- transient infrastructure problems: retry with backoff --
    "bank_cutoff_in_progress": Category.TRANSIENT,
    "bank_not_available": Category.TRANSIENT,
    "bank_technical_error": Category.TRANSIENT,
    "gateway_technical_error": Category.TRANSIENT,
    "issuer_technical_error": Category.TRANSIENT,
    "invalid_response_from_gateway": Category.TRANSIENT,
    "payment_declined_due_to_high_traffic": Category.TRANSIENT,
    "payment_timed_out": Category.TRANSIENT,
    "request_timed_out": Category.TRANSIENT,
    "server_error": Category.TRANSIENT,
    "upi_app_technical_error": Category.TRANSIENT,
    "psp_not_available": Category.TRANSIENT,
    "psp_app_not_available": Category.TRANSIENT,
    "authorisation_declined_by_psp": Category.TRANSIENT,
    "deemed_transaction": Category.TRANSIENT,

    # -- not enough money: schedule retry + payment link + polite reminder --
    "insufficient_funds": Category.INSUFFICIENT_FUNDS,
    "credit_limit_exceeded": Category.INSUFFICIENT_FUNDS,

    # -- the customer stumbled at the last step: fresh link, fast --
    "authentication_failed": Category.CUSTOMER_FUMBLE,
    "incorrect_otp": Category.CUSTOMER_FUMBLE,
    "otp_expired": Category.CUSTOMER_FUMBLE,
    "otp_attempts_exceeded": Category.CUSTOMER_FUMBLE,
    "incorrect_cvv": Category.CUSTOMER_FUMBLE,
    "incorrect_pin": Category.CUSTOMER_FUMBLE,
    "incorrect_atm_pin": Category.CUSTOMER_FUMBLE,
    "pin_attempts_exceeded": Category.CUSTOMER_FUMBLE,
    "payment_cancelled": Category.CUSTOMER_FUMBLE,
    "payment_session_expired": Category.CUSTOMER_FUMBLE,
    "payment_collect_request_expired": Category.CUSTOMER_FUMBLE,
    "collect_request_pending": Category.CUSTOMER_FUMBLE,
    "incorrect_card_details": Category.CUSTOMER_FUMBLE,
    "incorrect_card_expiry_date": Category.CUSTOMER_FUMBLE,
    "incorrect_cardholder_name": Category.CUSTOMER_FUMBLE,

    # -- the instrument itself is dead: don't hammer it, offer alternatives --
    "card_expired": Category.INSTRUMENT_INVALID,
    "card_number_invalid": Category.INSTRUMENT_INVALID,
    "card_not_enrolled": Category.INSTRUMENT_INVALID,
    "bank_account_invalid": Category.INSTRUMENT_INVALID,
    "bank_account_validation_failed": Category.INSTRUMENT_INVALID,
    "beneficiary_account_does_not_exist": Category.INSTRUMENT_INVALID,
    "beneficiary_account_dormant": Category.INSTRUMENT_INVALID,
    "invalid_vpa": Category.INSTRUMENT_INVALID,
    "vpa_resolution_failed": Category.INSTRUMENT_INVALID,
    "debit_instrument_blocked": Category.INSTRUMENT_INVALID,
    "debit_instrument_inactive": Category.INSTRUMENT_INVALID,
    "pin_not_set": Category.INSTRUMENT_INVALID,
    "user_not_registered_for_netbanking": Category.INSTRUMENT_INVALID,
    "psp_not_registered": Category.INSTRUMENT_INVALID,

    # -- limits reset with time: retry after the window --
    "transaction_daily_count_exceeded": Category.LIMIT_EXCEEDED,
    "transaction_daily_limit_exceeded": Category.LIMIT_EXCEEDED,
    "transaction_limit_exceeded": Category.LIMIT_EXCEEDED,
    "transaction_frequency_limit_exceeded": Category.LIMIT_EXCEEDED,
    "mcc_amount_limit_exceeded": Category.LIMIT_EXCEEDED,

    # -- never retry automatically --
    "payment_risk_check_failed": Category.DO_NOT_RETRY,
    "compliance_violation": Category.DO_NOT_RETRY,
    "payment_amount_tampered": Category.DO_NOT_RETRY,
    "international_transaction_not_allowed": Category.DO_NOT_RETRY,
    "duplicate_request": Category.DO_NOT_RETRY,
    "duplicate_rrn_found": Category.DO_NOT_RETRY,
    "order_already_paid": Category.DO_NOT_RETRY,
    "funds_blocked_by_mandate": Category.DO_NOT_RETRY,
    "transaction_on_vpa_restricted": Category.DO_NOT_RETRY,
    "user_not_eligible": Category.DO_NOT_RETRY,
    "credit_not_permitted": Category.DO_NOT_RETRY,

    # -- merchant-side configuration: alert us, not the customer --
    "payment_method_not_enabled": Category.MERCHANT_CONFIG,
    "merchant_not_activated": Category.MERCHANT_CONFIG,
    "live_mode_not_enabled": Category.MERCHANT_CONFIG,
    "recurring_payment_not_enabled": Category.MERCHANT_CONFIG,
    "upi_collect_not_enabled": Category.MERCHANT_CONFIG,
    "upi_intent_not_enabled": Category.MERCHANT_CONFIG,
    "card_network_not_enabled": Category.MERCHANT_CONFIG,
    "bank_not_enabled": Category.MERCHANT_CONFIG,
    "invalid_order_id": Category.MERCHANT_CONFIG,
    "order_amount_mismatch": Category.MERCHANT_CONFIG,
    "order_payment_method_mismatch": Category.MERCHANT_CONFIG,
    "amount_less_than_minimum_amount": Category.MERCHANT_CONFIG,
    "input_validation_failed": Category.MERCHANT_CONFIG,
    "invalid_amount": Category.MERCHANT_CONFIG,
    "invalid_currency": Category.MERCHANT_CONFIG,
    "invalid_request": Category.MERCHANT_CONFIG,

    # -- the bank told us nothing: hand to the LLM with context --
    "payment_failed": Category.AMBIGUOUS,
    "payment_declined": Category.AMBIGUOUS,
    "card_declined": Category.AMBIGUOUS,
    "debit_declined": Category.AMBIGUOUS,
    "capture_failed": Category.AMBIGUOUS,
    "verification_failed": Category.AMBIGUOUS,
}


@dataclass(frozen=True)
class RetryPolicy:
    """Hard bounds enforced in code — the LLM can pick within these, never outside."""
    max_attempts: int
    cooldown_minutes: list[int]  # wait before attempt 1, 2, ... (len == max_attempts)
    send_payment_link: bool
    notify_customer: bool
    needs_llm: bool = False


POLICIES: dict[Category, RetryPolicy] = {
    Category.TRANSIENT: RetryPolicy(3, [10, 60, 360], send_payment_link=False, notify_customer=False),
    Category.INSUFFICIENT_FUNDS: RetryPolicy(2, [1440, 4320], send_payment_link=True, notify_customer=True),
    Category.CUSTOMER_FUMBLE: RetryPolicy(2, [5, 720], send_payment_link=True, notify_customer=True),
    Category.INSTRUMENT_INVALID: RetryPolicy(1, [10], send_payment_link=True, notify_customer=True),
    Category.LIMIT_EXCEEDED: RetryPolicy(1, [1440], send_payment_link=True, notify_customer=True),
    Category.DO_NOT_RETRY: RetryPolicy(0, [], send_payment_link=False, notify_customer=False),
    Category.MERCHANT_CONFIG: RetryPolicy(0, [], send_payment_link=False, notify_customer=False),
    Category.AMBIGUOUS: RetryPolicy(2, [30, 1440], send_payment_link=True, notify_customer=True, needs_llm=True),
}


def classify(reason: str) -> Category:
    """Unknown reasons are AMBIGUOUS by design: the safe default is bounded
    LLM-assisted handling, never an unbounded auto-retry."""
    return REASON_CATEGORY.get(reason.strip().lower(), Category.AMBIGUOUS)


def policy_for(reason: str) -> tuple[Category, RetryPolicy]:
    cat = classify(reason)
    return cat, POLICIES[cat]
