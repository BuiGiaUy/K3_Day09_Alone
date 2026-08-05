from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dispute_resolution.coordinator import CoordinatorAgent
from dispute_resolution.models import DeliveryTask, OrderSellerTask, PaymentTask, PolicyTask
from dispute_resolution.repository import OlistRepository, load_cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a case-level audit matrix.")
    parser.add_argument("--input-dir", type=Path, default=Path("input"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("case_audit.csv"))
    args = parser.parse_args()

    cases = load_cases(args.input_dir)
    repository = OlistRepository(args.data_dir, (case.claimed_order_id for case in cases))
    coordinator = CoordinatorAgent(repository)

    rows = []
    for case in cases:
        order = coordinator.order_seller.handle(
            OrderSellerTask(case.case_id, case.claimed_order_id)
        )
        payment = coordinator.payment.handle(
            PaymentTask(case.case_id, case.claimed_order_id, order.item_total, order.freight_total)
        )
        delivery = coordinator.delivery.handle(DeliveryTask(case.case_id, order))
        decision = coordinator.policy.handle(PolicyTask(case, order, payment, delivery))
        candidate = coordinator.process(case)
        rows.append(
            {
                "case_id": case.case_id,
                "order_id": case.claimed_order_id,
                "primary_issue": decision.primary_issue,
                "case_status": decision.case_status,
                "order_status": order.order_status,
                "item_count": len(order.items),
                "payment_count": len(payment.rows),
                "delivered_late": delivery.delivered_late,
                "seller_handoff_late": delivery.seller_handoff_late,
                "violating_seller_ids": "|".join(delivery.violating_seller_ids),
                "item_total_brl": str(order.item_total),
                "freight_total_brl": str(order.freight_total),
                "payment_total_brl": str(payment.payment_total),
                "expected_total_brl": str(payment.expected_total),
                "payment_reconciled": payment.reconciled,
                "recommended_refund_brl": str(decision.recommended_refund),
                "responsible_parties": json.dumps(
                    candidate["root_cause_analysis"]["responsible_parties"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "affected_entities": json.dumps(
                    candidate["affected_entities"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "evidence_ids": json.dumps(
                    candidate["evidence_ids"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "resolution_actions": json.dumps(
                    candidate["resolution_actions"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
        )

    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
