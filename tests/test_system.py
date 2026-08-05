from __future__ import annotations

import json
import unittest
from collections import Counter
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from dispute_resolution.agents import (
    AgentError,
    DeliveryAgent,
    OrderSellerAgent,
    PaymentAgent,
    PolicyAgent,
)
from dispute_resolution.coordinator import CoordinatorAgent, build_metadata
from dispute_resolution.models import (
    CaseRequest,
    DeliveryFinding,
    DeliveryTask,
    ItemRecord,
    OrderRecord,
    OrderSellerFinding,
    OrderSellerTask,
    PaymentFinding,
    PaymentRecord,
    PaymentTask,
    PolicyTask,
    VerificationTask,
)
from dispute_resolution.repository import OlistRepository, load_cases


ROOT = Path(__file__).resolve().parents[1]
DATE = datetime(2018, 1, 10, 12, 0, 0)


class StubRepository:
    def __init__(self, order: OrderRecord, items=(), payments=()) -> None:
        self._order = order
        self._items = tuple(items)
        self._payments = tuple(payments)

    def order(self, order_id: str) -> OrderRecord:
        return self._order

    def order_items(self, order_id: str):
        return self._items

    def order_payments(self, order_id: str):
        return self._payments


def case(policy: str = "EC_POLICY_V1") -> CaseRequest:
    return CaseRequest("EC_TEST", "2018-01-01", "order-1", policy)


def order_finding(status: str = "delivered") -> OrderSellerFinding:
    return OrderSellerFinding(
        order_id="order-1",
        customer_id="customer-1",
        order_status=status,
        carrier_date=DATE,
        delivered_date=DATE,
        estimated_date=DATE,
        items=(),
        seller_ids=(),
        item_total=Decimal("90.00"),
        freight_total=Decimal("10.00"),
    )


def payment_finding(total: str = "100.00", split: bool = False) -> PaymentFinding:
    row_count = 2 if split else 1
    rows = tuple(
        PaymentRecord("order-1", index, "credit_card", 1, Decimal(total) / row_count)
        for index in range(1, row_count + 1)
    )
    return PaymentFinding(
        "order-1",
        rows,
        Decimal(total),
        Decimal("100.00"),
        True,
        split,
    )


def delivery(late=False, handoff=False, sellers=()) -> DeliveryFinding:
    return DeliveryFinding(
        "order-1", late, handoff, tuple(sellers), DATE, DATE, DATE
    )


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = PolicyAgent()

    def decide(self, status="delivered", payment=None, delivery_result=None):
        return self.agent.handle(
            PolicyTask(
                case(),
                order_finding(status),
                payment or payment_finding(),
                delivery_result or delivery(False, False),
            )
        )

    def test_all_six_policy_branches(self) -> None:
        scenarios = [
            ("canceled", payment_finding(), delivery(False, False), "canceled_order_paid"),
            ("unavailable", payment_finding(), delivery(False, False), "unavailable_order_paid"),
            ("delivered", payment_finding(), delivery(True, True, ("seller-1",)), "late_delivery_seller"),
            ("delivered", payment_finding(), delivery(True, False), "late_delivery_logistics"),
            ("delivered", payment_finding(split=True), delivery(False, False), "valid_split_payment"),
            ("delivered", payment_finding(), delivery(False, False), "unsupported_late_claim"),
        ]
        for status, paid, delivered, expected in scenarios:
            with self.subTest(expected=expected):
                self.assertEqual(
                    self.decide(status, paid, delivered).primary_issue, expected
                )

    def test_canceled_rule_has_priority_over_late_and_split(self) -> None:
        decision = self.decide(
            "canceled",
            payment_finding(split=True),
            delivery(True, True, ("seller-1",)),
        )
        self.assertEqual(decision.primary_issue, "canceled_order_paid")
        self.assertEqual(decision.recommended_refund, Decimal("100.00"))

    def test_unknown_policy_is_rejected(self) -> None:
        with self.assertRaises(AgentError):
            self.agent.handle(
                PolicyTask(
                    case("UNKNOWN"),
                    order_finding(),
                    payment_finding(),
                    delivery(False, False),
                )
            )


class DomainAgentTests(unittest.TestCase):
    def test_date_equalities_are_not_late(self) -> None:
        source_order = OrderRecord(
            "order-1", "customer-1", "delivered", DATE, DATE, DATE
        )
        item = ItemRecord(
            "order-1",
            1,
            "product-1",
            "seller-1",
            DATE,
            Decimal("90.00"),
            Decimal("10.00"),
        )
        finding = OrderSellerAgent(StubRepository(source_order, (item,))).handle(
            OrderSellerTask("EC_TEST", "order-1")
        )
        delivered = DeliveryAgent().handle(DeliveryTask("EC_TEST", finding))
        self.assertFalse(finding.items[0].handoff_late)
        self.assertFalse(delivered.delivered_late)
        self.assertFalse(delivered.seller_handoff_late)

    def test_missing_dates_remain_unknown(self) -> None:
        source_order = OrderRecord(
            "order-1", "customer-1", "delivered", None, None, DATE
        )
        finding = OrderSellerAgent(StubRepository(source_order)).handle(
            OrderSellerTask("EC_TEST", "order-1")
        )
        delivered = DeliveryAgent().handle(DeliveryTask("EC_TEST", finding))
        self.assertIsNone(delivered.delivered_late)
        self.assertIsNone(delivered.seller_handoff_late)

    def test_payment_tolerance_is_inclusive(self) -> None:
        source_order = OrderRecord(
            "order-1", "customer-1", "delivered", DATE, DATE, DATE
        )
        at_limit = PaymentRecord(
            "order-1", 1, "credit_card", 1, Decimal("100.10")
        )
        above_limit = replace(at_limit, value=Decimal("100.11"))
        task = PaymentTask(
            "EC_TEST", "order-1", Decimal("90.00"), Decimal("10.00")
        )
        self.assertTrue(
            PaymentAgent(StubRepository(source_order, payments=(at_limit,)))
            .handle(task)
            .reconciled
        )
        self.assertFalse(
            PaymentAgent(StubRepository(source_order, payments=(above_limit,)))
            .handle(task)
            .reconciled
        )


class FullDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases(ROOT / "input")
        cls.repository = OlistRepository(
            ROOT / "data", (item.claimed_order_id for item in cls.cases)
        )
        cls.coordinator = CoordinatorAgent(cls.repository)
        cls.outputs = {
            item.case_id: cls.coordinator.process(item) for item in cls.cases
        }

    def test_all_cases_and_expected_distribution(self) -> None:
        self.assertEqual(len(self.outputs), 50)
        counts = Counter(
            output["assessment"]["primary_issue"]
            for output in self.outputs.values()
        )
        self.assertEqual(
            counts,
            Counter(
                {
                    "canceled_order_paid": 8,
                    "unavailable_order_paid": 8,
                    "late_delivery_seller": 8,
                    "late_delivery_logistics": 8,
                    "valid_split_payment": 9,
                    "unsupported_late_claim": 9,
                }
            ),
        )
        self.assertEqual(len(self.coordinator.events), 500)

    def test_verifier_rejects_fake_evidence_and_bad_refund(self) -> None:
        target = self.cases[0]
        clean = self.outputs[target.case_id]
        order = self.coordinator.order_seller.handle(
            OrderSellerTask(target.case_id, target.claimed_order_id)
        )
        paid = self.coordinator.payment.handle(
            PaymentTask(
                target.case_id,
                target.claimed_order_id,
                order.item_total,
                order.freight_total,
            )
        )
        delivered = self.coordinator.delivery.handle(DeliveryTask(target.case_id, order))
        decision = self.coordinator.policy.handle(
            PolicyTask(target, order, paid, delivered)
        )
        tampered = json.loads(json.dumps(clean))
        tampered["evidence_ids"][0] = "order:not-real"
        tampered["financial_resolution"]["recommended_refund_brl"] = 999.0
        result = self.coordinator.verifier.handle(
            VerificationTask(target, tampered, order, paid, delivered, decision)
        )
        self.assertFalse(result.valid)
        self.assertGreaterEqual(len(result.errors), 2)

    def test_verifier_rejects_invalid_enum_and_array_limit(self) -> None:
        target = self.cases[0]
        order = self.coordinator.order_seller.handle(
            OrderSellerTask(target.case_id, target.claimed_order_id)
        )
        paid = self.coordinator.payment.handle(
            PaymentTask(
                target.case_id,
                target.claimed_order_id,
                order.item_total,
                order.freight_total,
            )
        )
        delivered = self.coordinator.delivery.handle(DeliveryTask(target.case_id, order))
        decision = self.coordinator.policy.handle(
            PolicyTask(target, order, paid, delivered)
        )
        tampered = json.loads(json.dumps(self.outputs[target.case_id]))
        tampered["assessment"]["primary_issue"] = "invented_issue"
        tampered["affected_entities"]["order_ids"] = [target.claimed_order_id] * 6
        result = self.coordinator.verifier.handle(
            VerificationTask(target, tampered, order, paid, delivered, decision)
        )
        self.assertFalse(result.valid)
        self.assertTrue(any("primary_issue" in error for error in result.errors))
        self.assertTrue(any("limit" in error for error in result.errors))

    def test_model_metadata_is_truthful(self) -> None:
        metadata = build_metadata()
        self.assertEqual(metadata["model_name"], "Llama 3.1 8B Instruct")
        self.assertEqual(metadata["model_parameter_size_billion"], 8)
        self.assertEqual(metadata["model_provider"], "Groq")
        self.assertFalse(metadata["model_invocation_enabled"])
        self.assertEqual(metadata["execution_engine"], "deterministic_python")


if __name__ == "__main__":
    unittest.main()
