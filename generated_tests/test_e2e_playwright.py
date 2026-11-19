"""Auto-generated Playwright E2E tests for stateful user journeys."""
import pytest
import uuid
from playwright.sync_api import APIRequestContext, Page

import pytest
from playwright.sync_api import sync_playwright, expect

@pytest.fixture(scope="module")
def api_context():
    with sync_playwright() as p:
        context = p.chromium.new_context(base_url="http://localhost:8000")
        yield context
        context.close()

@pytest.fixture(scope="module")
def token(api_context):
    response = api_context.post("/auth/register", json={"username": "testuser", "password": "testpass"})
    assert response.status == 201

    login_response = api_context.post(
        "/auth/token",
        form={"grant_type": "password", "username": "testuser", "password": "testpass"}
    )
    assert login_response.status == 200
    return login_response.json().get("access_token")

@pytest.fixture(scope="module")
def item_id(api_context, token):
    response = api_context.post(
        "/items/",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Item Title", "description": "Item description", "price": 10.0}
    )
    assert response.status == 201
    return response.json().get("id")

def test_full_user_journey(api_context, token, item_id):
    # Step 4: GET /items/{item_id} with auth
    get_response = api_context.get(f"/items/{item_id}", headers={"Authorization": f"Bearer {token}"})
    assert get_response.status == 200
    data = get_response.json()
    assert data["title"] == "Item Title"
    assert data["description"] == "Item description"
    assert data["price"] == 10.0

    # Step 5: PUT /items/{item_id} with auth
    put_response = api_context.put(
        f"/items/{item_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Updated Title", "description": "Updated description", "price": 20.0}
    )
    assert put_response.status == 200
    updated_data = put_response.json()
    assert updated_data["title"] == "Updated Title"
    assert updated_data["description"] == "Updated description"
    assert updated_data["price"] == 20.0
def test_smoke_test(client):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(base_url="http://localhost:8000")
        page = context.new_page()
        page.goto("/docs")

        expect(page).to_have_title("Swagger UI")
        expect(page.locator(".opblock")).to_be_visible()

        context.close()
        browser.close()
