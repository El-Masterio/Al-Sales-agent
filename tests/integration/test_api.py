"""
tests/integration/test_api.py
=============================
Integration tests exercising API endpoints end-to-end against a real
(test) database. The LLM is mocked; everything else is real.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]


class TestAuthFlow:
    async def test_register_and_login(self, client):
        register_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "full_name": "New User",
                "password": "password123",
                "role": "sales_rep",
            },
        )
        assert register_resp.status_code == 201
        assert register_resp.json()["email"] == "newuser@example.com"

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "newuser@example.com", "password": "password123"},
        )
        assert login_resp.status_code == 200
        body = login_resp.json()
        assert "access_token" in body
        assert "refresh_token" in body

    async def test_login_wrong_password(self, client, test_user):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    async def test_me_endpoint(self, client, auth_headers):
        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert "email" in resp.json()

    async def test_me_without_auth(self, client):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 403  # HTTPBearer auto_error


class TestCompaniesAPI:
    async def test_create_and_get_company(self, client, auth_headers):
        create_resp = await client.post(
            "/api/v1/companies",
            headers=auth_headers,
            json={"name": "Acme Corp", "website": "https://acme.example.com", "industry": "SaaS"},
        )
        assert create_resp.status_code == 201
        company_id = create_resp.json()["id"]

        get_resp = await client.get(f"/api/v1/companies/{company_id}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Acme Corp"

    async def test_list_companies(self, client, auth_headers):
        await client.post(
            "/api/v1/companies",
            headers=auth_headers,
            json={"name": "ListCo", "website": "https://listco.example.com"},
        )
        resp = await client.get("/api/v1/companies", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert body["total"] >= 1

    async def test_duplicate_domain_rejected(self, client, auth_headers):
        payload = {"name": "DupCo", "website": "https://dup.example.com"}
        first = await client.post("/api/v1/companies", headers=auth_headers, json=payload)
        assert first.status_code == 201
        second = await client.post("/api/v1/companies", headers=auth_headers, json=payload)
        assert second.status_code == 409


class TestCampaignsAPI:
    async def test_create_campaign(self, client, auth_headers):
        resp = await client.post(
            "/api/v1/campaigns",
            headers=auth_headers,
            json={
                "name": "Q3 Outreach",
                "from_name": "Alex Rivera",
                "from_email": "alex@example.com",
                "value_proposition": "We reduce churn",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Q3 Outreach"

    async def test_activate_campaign(self, client, auth_headers):
        create = await client.post(
            "/api/v1/campaigns",
            headers=auth_headers,
            json={"name": "Activate Me", "from_name": "A", "from_email": "a@b.com"},
        )
        campaign_id = create.json()["id"]
        activate = await client.post(
            f"/api/v1/campaigns/{campaign_id}/activate", headers=auth_headers
        )
        assert activate.status_code == 200
        assert activate.json()["status"] == "active"


class TestHealthEndpoints:
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestDashboardAPI:
    async def test_overview(self, client, auth_headers):
        resp = await client.get("/api/v1/dashboard/overview", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "total_leads" in body
        assert "open_rate_pct" in body
