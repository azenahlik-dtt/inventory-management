"""
Tests for reports API endpoints (quarterly and monthly trends).
"""
import pytest


class TestReportsEndpoints:
    """Test suite for report endpoints and their global filter support."""

    def test_get_quarterly_reports(self, client):
        """Test getting quarterly reports."""
        response = client.get("/api/reports/quarterly")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        for quarter in data:
            assert "quarter" in quarter
            assert "total_orders" in quarter
            assert "total_revenue" in quarter
            assert "avg_order_value" in quarter
            assert "fulfillment_rate" in quarter
            assert 0 <= quarter["fulfillment_rate"] <= 100

    def test_quarterly_reports_sorted(self, client):
        """Test that quarters are returned in chronological order."""
        data = client.get("/api/reports/quarterly").json()
        quarters = [q["quarter"] for q in data]
        assert quarters == sorted(quarters)

    def test_get_monthly_trends(self, client):
        """Test getting monthly trends."""
        response = client.get("/api/reports/monthly-trends")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        for month in data:
            assert "month" in month
            assert "order_count" in month
            assert "revenue" in month
            assert len(month["month"]) == 7  # YYYY-MM

        months = [m["month"] for m in data]
        assert months == sorted(months)

    def test_reports_totals_match_orders(self, client):
        """Test that report totals agree with the raw orders."""
        orders = client.get("/api/orders").json()
        quarterly = client.get("/api/reports/quarterly").json()
        monthly = client.get("/api/reports/monthly-trends").json()

        assert sum(q["total_orders"] for q in quarterly) == len(orders)
        assert sum(m["order_count"] for m in monthly) == len(orders)
        expected_revenue = sum(o["total_value"] for o in orders)
        assert abs(sum(m["revenue"] for m in monthly) - expected_revenue) < 1

    def test_reports_by_warehouse(self, client):
        """Test that the warehouse filter narrows both reports."""
        orders = client.get("/api/orders?warehouse=Tokyo").json()
        assert 0 < len(orders) < len(client.get("/api/orders").json())

        monthly = client.get("/api/reports/monthly-trends?warehouse=Tokyo").json()
        quarterly = client.get("/api/reports/quarterly?warehouse=Tokyo").json()

        assert sum(m["order_count"] for m in monthly) == len(orders)
        assert sum(q["total_orders"] for q in quarterly) == len(orders)

    def test_reports_by_status(self, client):
        """Test that the status filter is applied to both reports."""
        orders = client.get("/api/orders?status=Delivered").json()
        quarterly = client.get("/api/reports/quarterly?status=Delivered").json()

        assert sum(q["total_orders"] for q in quarterly) == len(orders)
        # Every remaining order is delivered, so fulfillment must be 100%
        for quarter in quarterly:
            assert quarter["fulfillment_rate"] == 100

    def test_reports_by_category(self, client):
        """Test that the category filter is applied to both reports."""
        orders = client.get("/api/orders?category=Sensors").json()
        monthly = client.get("/api/reports/monthly-trends?category=Sensors").json()

        assert sum(m["order_count"] for m in monthly) == len(orders)

    def test_reports_by_month(self, client):
        """Test that the month filter limits the reports to that month."""
        monthly = client.get("/api/reports/monthly-trends?month=2025-01").json()
        assert len(monthly) == 1
        assert monthly[0]["month"] == "2025-01"

        quarterly = client.get("/api/reports/quarterly?month=2025-01").json()
        assert [q["quarter"] for q in quarterly] == ["Q1-2025"]

    def test_reports_by_quarter(self, client):
        """Test that a quarter filter limits the reports to that quarter."""
        monthly = client.get("/api/reports/monthly-trends?month=Q2-2025").json()
        assert {m["month"] for m in monthly} <= {"2025-04", "2025-05", "2025-06"}

    def test_reports_all_filters_ignored(self, client):
        """Test that 'all' behaves like no filter."""
        base = client.get("/api/reports/quarterly").json()
        filtered = client.get(
            "/api/reports/quarterly?warehouse=all&category=all&status=all&month=all"
        ).json()
        assert base == filtered

    def test_reports_no_matches(self, client):
        """Test that filters with no matching orders return empty lists, not errors."""
        response = client.get("/api/reports/quarterly?category=Nonexistent")
        assert response.status_code == 200
        assert response.json() == []

        response = client.get("/api/reports/monthly-trends?category=Nonexistent")
        assert response.status_code == 200
        assert response.json() == []
