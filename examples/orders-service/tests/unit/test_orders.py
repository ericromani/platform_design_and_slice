"""Domain logic. Add a case here for every new validation rule."""

import pytest

from app.orders import InvalidOrder, build_order_record
from tests.conftest import order_message


def test_computes_totals():
    record = build_order_record(order_message(), processed_by="v1")
    assert record["orderId"] == "o-1"
    assert record["itemCount"] == 3
    assert record["totalCents"] == 2 * 450 + 300
    assert record["status"] == "RECEIVED"
    assert record["processedBy"] == "v1"


@pytest.mark.parametrize(
    "bad",
    [
        {"customerId": "c-1", "items": [{"quantity": 1, "unitPriceCents": 1}]},
        order_message(items=[]),
        order_message(items=[{"sku": "X", "quantity": 0, "unitPriceCents": 1}]),
        order_message(items=[{"sku": "X", "quantity": "lots", "unitPriceCents": 1}]),
        order_message(orderId="  "),
    ],
)
def test_rejects_malformed_orders(bad):
    with pytest.raises(InvalidOrder):
        build_order_record(bad, processed_by="v1")
