"""Pure domain logic: turn an order message into the DynamoDB record. No AWS here, so
it is trivially unit-testable."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


class InvalidOrder(ValueError):
    """The message is not a well-formed order; it will not succeed on retry."""


def build_order_record(message: dict[str, Any], processed_by: str) -> dict[str, Any]:
    """Validate an order message and compute the record to store.

    Expected message shape:
      {"orderId": "o-1", "customerId": "c-1",
       "items": [{"sku": "ABC", "quantity": 2, "unitPriceCents": 1250}]}
    """
    try:
        order_id = str(message["orderId"]).strip()
        customer_id = str(message["customerId"]).strip()
        items = message["items"]
    except (KeyError, TypeError) as exc:
        raise InvalidOrder(f"missing field: {exc}") from exc

    if not order_id or not customer_id:
        raise InvalidOrder("orderId and customerId must be non-empty")
    if not isinstance(items, list) or not items:
        raise InvalidOrder("items must be a non-empty list")

    total_cents = 0
    item_count = 0
    for item in items:
        try:
            quantity = int(item["quantity"])
            unit_price = int(item["unitPriceCents"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidOrder(f"bad item {item!r}: {exc}") from exc
        if quantity <= 0 or unit_price < 0:
            raise InvalidOrder(f"bad item {item!r}: quantity must be > 0, price >= 0")
        item_count += quantity
        total_cents += quantity * unit_price

    return {
        "orderId": order_id,
        "customerId": customer_id,
        "itemCount": Decimal(item_count),
        "totalCents": Decimal(total_cents),
        "status": "RECEIVED",
        "processedAt": datetime.now(timezone.utc).isoformat(),
        "processedBy": processed_by,
    }
