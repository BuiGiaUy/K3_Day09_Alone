"""Shared policy, schema, and model declarations."""

from decimal import Decimal

EXECUTION_ENGINE = "deterministic_python"
MODEL_NAME = "qwen-qwen3-8b"
MODEL_PARAMETER_SIZE_BILLION = 8
MODEL_PROVIDER = "Qwen"
MODEL_INVOCATION_ENABLED = False

POLICY_VERSION = "EC_POLICY_V1"
PAYMENT_TOLERANCE = Decimal("0.10")
MONEY_QUANTUM = Decimal("0.01")

MAX_ENTITY_IDS = 5
MAX_EVIDENCE_IDS = 10
MAX_ROOT_CAUSES = 3
MAX_RESPONSIBLE_PARTIES = 3
MAX_ACTIONS = 5

PRIMARY_ISSUES = {
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
}
CASE_STATUSES = {"action_required", "no_action"}
CAUSE_CODES = {
    "ORDER_CANCELED_AFTER_PAYMENT",
    "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "SELLER_HANDOFF_AFTER_LIMIT",
    "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "MULTIPLE_PAYMENTS_RECONCILED",
    "DELIVERY_WITHIN_ESTIMATE",
}
PARTY_TYPES = {"platform", "seller", "logistics_provider"}
RESOLUTION_ACTIONS = {
    "issue_full_refund",
    "refund_freight",
    "explain_valid_split_payment",
    "reject_late_refund",
}

