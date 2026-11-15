"""Auto-generated Playwright E2E tests for stateful user journeys."""
import pytest
import uuid
from playwright.sync_api import APIRequestContext, Page

import pytest
from playwright.sync_api import sync_playwright, expect

@pytest.fixture(scope="module")
def api_context():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        yield context
        browser.close()

@pytest.fixture(scope="module")
def user_credentials(api_context):
    username = "testuser"
    password = "password123"
    response = api_context.request.post("http://localhost:8000/auth/register", json={"username": username, "password": password})
    assert response.status == 201
    return {"username": username, "password": password}

@pytest.fixture(scope="module")
def access_token(api_context, user_credentials):
    response = api_context.request.post("http://localhost:8000/auth/token", data={"grant_type": "password", "username": user_credentials["username"], "password": user_credentials["password"]})
    assert response.status == 200
    return response.json().get("access_token")

@pytest.fixture(scope="module")
def item_id(api_context, access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    response = api_context.request.post("http://localhost:8000/items/", json={"name": "test item", "description": "a test item"}, headers=headers)
    assert response.status == 201
    return response.json().get("id")

def test_full_user_journey(api_context, access_token, item_id):
    # Step 3: POST /items/ with auth header → expect 201, save item_id
    headers = {"Authorization": f"Bearer {access_token}"}
    response = api_context.request.post("http://localhost:8000/items/", json={"name": "test item", "description": "a test item"}, headers=headers)
    assert response.status == 201
    item_id = response.json().get("id")

    # Step 4: GET /items/{item_id} with auth → expect 200, verify data
    response = api_context.request.get(f"http://localhost:8000/items/{item_id}", headers=headers)
    assert response.status == 200
    item_data = response.json()
    assert item_data["name"] == "test item"
    assert item_data["description"] == "a test item"

    # Step 5: PUT /items/{item_id} with auth → expect 200, verify updated data
    update_response = api_context.request.put(f"http://localhost:8000/items/{item_id}", json={"name": "updated item", "description": "an updated item"}, headers=headers)
    assert update_response.status == 200
    updated_item_data = update_response.json()
    assert updated_item_data["name"] == "updated item"
    assert updated_item_data["description"] == "an updated item"

    # Step 6: DELETE /items/{item_id} with auth → expect 204
    delete_response = api_context.request.delete(f"http://localhost:8000/items/{item_id}", headers=headers)
    assert delete_response.status == 204

    # Step 7: GET /items/{item_id} after delete → expect 404 OR 500 (note if 500: possible API_BUG)
    final_get_response = api_context.request.get(f"http://localhost:8000/items/{item_id}", headers=headers)
    assert final_get_response.status in [404, 500]

def test_swagger_smoke_test():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto("http://localhost:8000/docs")
        expect(page).to_have_title("Swagger")
        endpoints = page.query_selector_all(".opblock-summary")
        assert len(endpoints) > 0
        browser.close()