import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        service="orders-service",
        environment="test",
        version="test-sha",
        queue_name="orders-service-orders",
        table_name="orders-service-orders",
        fail_rate=0.0,
        poll_wait_seconds=0,
        max_messages=10,
    )


def order_message(order_id: str = "o-1", **overrides) -> dict:
    body = {
        "orderId": order_id,
        "customerId": "c-1",
        "items": [
            {"sku": "TEA", "quantity": 2, "unitPriceCents": 450},
            {"sku": "CAKE", "quantity": 1, "unitPriceCents": 300},
        ],
    }
    body.update(overrides)
    return body
