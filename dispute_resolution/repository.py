"""Read-only, indexed access to the Olist CSV dataset and case inputs."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from .constants import POLICY_VERSION
from .models import CaseRequest, ItemRecord, OrderRecord, PaymentRecord


class DataError(RuntimeError):
    """Raised when required input or source data is missing or malformed."""


def _parse_datetime(value: str, field: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise DataError(f"invalid {field} timestamp: {value!r}") from exc


def _decimal(value: str, field: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise DataError(f"invalid {field} amount: {value!r}") from exc


class OlistRepository:
    """Indexes only records related to the requested orders."""

    def __init__(self, data_dir: Path, order_ids: Iterable[str]) -> None:
        self.data_dir = data_dir
        requested = set(order_ids)
        self.orders: dict[str, OrderRecord] = {}
        self.items: dict[str, tuple[ItemRecord, ...]] = {}
        self.payments: dict[str, tuple[PaymentRecord, ...]] = {}
        self.customer_ids: set[str] = set()
        self.seller_ids: set[str] = set()
        self.product_ids: set[str] = set()
        self._load(requested)

    def _csv_rows(self, filename: str):
        path = self.data_dir / filename
        if not path.is_file():
            raise DataError(f"missing dataset file: {path}")
        with path.open("r", encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle)

    def _load(self, requested: set[str]) -> None:
        for row in self._csv_rows("olist_orders_dataset.csv"):
            if row["order_id"] not in requested:
                continue
            order = OrderRecord(
                order_id=row["order_id"],
                customer_id=row["customer_id"],
                order_status=row["order_status"],
                carrier_date=_parse_datetime(
                    row["order_delivered_carrier_date"], "carrier"
                ),
                delivered_date=_parse_datetime(
                    row["order_delivered_customer_date"], "delivered"
                ),
                estimated_date=_parse_datetime(
                    row["order_estimated_delivery_date"], "estimated"
                ),
            )
            if order.order_id in self.orders:
                raise DataError(f"duplicate order row: {order.order_id}")
            self.orders[order.order_id] = order

        missing = sorted(requested - self.orders.keys())
        if missing:
            raise DataError(f"claimed orders not found: {', '.join(missing)}")

        raw_items: dict[str, list[ItemRecord]] = defaultdict(list)
        for row in self._csv_rows("olist_order_items_dataset.csv"):
            if row["order_id"] not in requested:
                continue
            limit = _parse_datetime(row["shipping_limit_date"], "shipping limit")
            if limit is None:
                raise DataError(
                    f"missing shipping limit for {row['order_id']}:{row['order_item_id']}"
                )
            raw_items[row["order_id"]].append(
                ItemRecord(
                    order_id=row["order_id"],
                    item_id=int(row["order_item_id"]),
                    product_id=row["product_id"],
                    seller_id=row["seller_id"],
                    shipping_limit_date=limit,
                    price=_decimal(row["price"], "price"),
                    freight=_decimal(row["freight_value"], "freight"),
                )
            )
        self.items = {
            order_id: tuple(sorted(rows, key=lambda item: item.item_id))
            for order_id, rows in raw_items.items()
        }

        raw_payments: dict[str, list[PaymentRecord]] = defaultdict(list)
        for row in self._csv_rows("olist_order_payments_dataset.csv"):
            if row["order_id"] not in requested:
                continue
            raw_payments[row["order_id"]].append(
                PaymentRecord(
                    order_id=row["order_id"],
                    sequential=int(row["payment_sequential"]),
                    payment_type=row["payment_type"],
                    installments=int(row["payment_installments"]),
                    value=_decimal(row["payment_value"], "payment"),
                )
            )
        self.payments = {
            order_id: tuple(sorted(rows, key=lambda payment: payment.sequential))
            for order_id, rows in raw_payments.items()
        }

        related_customers = {order.customer_id for order in self.orders.values()}
        related_sellers = {
            item.seller_id for rows in self.items.values() for item in rows
        }
        related_products = {
            item.product_id for rows in self.items.values() for item in rows
        }
        self.customer_ids = self._load_id_set(
            "olist_customers_dataset.csv", "customer_id", related_customers
        )
        self.seller_ids = self._load_id_set(
            "olist_sellers_dataset.csv", "seller_id", related_sellers
        )
        self.product_ids = self._load_id_set(
            "olist_products_dataset.csv", "product_id", related_products
        )
        self._require_related("customer", related_customers, self.customer_ids)
        self._require_related("seller", related_sellers, self.seller_ids)
        self._require_related("product", related_products, self.product_ids)

    def _load_id_set(self, filename: str, key: str, wanted: set[str]) -> set[str]:
        return {row[key] for row in self._csv_rows(filename) if row[key] in wanted}

    @staticmethod
    def _require_related(kind: str, wanted: set[str], found: set[str]) -> None:
        missing = sorted(wanted - found)
        if missing:
            raise DataError(f"missing related {kind} records: {', '.join(missing)}")

    def order(self, order_id: str) -> OrderRecord:
        try:
            return self.orders[order_id]
        except KeyError as exc:
            raise DataError(f"order not indexed: {order_id}") from exc

    def order_items(self, order_id: str) -> tuple[ItemRecord, ...]:
        return self.items.get(order_id, ())

    def order_payments(self, order_id: str) -> tuple[PaymentRecord, ...]:
        return self.payments.get(order_id, ())


def load_cases(input_dir: Path) -> tuple[CaseRequest, ...]:
    paths = sorted(input_dir.glob("EC_*.json"))
    if not paths:
        raise DataError(f"no EC input files found in {input_dir}")
    cases: list[CaseRequest] = []
    seen_cases: set[str] = set()
    seen_orders: set[str] = set()
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            customer_request = data["customer_request"]
            case = CaseRequest(
                case_id=data["case_id"],
                opened_at=data["opened_at"],
                claimed_order_id=customer_request["claimed_order_id"],
                policy_version=data["policy_version"],
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise DataError(f"malformed input: {path}") from exc
        if path.stem != case.case_id:
            raise DataError(f"case ID does not match filename: {path}")
        if case.policy_version != POLICY_VERSION:
            raise DataError(
                f"unsupported policy {case.policy_version!r} in {case.case_id}"
            )
        if case.case_id in seen_cases:
            raise DataError(f"duplicate case ID: {case.case_id}")
        if case.claimed_order_id in seen_orders:
            raise DataError(f"duplicate claimed order: {case.claimed_order_id}")
        seen_cases.add(case.case_id)
        seen_orders.add(case.claimed_order_id)
        cases.append(case)
    return tuple(cases)
