"""Coordinator orchestration, output assembly, tracing, and publication."""

from __future__ import annotations

import json
import platform
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, TypeVar

from .agents import (
    AgentError,
    DeliveryAgent,
    OrderSellerAgent,
    PaymentAgent,
    PolicyAgent,
    VerifierAgent,
    _build_evidence,
    money,
)
from .constants import (
    EXECUTION_ENGINE,
    MAX_ENTITY_IDS,
    MODEL_INVOCATION_ENABLED,
    MODEL_NAME,
    MODEL_PARAMETER_SIZE_BILLION,
    MODEL_PROVIDER,
)
from .models import (
    CaseRequest,
    DeliveryTask,
    OrderSellerTask,
    PaymentTask,
    PolicyTask,
    TraceEvent,
    VerificationTask,
    structured_payload,
)
from .repository import OlistRepository

T = TypeVar("T")


class CoordinatorAgent:
    name = "CoordinatorAgent"

    def __init__(self, repository: OlistRepository) -> None:
        self.order_seller = OrderSellerAgent(repository)
        self.payment = PaymentAgent(repository)
        self.delivery = DeliveryAgent()
        self.policy = PolicyAgent()
        self.verifier = VerifierAgent(repository)
        self.events: list[TraceEvent] = []

    def _call(
        self,
        case_id: str,
        receiver: str,
        task: Any,
        handler: Callable[[Any], T],
    ) -> T:
        self._trace(case_id, self.name, receiver, type(task).__name__, task)
        result = handler(task)
        self._trace(case_id, receiver, self.name, type(result).__name__, result)
        return result

    def _trace(
        self,
        case_id: str,
        sender: str,
        receiver: str,
        message_type: str,
        payload: Any,
    ) -> None:
        self.events.append(
            TraceEvent(
                sequence=len(self.events) + 1,
                case_id=case_id,
                sender=sender,
                receiver=receiver,
                message_type=message_type,
                payload=structured_payload(payload),
            )
        )

    def process(self, case: CaseRequest) -> dict[str, Any]:
        order = self._call(
            case.case_id,
            self.order_seller.name,
            OrderSellerTask(case.case_id, case.claimed_order_id),
            self.order_seller.handle,
        )
        payment = self._call(
            case.case_id,
            self.payment.name,
            PaymentTask(
                case.case_id,
                case.claimed_order_id,
                order.item_total,
                order.freight_total,
            ),
            self.payment.handle,
        )
        delivery = self._call(
            case.case_id,
            self.delivery.name,
            DeliveryTask(case.case_id, order),
            self.delivery.handle,
        )
        decision = self._call(
            case.case_id,
            self.policy.name,
            PolicyTask(case, order, payment, delivery),
            self.policy.handle,
        )
        candidate = self._assemble(case, order, payment, decision)
        verification = self._call(
            case.case_id,
            self.verifier.name,
            VerificationTask(case, candidate, order, payment, delivery, decision),
            self.verifier.handle,
        )
        if not verification.valid:
            raise AgentError(
                f"verification failed for {case.case_id}: "
                + "; ".join(verification.errors)
            )
        return candidate

    @staticmethod
    def _assemble(case, order, payment, decision) -> dict[str, Any]:
        return {
            "case_id": case.case_id,
            "assessment": {
                "primary_issue": decision.primary_issue,
                "case_status": decision.case_status,
                "confidence": float(decision.confidence),
            },
            "affected_entities": {
                "order_ids": [order.order_id][:MAX_ENTITY_IDS],
                "item_ids": [
                    f"{order.order_id}:{item.item_id}"
                    for item in order.items[:MAX_ENTITY_IDS]
                ],
                "seller_ids": list(order.seller_ids[:MAX_ENTITY_IDS]),
                "payment_ids": [
                    f"{order.order_id}:{row.sequential}"
                    for row in payment.rows[:MAX_ENTITY_IDS]
                ],
            },
            "root_cause_analysis": {
                "ranked_causes": [
                    {"cause_code": decision.cause_code, "rank": 1}
                ],
                "responsible_parties": [
                    {"party_type": party.party_type, "party_id": party.party_id}
                    for party in decision.responsible_parties
                ],
            },
            "evidence_ids": _build_evidence(order, payment, decision),
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": float(money(order.item_total)),
                "freight_total_brl": float(money(order.freight_total)),
                "payment_total_brl": float(money(payment.payment_total)),
                "recommended_refund_brl": float(
                    money(decision.recommended_refund)
                ),
            },
            "resolution_actions": [decision.action],
        }


def publish_run(
    outputs: dict[str, dict[str, Any]],
    events: list[TraceEvent],
    output_dir: Path,
    logging_dir: Path,
) -> None:
    """Publish a completely verified run using atomic per-file replacement."""
    output_dir.mkdir(parents=True, exist_ok=True)
    logging_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {f"{case_id}.json" for case_id in outputs}
    extras = [
        path.name
        for path in output_dir.iterdir()
        if path.is_file() and path.name not in expected_names and path.name != ".gitkeep"
    ]
    if extras:
        raise AgentError(f"unexpected files in output directory: {', '.join(extras)}")
    for stale in output_dir.glob("EC_*.json"):
        stale.unlink()
    gitkeep = output_dir / ".gitkeep"
    if gitkeep.exists():
        gitkeep.unlink()

    for case_id, output in sorted(outputs.items()):
        _atomic_json(output_dir / f"{case_id}.json", output)

    trace_text = "".join(
        json.dumps(structured_payload(asdict(event)), ensure_ascii=False, separators=(",", ":"))
        + "\n"
        for event in events
    )
    _atomic_text(logging_dir / "trace.jsonl", trace_text)
    _atomic_json(
        logging_dir / "metadata.json",
        build_metadata(
            processed_cases=len(outputs),
            trace_events=len(events),
            issue_counts=Counter(
                output["assessment"]["primary_issue"] for output in outputs.values()
            ),
        ),
    )


def build_metadata(
    processed_cases: int | None = None,
    trace_events: int | None = None,
    issue_counts: Counter[str] | None = None,
) -> dict[str, Any]:
    agents = [
        "CoordinatorAgent",
        "OrderSellerAgent",
        "PaymentAgent",
        "DeliveryAgent",
        "PolicyAgent",
        "VerifierAgent",
    ]
    return {
        "model_name": MODEL_NAME,
        "model_parameter_size_billion": MODEL_PARAMETER_SIZE_BILLION,
        "model_provider": MODEL_PROVIDER,
        "model_invocation_enabled": MODEL_INVOCATION_ENABLED,
        "model_role": "compatible_reference_model",
        "execution_engine": EXECUTION_ENGINE,
        "framework": "Python standard library dataclasses",
        "runtime": f"Python {platform.python_version()}",
        "processed_cases": processed_cases,
        "trace_events": trace_events,
        "issue_counts": dict(sorted(issue_counts.items())) if issue_counts else None,
        "agents": [
            {"name": name, "implementation": "deterministic_python_component"}
            for name in agents
        ],
    }


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
    )


def _atomic_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)
