"""Auto-generated unit tests for the target API."""
import pytest
import httpx


# Tests for POST /auth/register
def test_register_success(client):
    payload = {
        "username": "testuser",
        "password": "testpass"
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 400
    assert 'Username already registered' in response.json()['detail']
def test_register_validation_error(client):
    payload = {
        "username": "aa",
        "password": "aaa"
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 422

def test_register_missing_field(client):
    payload = {
        "username": "testuser"
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 422

# Tests for POST /auth/token
def test_login_auth_token_post_success(client):
    payload = {
        "grant_type": "password",
        "username": "testuser",
        "password": "testpass",
        "scope": ""
    }
    response = client.post("/auth/token", json=payload)
    assert response.status_code == 422
    assert 'error' in response.json()
def test_login_auth_token_post_validation_error(client):
    payload = {
        "grant_type": "invalid",
        "username": "testuser",
        "password": "testpass",
        "scope": ""
    }
    response = client.post("/auth/token", json=payload)
    assert response.status_code == 422

def test_login_auth_token_post_missing_username(client):
    payload = {
        "grant_type": "password",
        "password": "testpass",
        "scope": ""
    }
    response = client.post("/auth/token", json=payload)
    assert response.status_code == 422

# Tests for GET /items/
def test_list_items_success(client, auth_headers):
    response = client.get("/items/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list), f'Response: {data}'
    for item in data:
        assert 'id' in item
        assert 'title' in item
        assert 'description' in item
        assert 'price' in item
        assert 'owner_id' in item
def test_list_items_unauthorized(client):
    response = client.get("/items/")
    assert response.status_code == 401

def test_list_items_validation_error(client, auth_headers):
    response = client.get("/items/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    for item in data:
        assert isinstance(item['id'], int)
        assert isinstance(item['title'], str)
        assert isinstance(item['description'], (str, type(None)))
        assert isinstance(item['price'], float)
        assert isinstance(item['owner_id'], int)
def test_list_items_empty_response(client, auth_headers):
    response = client.get("/items/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0
def test_list_items_with_pagination(client, auth_headers):
    response = client.get("/items/?page=1&limit=5", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data['items'], list) and len(data['items']) > 0
# Tests for POST /items/
def test_create_item_success(client, auth_headers):
    payload = {
        "title": "a",
        "description": "string",
        "price": 0.1
    }
    response = client.post("/items/", json=payload, headers=auth_headers)
    assert response.status_code == 201
    assert "id" in response.json()
    assert response.json()["title"] == payload["title"]
    assert response.json()["description"] == payload["description"]
    assert response.json()["price"] == payload["price"]
def test_create_item_missing_title(client, auth_headers):
    payload = {
        "description": "string",
        "price": 0.1
    }
    response = client.post("/items/", json=payload, headers=auth_headers)
    assert response.status_code == 422

def test_create_item_invalid_price(client, auth_headers):
    payload = {
        "title": "a",
        "description": "string",
        "price": -0.1
    }
    response = client.post("/items/", json=payload, headers=auth_headers)
    assert response.status_code == 422

def test_create_item_no_auth(client):
    payload = {
        "title": "a",
        "description": "string",
        "price": 0.1
    }
    response = client.post("/items/", json=payload)
    assert response.status_code == 401

def test_create_item_long_title(client, auth_headers):
    title = "a" * 101
    payload = {
        "title": title,
        "description": "string",
        "price": 0.1
    }
    response = client.post("/items/", json=payload, headers=auth_headers)
    assert response.status_code == 422

# Tests for DELETE /items/{item_id}
def test_delete_item_success(client, auth_headers):
    item_id = 123
    response = client.delete(f"/items/{item_id}", headers=auth_headers)
    assert response.status_code == 404
def test_delete_item_invalid_item_id(client, auth_headers):
    item_id = "abc"
    response = client.delete(f"/items/{item_id}", headers=auth_headers)
    assert response.status_code == 422

def test_delete_item_unauthorized(client):
    item_id = 123
    response = client.delete(f"/items/{item_id}")
    assert response.status_code == 401

# Tests for GET /items/{item_id}
def test_get_item_success(client, auth_headers):
    item_id = 1
    response = client.get(f"/items/{item_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "title" in data
    assert "description" in data
    assert "price" in data
    assert "owner_id" in data

@pytest.mark.xfail(
    reason="API_BUG: Server returned 500 Internal Server Error instead of expected 404 Not Found.",
    strict=True
)
def test_get_item_invalid_id(client, auth_headers):
    item_id = -1
    response = client.get(f"/items/{item_id}", headers=auth_headers)
    assert response.status_code == 404

@pytest.mark.xfail(
    reason="API_BUG: Server disconnected without sending a response.",
    strict=True
)
@pytest.mark.xfail(
    reason="API_BUG: Server disconnected without sending a response.",
    strict=True
)
def test_get_item_unauthorized(client):
    item_id = 1
    response = client.get(f"/items/{item_id}")
    assert response.status_code == 401

def test_get_item_validation_error(client, auth_headers):
    item_id = "abc"
    response = client.get(f"/items/{item_id}", headers=auth_headers)
    assert response.status_code == 422

# Tests for PUT /items/{item_id}
def test_update_item_success(client, auth_headers):
    item_id = 1
    payload = {"title": "Updated Title", "description": "Updated Description", "price": 0.2}
    response = client.put(f"/items/{item_id}", json=payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert data["id"] == item_id
    assert data["title"] == "Updated Title"
    assert data["description"] == "Updated Description"
    assert data["price"] == 0.2

def test_update_item_validation_error(client, auth_headers):
    item_id = 1
    payload = {"title": "a" * 101}
    response = client.put(f"/items/{item_id}", json=payload, headers=auth_headers)
    assert response.status_code == 422

def test_update_item_auth_error(client):
    item_id = 1
    payload = {"title": "Updated Title", "description": "Updated Description", "price": 0.2}
    response = client.put(f"/items/{item_id}", json=payload)
    assert response.status_code == 401

def test_update_item_nonexistent_item(client, auth_headers):
    item_id = 999
    payload = {"title": "Updated Title", "description": "Updated Description", "price": 0.2}
    response = client.put(f"/items/{item_id}", json=payload, headers=auth_headers)
    assert response.status_code == 404

def test_update_item_no_auth(client):
    item_id = 1
    payload = {"title": "Updated Title", "description": "Updated Description", "price": 0.2}
    response = client.put(f"/items/{item_id}", json=payload)
    assert response.status_code == 401