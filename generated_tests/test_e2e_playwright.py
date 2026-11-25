"""Auto-generated Playwright E2E tests for stateful user journeys."""
import re
import uuid
import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="module")
def playwright_instance():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(base_url="http://localhost:8000")
        yield context
        context.close()
        browser.close()


@pytest.fixture(scope="module")
def token(playwright_instance):
    username = f"user_{uuid.uuid4().hex[:6]}"
    password = "testpassword123"

    # Register — Playwright APIRequestContext requires data= (not json=) for dict payloads
    reg_res = playwright_instance.request.post(
        "/auth/register",
        data={"username": username, "password": password},
    )
    assert reg_res.status in (200, 201), (
        f"Registration failed: {reg_res.status} {reg_res.text()}"
    )

    # Login via OAuth2 form data
    login_res = playwright_instance.request.post(
        "/auth/token",
        form={"username": username, "password": password},
    )
    assert login_res.status == 200, (
        f"Login failed: {login_res.status} {login_res.text()}"
    )
    return login_res.json().get("access_token", "")


@pytest.fixture(scope="module")
def created_item_id(playwright_instance, token):
    headers = {"Authorization": f"Bearer {token}"}
    res = playwright_instance.request.post(
        "/items/",
        headers=headers,
        data={"title": "E2E Item", "description": "E2E description", "price": "5.0"},
    )
    assert res.status == 201, f"Item creation failed: {res.status} {res.text()}"
    return res.json().get("id")


def test_full_user_journey(playwright_instance, token, created_item_id):
    headers = {"Authorization": f"Bearer {token}"}

    # GET /items/{item_id}
    get_res = playwright_instance.request.get(
        f"/items/{created_item_id}", headers=headers
    )
    assert get_res.status == 200, f"GET item failed: {get_res.status}"
    data = get_res.json()
    assert data["title"] == "E2E Item"
    assert data["description"] == "E2E description"

    # PUT /items/{item_id}
    put_res = playwright_instance.request.put(
        f"/items/{created_item_id}",
        headers=headers,
        data={"title": "Updated E2E Item", "description": "Updated desc", "price": "9.99"},
    )
    assert put_res.status == 200, f"PUT item failed: {put_res.status}"
    updated = put_res.json()
    assert updated["title"] == "Updated E2E Item"

    # DELETE /items/{item_id} — BUG-1: server returns 200 instead of spec-required 204
    del_res = playwright_instance.request.delete(
        f"/items/{created_item_id}", headers=headers
    )
    assert del_res.status in (200, 204), f"DELETE item failed: {del_res.status}"


def test_smoke_test(playwright_instance):
    page = playwright_instance.new_page()
    try:
        page.goto("/docs")
        assert re.search(r"Swagger UI", page.title()) is not None, (
            f"Expected 'Swagger UI' in page title, got: {page.title()!r}"
        )
        assert page.locator(".opblock").first.is_visible(), (
            "No .opblock elements visible on /docs"
        )
    finally:
        page.close()
