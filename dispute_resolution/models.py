"""Typed data contracts exchanged by the autonomous software agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class CaseRequest:
    case_id: str
    opened_at: str
    claimed_order_id: str
    policy_version: str


@dataclass(frozen=True)
class OrderRecord:
    order_id: str
    customer_id: str
    order_status: str
    carrier_date: Optional[datetime]
    delivered_date: Optional[datetime]
    estimated_date: Optional[datetime]


@dataclass(frozen=True)
class ItemRecord:
    order_id: str
    item_id: int
    product_id: str
    seller_id: str
    shipping_limit_date: datetime
    price: Decimal
    freight: Decimal


@dataclass(frozen=True)
class PaymentRecord:
    order_id: str
    sequential: int
    payment_type: str
    installments: int
    value: Decimal


@dataclass(frozen=True)
class OrderSellerTask:
    case_id: str
    order_id: str


@dataclass(frozen=True)
class ItemFinding:
    item_id: int
    product_id: str
    seller_id: str
    shipping_limit_date: datetime
    handoff_late: Optional[bool]
    price: Decimal
    freight: Decimal


@dataclass(frozen=True)
class OrderSellerFinding:
    order_id: str
    customer_id: str
    order_status: str
    carrier_date: Optional[datetime]
    delivered_date: Optional[datetime]
    estimated_date: Optional[datetime]
    items: Tuple[ItemFinding, ...]
    seller_ids: Tuple[str, ...]
    item_total: Decimal
    freight_total: Decimal


@dataclass(frozen=True)
class PaymentTask:
    case_id: str
    order_id: str
    item_total: Decimal
    freight_total: Decimal


@dataclass(frozen=True)
class PaymentFinding:
    order_id: str
    rows: Tuple[PaymentRecord, ...]
    payment_total: Decimal
    expected_total: Decimal
    reconciled: bool
    split_payment: bool


@dataclass(frozen=True)
class DeliveryTask:
    case_id: str
    order: OrderSellerFinding


@dataclass(frozen=True)
class DeliveryFinding:
    order_id: str
    delivered_late: Optional[bool]
    seller_handoff_late: Optional[bool]
    violating_seller_ids: Tuple[str, ...]
    estimated_date: Optional[datetime]
    delivered_date: Optional[datetime]
    carrier_date: Optional[datetime]


@dataclass(frozen=True)
class PolicyTask:
    case: CaseRequest
    order: OrderSellerFinding
    payment: PaymentFinding
    delivery: DeliveryFinding


@dataclass(frozen=True)
class ResponsibleParty:
    party_type: str
    party_id: str


@dataclass(frozen=True)
class PolicyDecision:
    primary_issue: str
    case_status: str
    confidence: Decimal
    cause_code: str
    responsible_parties: Tuple[ResponsibleParty, ...]
    recommended_refund: Decimal
    action: str


@dataclass(frozen=True)
class VerificationTask:
    case: CaseRequest
    candidate: dict[str, Any]
    order: OrderSellerFinding
    payment: PaymentFinding
    delivery: DeliveryFinding
    decision: PolicyDecision


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    errors: Tuple[str, ...]


@dataclass(frozen=True)
class TraceEvent:
    sequence: int
    case_id: str
    sender: str
    receiver: str
    message_type: str
    payload: Any


def structured_payload(value: Any) -> Any:
    """Convert a typed handoff to deterministic JSON-compatible data."""
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: structured_payload(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [structured_payload(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value

