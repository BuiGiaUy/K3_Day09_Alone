"""Autonomous deterministic agents and their domain-specific computations."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .constants import (
    CASE_STATUSES,
    CAUSE_CODES,
    MAX_ACTIONS,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE_IDS,
    MAX_RESPONSIBLE_PARTIES,
    MAX_ROOT_CAUSES,
    MONEY_QUANTUM,
    PARTY_TYPES,
    PAYMENT_TOLERANCE,
    POLICY_VERSION,
    PRIMARY_ISSUES,
    RESOLUTION_ACTIONS,
)
from .models import (
    DeliveryFinding,
    DeliveryTask,
    ItemFinding,
    OrderSellerFinding,
    OrderSellerTask,
    PaymentFinding,
    PaymentTask,
    PolicyDecision,
    PolicyTask,
    ResponsibleParty,
    VerificationResult,
    VerificationTask,
)
from .repository import OlistRepository


class AgentError(RuntimeError):
    """Raised when an agent cannot produce a valid deterministic result."""


CONFIDENCE_BY_ISSUE = {
    "canceled_order_paid": Decimal("0.98"),
    "unavailable_order_paid": Decimal("0.98"),
    "late_delivery_seller": Decimal("0.94"),
    "late_delivery_logistics": Decimal("0.92"),
    "valid_split_payment": Decimal("0.90"),
    "unsupported_late_claim": Decimal("0.88"),
}


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


class OrderSellerAgent:
    name = "OrderSellerAgent"

    def __init__(self, repository: OlistRepository) -> None:
        self.repository = repository

    def handle(self, task: OrderSellerTask) -> OrderSellerFinding:
        order = self.repository.order(task.order_id)
        items = self.repository.order_items(task.order_id)
        findings = tuple(
            ItemFinding(
                item_id=item.item_id,
                product_id=item.product_id,
                seller_id=item.seller_id,
                shipping_limit_date=item.shipping_limit_date,
                handoff_late=(
                    None
                    if order.carrier_date is None
                    else order.carrier_date > item.shipping_limit_date
                ),
                price=item.price,
                freight=item.freight,
            )
            for item in items
        )
        return OrderSellerFinding(
            order_id=order.order_id,
            customer_id=order.customer_id,
            order_status=order.order_status,
            carrier_date=order.carrier_date,
            delivered_date=order.delivered_date,
            estimated_date=order.estimated_date,
            items=findings,
            seller_ids=tuple(sorted({item.seller_id for item in findings})),
            item_total=money(sum((item.price for item in findings), Decimal("0"))),
            freight_total=money(
                sum((item.freight for item in findings), Decimal("0"))
            ),
        )


class PaymentAgent:
    name = "PaymentAgent"

    def __init__(self, repository: OlistRepository) -> None:
        self.repository = repository

    def handle(self, task: PaymentTask) -> PaymentFinding:
        rows = self.repository.order_payments(task.order_id)
        payment_total = money(sum((row.value for row in rows), Decimal("0")))
        expected_total = money(task.item_total + task.freight_total)
        return PaymentFinding(
            order_id=task.order_id,
            rows=rows,
            payment_total=payment_total,
            expected_total=expected_total,
            reconciled=abs(payment_total - expected_total) <= PAYMENT_TOLERANCE,
            split_payment=len(rows) >= 2,
        )


class DeliveryAgent:
    name = "DeliveryAgent"

    def handle(self, task: DeliveryTask) -> DeliveryFinding:
        order = task.order
        delivered_late = (
            None
            if order.delivered_date is None or order.estimated_date is None
            else order.delivered_date > order.estimated_date
        )
        handoff_values = [item.handoff_late for item in order.items]
        seller_handoff_late = (
            None
            if not handoff_values or any(value is None for value in handoff_values)
            else any(handoff_values)
        )
        violating_sellers = tuple(
            sorted({item.seller_id for item in order.items if item.handoff_late is True})
        )
        return DeliveryFinding(
            order_id=order.order_id,
            delivered_late=delivered_late,
            seller_handoff_late=seller_handoff_late,
            violating_seller_ids=violating_sellers,
            estimated_date=order.estimated_date,
            delivered_date=order.delivered_date,
            carrier_date=order.carrier_date,
        )


class PolicyAgent:
    name = "PolicyAgent"

    def handle(self, task: PolicyTask) -> PolicyDecision:
        if task.case.policy_version != POLICY_VERSION:
            raise AgentError(f"unsupported policy: {task.case.policy_version}")
        order = task.order
        payment = task.payment
        delivery = task.delivery

        # EC_POLICY_V1 priority is intentionally explicit and must not be reordered.
        if order.order_status == "canceled" and payment.payment_total > 0:
            return self._decision(
                "canceled_order_paid",
                "ORDER_CANCELED_AFTER_PAYMENT",
                (ResponsibleParty("platform", "OLIST_PLATFORM"),),
                payment.payment_total,
                "issue_full_refund",
            )
        if order.order_status == "unavailable" and payment.payment_total > 0:
            return self._decision(
                "unavailable_order_paid",
                "ORDER_UNAVAILABLE_AFTER_PAYMENT",
                (ResponsibleParty("platform", "OLIST_PLATFORM"),),
                payment.payment_total,
                "issue_full_refund",
            )
        if delivery.delivered_late is True and delivery.seller_handoff_late is True:
            return self._decision(
                "late_delivery_seller",
                "SELLER_HANDOFF_AFTER_LIMIT",
                tuple(
                    ResponsibleParty("seller", seller_id)
                    for seller_id in delivery.violating_seller_ids[
                        :MAX_RESPONSIBLE_PARTIES
                    ]
                ),
                order.freight_total,
                "refund_freight",
            )
        if delivery.delivered_late is True and delivery.seller_handoff_late is False:
            return self._decision(
                "late_delivery_logistics",
                "CARRIER_DELIVERED_AFTER_ESTIMATE",
                (ResponsibleParty("logistics_provider", "LOGISTICS_PROVIDER"),),
                order.freight_total,
                "refund_freight",
            )
        if payment.split_payment and payment.reconciled:
            return self._decision(
                "valid_split_payment",
                "MULTIPLE_PAYMENTS_RECONCILED",
                (),
                Decimal("0"),
                "explain_valid_split_payment",
            )
        if delivery.delivered_late is False and payment.reconciled:
            return self._decision(
                "unsupported_late_claim",
                "DELIVERY_WITHIN_ESTIMATE",
                (),
                Decimal("0"),
                "reject_late_refund",
            )
        raise AgentError(f"no EC_POLICY_V1 rule matched case {task.case.case_id}")

    @staticmethod
    def _decision(
        issue: str,
        cause: str,
        parties: tuple[ResponsibleParty, ...],
        refund: Decimal,
        action: str,
    ) -> PolicyDecision:
        return PolicyDecision(
            primary_issue=issue,
            case_status="action_required" if refund > 0 else "no_action",
            confidence=CONFIDENCE_BY_ISSUE[issue],
            cause_code=cause,
            responsible_parties=parties,
            recommended_refund=money(refund),
            action=action,
        )


class VerifierAgent:
    name = "VerifierAgent"

    def __init__(self, repository: OlistRepository) -> None:
        self.repository = repository

    def handle(self, task: VerificationTask) -> VerificationResult:
        errors: list[str] = []
        candidate = task.candidate
        self._validate_shape(candidate, errors)
        if errors:
            return VerificationResult(False, tuple(errors))

        assessment = candidate["assessment"]
        entities = candidate["affected_entities"]
        analysis = candidate["root_cause_analysis"]
        financial = candidate["financial_resolution"]
        decision = task.decision

        if candidate["case_id"] != task.case.case_id:
            errors.append("case_id mismatch")
        if assessment["primary_issue"] not in PRIMARY_ISSUES:
            errors.append("invalid primary_issue")
        if assessment["primary_issue"] != decision.primary_issue:
            errors.append("primary_issue does not match policy decision")
        if assessment["case_status"] not in CASE_STATUSES:
            errors.append("invalid case_status")
        if assessment["case_status"] != decision.case_status:
            errors.append("case_status does not match refund")
        confidence = assessment["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            errors.append("confidence must be numeric")
        elif not 0 <= confidence <= 1:
            errors.append("confidence outside [0, 1]")
        elif Decimal(str(confidence)) != decision.confidence:
            errors.append("confidence does not match verified decision")

        self._validate_limits(candidate, errors)
        expected_order_ids = [task.order.order_id][:MAX_ENTITY_IDS]
        expected_item_ids = [
            f"{task.order.order_id}:{item.item_id}"
            for item in task.order.items[:MAX_ENTITY_IDS]
        ]
        expected_seller_ids = list(task.order.seller_ids[:MAX_ENTITY_IDS])
        expected_payment_ids = [
            f"{task.order.order_id}:{row.sequential}"
            for row in task.payment.rows[:MAX_ENTITY_IDS]
        ]
        expected_entities = {
            "order_ids": expected_order_ids,
            "item_ids": expected_item_ids,
            "seller_ids": expected_seller_ids,
            "payment_ids": expected_payment_ids,
        }
        if entities != expected_entities:
            errors.append("affected entity IDs do not match source data")

        expected_causes = [{"cause_code": decision.cause_code, "rank": 1}]
        expected_parties = [
            {"party_type": party.party_type, "party_id": party.party_id}
            for party in decision.responsible_parties
        ]
        if analysis["ranked_causes"] != expected_causes:
            errors.append("root cause does not match policy decision")
        if analysis["responsible_parties"] != expected_parties:
            errors.append("responsible parties do not match policy decision")
        for cause in analysis["ranked_causes"]:
            if cause.get("cause_code") not in CAUSE_CODES:
                errors.append("invalid root cause enum")
        for party in analysis["responsible_parties"]:
            if party.get("party_type") not in PARTY_TYPES:
                errors.append("invalid responsible party type")
            if party.get("party_type") == "seller" and party.get(
                "party_id"
            ) not in self.repository.seller_ids:
                errors.append("responsible seller does not exist")

        expected_evidence = _build_evidence(
            task.order, task.payment, decision.cause_code
        )
        if candidate["evidence_ids"] != expected_evidence:
            errors.append("evidence IDs do not match reconstructable source evidence")

        expected_financial = {
            "currency": "BRL",
            "item_total_brl": float(money(task.order.item_total)),
            "freight_total_brl": float(money(task.order.freight_total)),
            "payment_total_brl": float(money(task.payment.payment_total)),
            "recommended_refund_brl": float(money(decision.recommended_refund)),
        }
        if financial != expected_financial:
            errors.append("financial resolution does not match source calculations")
        if candidate["resolution_actions"] != [decision.action]:
            errors.append("resolution action does not match policy decision")
        if decision.action not in RESOLUTION_ACTIONS:
            errors.append("invalid resolution action")

        return VerificationResult(not errors, tuple(errors))

    @staticmethod
    def _validate_shape(candidate: dict[str, Any], errors: list[str]) -> None:
        expected_top = {
            "case_id",
            "assessment",
            "affected_entities",
            "root_cause_analysis",
            "evidence_ids",
            "financial_resolution",
            "resolution_actions",
        }
        if not isinstance(candidate, dict) or set(candidate) != expected_top:
            errors.append("output top-level schema mismatch")
            return
        if not isinstance(candidate["case_id"], str):
            errors.append("case_id must be a string")
        nested = {
            "assessment": {"primary_issue", "case_status", "confidence"},
            "affected_entities": {
                "order_ids",
                "item_ids",
                "seller_ids",
                "payment_ids",
            },
            "root_cause_analysis": {"ranked_causes", "responsible_parties"},
            "financial_resolution": {
                "currency",
                "item_total_brl",
                "freight_total_brl",
                "payment_total_brl",
                "recommended_refund_brl",
            },
        }
        for key, expected in nested.items():
            if not isinstance(candidate.get(key), dict) or set(candidate[key]) != expected:
                errors.append(f"{key} schema mismatch")
        for key in ("evidence_ids", "resolution_actions"):
            if not isinstance(candidate.get(key), list):
                errors.append(f"{key} must be an array")
        if errors:
            return

        assessment = candidate["assessment"]
        if not isinstance(assessment["primary_issue"], str):
            errors.append("primary_issue must be a string")
        if not isinstance(assessment["case_status"], str):
            errors.append("case_status must be a string")
        if isinstance(assessment["confidence"], bool) or not isinstance(
            assessment["confidence"], (int, float)
        ):
            errors.append("confidence must be numeric")

        for key, values in candidate["affected_entities"].items():
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values
            ):
                errors.append(f"{key} must contain strings")

        analysis = candidate["root_cause_analysis"]
        if not isinstance(analysis["ranked_causes"], list) or not all(
            isinstance(cause, dict)
            and set(cause) == {"cause_code", "rank"}
            and isinstance(cause["cause_code"], str)
            and isinstance(cause["rank"], int)
            and not isinstance(cause["rank"], bool)
            for cause in analysis["ranked_causes"]
        ):
            errors.append("ranked_causes item schema mismatch")
        if not isinstance(analysis["responsible_parties"], list) or not all(
            isinstance(party, dict)
            and set(party) == {"party_type", "party_id"}
            and isinstance(party["party_type"], str)
            and isinstance(party["party_id"], str)
            for party in analysis["responsible_parties"]
        ):
            errors.append("responsible_parties item schema mismatch")

        if not all(isinstance(value, str) for value in candidate["evidence_ids"]):
            errors.append("evidence_ids must contain strings")
        financial = candidate["financial_resolution"]
        if not isinstance(financial["currency"], str):
            errors.append("currency must be a string")
        for key in (
            "item_total_brl",
            "freight_total_brl",
            "payment_total_brl",
            "recommended_refund_brl",
        ):
            if isinstance(financial[key], bool) or not isinstance(
                financial[key], (int, float)
            ):
                errors.append(f"{key} must be numeric")
        if not all(
            isinstance(value, str) for value in candidate["resolution_actions"]
        ):
            errors.append("resolution_actions must contain strings")

    @staticmethod
    def _validate_limits(candidate: dict[str, Any], errors: list[str]) -> None:
        for key, values in candidate["affected_entities"].items():
            if not isinstance(values, list) or len(values) > MAX_ENTITY_IDS:
                errors.append(f"{key} exceeds entity limit")
        if len(candidate["evidence_ids"]) > MAX_EVIDENCE_IDS:
            errors.append("evidence_ids exceeds limit")
        analysis = candidate["root_cause_analysis"]
        if len(analysis["ranked_causes"]) > MAX_ROOT_CAUSES:
            errors.append("ranked_causes exceeds limit")
        if len(analysis["responsible_parties"]) > MAX_RESPONSIBLE_PARTIES:
            errors.append("responsible_parties exceeds limit")
        if len(candidate["resolution_actions"]) > MAX_ACTIONS:
            errors.append("resolution_actions exceeds limit")


def _build_evidence(
    order: OrderSellerFinding, payment: PaymentFinding, cause_code: str
) -> list[str]:
    """Build stable evidence with mandatory order and policy references."""
    evidence = [f"order:{order.order_id}"]
    optional = [
        *(f"item:{order.order_id}:{item.item_id}" for item in order.items),
        *(f"payment:{order.order_id}:{row.sequential}" for row in payment.rows),
        *(f"seller:{seller_id}" for seller_id in order.seller_ids),
    ]
    evidence.extend(optional[: MAX_EVIDENCE_IDS - 2])
    evidence.append(f"policy:{cause_code}")
    return evidence
