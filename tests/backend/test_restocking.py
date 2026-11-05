"""
Tests for the restocking order endpoints.
"""


class TestCreateRestockingOrder:
    def test_creates_order_with_server_side_totals(self, client):
        response = client.post("/api/restocking-orders", json={
            "items": [
                {"sku": "WDG-001", "quantity": 10},   # 42.5 each, 14 day lead time
                {"sku": "FLT-405", "quantity": 100},  # 9.8 each, 5 day lead time
            ]
        })

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "Submitted"
        assert data["order_number"].startswith("RST-")
        assert data["total_cost"] == 425.0 + 980.0
        # Order lead time is the slowest item
        assert data["lead_time_days"] == 14
        assert len(data["items"]) == 2
        assert data["items"][0]["line_total"] == 425.0

    def test_expected_delivery_follows_lead_time(self, client):
        data = client.post("/api/restocking-orders", json={
            "items": [{"sku": "GSK-203", "quantity": 5}]
        }).json()

        assert data["lead_time_days"] == 7
        assert data["expected_delivery"] > data["submitted_date"]

    def test_rejects_empty_items(self, client):
        response = client.post("/api/restocking-orders", json={"items": []})
        assert response.status_code == 400

    def test_rejects_unknown_sku(self, client):
        response = client.post("/api/restocking-orders", json={
            "items": [{"sku": "NOPE-000", "quantity": 1}]
        })
        assert response.status_code == 400

    def test_rejects_non_positive_quantity(self, client):
        # Bounds are enforced by Pydantic, so these are 422 validation errors
        for quantity in (0, -3):
            response = client.post("/api/restocking-orders", json={
                "items": [{"sku": "WDG-001", "quantity": quantity}]
            })
            assert response.status_code == 422

    def test_rejects_quantity_above_max(self, client):
        response = client.post("/api/restocking-orders", json={
            "items": [{"sku": "WDG-001", "quantity": 100001}]
        })
        assert response.status_code == 422

    def test_huge_quantity_is_validation_error_not_500(self, client):
        # Content is sent as raw text because 10**400 overflows float on the cost multiply
        response = client.post(
            "/api/restocking-orders",
            content='{"items":[{"sku":"WDG-001","quantity":1' + "0" * 400 + '}]}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_accepts_max_quantity(self, client):
        response = client.post("/api/restocking-orders", json={
            "items": [{"sku": "GSK-203", "quantity": 100000}]
        })
        assert response.status_code == 201
        assert response.json()["total_cost"] == 620000.0

    def test_rejects_duplicate_sku(self, client):
        response = client.post("/api/restocking-orders", json={
            "items": [
                {"sku": "WDG-001", "quantity": 1},
                {"sku": "WDG-001", "quantity": 2},
            ]
        })
        assert response.status_code == 400
        assert "Duplicate" in response.json()["detail"]

    def test_rejects_item_without_lead_time(self, client, monkeypatch):
        import mock_data
        patched = [dict(f, lead_time_days=None) if f["item_sku"] == "WDG-001" else f
                   for f in mock_data.demand_forecasts]
        monkeypatch.setattr("main.demand_forecasts", patched)

        response = client.post("/api/restocking-orders", json={
            "items": [{"sku": "WDG-001", "quantity": 1}]
        })
        assert response.status_code == 400

    def test_concurrent_orders_get_unique_ids(self, client):
        from concurrent.futures import ThreadPoolExecutor

        def place(_):
            return client.post("/api/restocking-orders", json={
                "items": [{"sku": "GSK-203", "quantity": 1}]
            }).json()

        with ThreadPoolExecutor(max_workers=8) as pool:
            orders = list(pool.map(place, range(24)))

        assert len({o["id"] for o in orders}) == 24
        assert len({o["order_number"] for o in orders}) == 24

    def test_rejects_malformed_body(self, client):
        response = client.post("/api/restocking-orders", json={"items": [{"sku": "WDG-001"}]})
        assert response.status_code == 422


class TestGetRestockingOrders:
    def test_empty_by_default(self, client):
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_lists_newest_first(self, client):
        client.post("/api/restocking-orders", json={"items": [{"sku": "WDG-001", "quantity": 1}]})
        client.post("/api/restocking-orders", json={"items": [{"sku": "GSK-203", "quantity": 1}]})

        orders = client.get("/api/restocking-orders").json()
        assert len(orders) == 2
        assert orders[0]["items"][0]["sku"] == "GSK-203"
        assert orders[1]["items"][0]["sku"] == "WDG-001"


class TestDemandRestockingFields:
    def test_demand_includes_cost_and_lead_time(self, client):
        forecasts = client.get("/api/demand").json()
        for forecast in forecasts:
            assert forecast["unit_cost"] > 0
            assert forecast["lead_time_days"] > 0
            assert forecast["supplier"]
