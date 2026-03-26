"""
tests/test_auth_users.py — Tests for auth, user profile, saved searches,
user favorites, and admin endpoints.
"""

import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def user_db(tmp_path):
    """Isolated UserDB backed by a temp file."""
    from utils.user_db import UserDB
    return UserDB(path=str(tmp_path / "users.db"))


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """TestClient with all DB paths redirected to tmp_path."""
    import api.app as app_module
    import api.routers.auth as auth_module
    import api.routers.users as users_module
    import api.routers.admin as admin_module
    from utils.user_db import UserDB

    db = UserDB(path=str(tmp_path / "users.db"))
    monkeypatch.setattr(app_module, "_API_KEY", "")
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "main.db"))
    monkeypatch.setattr(app_module, "FAV_DB_PATH", str(tmp_path / "fav.db"))
    app_module._ensure_fav_schema()

    # Point all routers to the same isolated DB
    monkeypatch.setattr(auth_module, "_db", db)
    monkeypatch.setattr(users_module, "_user_db", db)
    monkeypatch.setattr(admin_module, "_user_db", db)

    return TestClient(app_module.app, raise_server_exceptions=True)


def _register(client, email="user@test.com", password="pass123"):
    """Helper: register a user and return (token, user_id)."""
    res = client.post("/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.text
    data = res.json()
    return data["token"], data["user"]["id"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── /auth/register ────────────────────────────────────────────────────────────

def test_register_creates_user(app_client):
    res = app_client.post("/auth/register", json={"email": "a@b.com", "password": "pass123"})
    assert res.status_code == 201
    data = res.json()
    assert "token" in data
    assert data["user"]["email"] == "a@b.com"
    assert "hashed_password" not in data["user"]


def test_register_first_user_is_admin(app_client):
    _, uid = _register(app_client, "first@test.com")
    # First registered user gets admin role
    token2, _ = _register(app_client, "second@test.com")
    # Get profile — first user should be admin
    token1, _ = _register.__wrapped__(app_client, "first@test.com") if False else (None, None)
    # Re-login as first user to check role
    res = app_client.post("/auth/login", json={"email": "first@test.com", "password": "pass123"})
    assert res.json()["user"]["role"] == "admin"


def test_register_duplicate_email_rejected(app_client):
    _register(app_client)
    res = app_client.post("/auth/register", json={"email": "user@test.com", "password": "other123"})
    assert res.status_code == 409


def test_register_short_password_rejected(app_client):
    res = app_client.post("/auth/register", json={"email": "x@y.com", "password": "abc"})
    assert res.status_code == 422


# ── /auth/login ───────────────────────────────────────────────────────────────

def test_login_valid_credentials(app_client):
    _register(app_client)
    res = app_client.post("/auth/login", json={"email": "user@test.com", "password": "pass123"})
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["user"]["email"] == "user@test.com"


def test_login_wrong_password(app_client):
    _register(app_client)
    res = app_client.post("/auth/login", json={"email": "user@test.com", "password": "wrong!"})
    assert res.status_code == 401


def test_login_unknown_email(app_client):
    res = app_client.post("/auth/login", json={"email": "nobody@x.com", "password": "pass123"})
    assert res.status_code == 401


# ── /auth/forgot-password ─────────────────────────────────────────────────────

def test_forgot_password_always_returns_202(app_client):
    # Email not registered — still 202 (no enumeration)
    with patch("api.routers.auth.send_email"):
        res = app_client.post("/auth/forgot-password", json={"email": "nobody@x.com"})
    assert res.status_code == 202


def test_forgot_password_registered_email_returns_202(app_client):
    _register(app_client)
    with patch("api.routers.auth.send_email") as mock_email:
        res = app_client.post("/auth/forgot-password", json={"email": "user@test.com"})
    assert res.status_code == 202
    mock_email.assert_called_once()


# ── /auth/reset-password ──────────────────────────────────────────────────────

def test_reset_password_valid_token(app_client, monkeypatch):
    import api.routers.auth as auth_module
    _register(app_client)
    # Get the DB used by auth module
    db = auth_module._db
    user = db.get_user_by_email("user@test.com")
    reset_token = db.create_reset_token(user["id"])

    res = app_client.post("/auth/reset-password", json={"token": reset_token, "password": "newpass456"})
    assert res.status_code == 200
    assert "Password updated" in res.json()["detail"]

    # Can now login with new password
    login_res = app_client.post("/auth/login", json={"email": "user@test.com", "password": "newpass456"})
    assert login_res.status_code == 200


def test_reset_password_token_consumed_on_use(app_client):
    import api.routers.auth as auth_module
    _register(app_client)
    db = auth_module._db
    user = db.get_user_by_email("user@test.com")
    reset_token = db.create_reset_token(user["id"])

    app_client.post("/auth/reset-password", json={"token": reset_token, "password": "newpass456"})

    # Second use of same token should fail
    res2 = app_client.post("/auth/reset-password", json={"token": reset_token, "password": "another789"})
    assert res2.status_code == 400


def test_reset_password_invalid_token(app_client):
    res = app_client.post("/auth/reset-password", json={"token": "bogus-token-xyz", "password": "newpass456"})
    assert res.status_code == 400


def test_reset_password_short_password_rejected(app_client):
    import api.routers.auth as auth_module
    _register(app_client)
    db = auth_module._db
    user = db.get_user_by_email("user@test.com")
    reset_token = db.create_reset_token(user["id"])

    res = app_client.post("/auth/reset-password", json={"token": reset_token, "password": "ab"})
    assert res.status_code == 422


# ── /users/{user_id} profile ──────────────────────────────────────────────────

def test_get_profile_requires_auth(app_client):
    _, uid = _register(app_client)
    res = app_client.get(f"/users/{uid}")
    assert res.status_code == 401


def test_get_profile_returns_own_data(app_client):
    token, uid = _register(app_client)
    res = app_client.get(f"/users/{uid}", headers=_auth_headers(token))
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "user@test.com"
    assert "hashed_password" not in data


def test_get_profile_blocked_for_other_user(app_client):
    token1, uid1 = _register(app_client, "a@test.com")
    _, uid2 = _register(app_client, "b@test.com")
    res = app_client.get(f"/users/{uid2}", headers=_auth_headers(token1))
    assert res.status_code == 403


def test_update_profile_notify_carvana(app_client):
    token, uid = _register(app_client)
    res = app_client.patch(f"/users/{uid}", json={"notify_carvana": True}, headers=_auth_headers(token))
    assert res.status_code == 200
    assert res.json()["notify_carvana"] is True


# ── /users/{user_id}/searches ─────────────────────────────────────────────────

def test_create_and_list_search(app_client):
    token, uid = _register(app_client)
    body = {"name": "My Tacoma Search", "criteria": {"query": "tacoma", "zip_code": "85001", "radius_miles": 100}}
    res = app_client.post(f"/users/{uid}/searches", json=body, headers=_auth_headers(token))
    assert res.status_code == 201
    search = res.json()
    assert search["name"] == "My Tacoma Search"
    assert search["criteria"]["query"] == "tacoma"

    list_res = app_client.get(f"/users/{uid}/searches", headers=_auth_headers(token))
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1


def test_delete_search(app_client):
    token, uid = _register(app_client)
    body = {"name": "To Delete", "criteria": {"query": "f150", "zip_code": "85001", "radius_miles": 50}}
    create_res = app_client.post(f"/users/{uid}/searches", json=body, headers=_auth_headers(token))
    sid = create_res.json()["id"]

    del_res = app_client.delete(f"/users/{uid}/searches/{sid}", headers=_auth_headers(token))
    assert del_res.status_code == 204

    list_res = app_client.get(f"/users/{uid}/searches", headers=_auth_headers(token))
    assert list_res.json() == []


def test_delete_all_searches(app_client):
    token, uid = _register(app_client)
    base_body = {"criteria": {"query": "x", "zip_code": "85001", "radius_miles": 50}}
    for i in range(3):
        app_client.post(f"/users/{uid}/searches", json={**base_body, "name": f"S{i}"}, headers=_auth_headers(token))

    res = app_client.delete(f"/users/{uid}/searches", headers=_auth_headers(token))
    assert res.status_code == 200
    assert res.json()["deleted"] == 3


def test_delete_nonexistent_search_404(app_client):
    token, uid = _register(app_client)
    res = app_client.delete(f"/users/{uid}/searches/9999", headers=_auth_headers(token))
    assert res.status_code == 404


def test_search_cross_user_blocked(app_client):
    token1, uid1 = _register(app_client, "a@test.com")
    token2, uid2 = _register(app_client, "b@test.com")
    res = app_client.get(f"/users/{uid1}/searches", headers=_auth_headers(token2))
    assert res.status_code == 403


# ── /users/{user_id}/favorites ────────────────────────────────────────────────

_SAMPLE_LISTING = {
    "listing_id": "cl_001",
    "title": "2020 Tacoma TRD",
    "asking_price": 32000,
    "source": "craigslist",
    "url": "https://example.com/1",
}


def test_add_and_get_user_favorite(app_client):
    token, uid = _register(app_client)
    res = app_client.post(
        f"/users/{uid}/favorites",
        json={"listing_data": _SAMPLE_LISTING},
        headers=_auth_headers(token),
    )
    assert res.status_code == 201

    fav_res = app_client.get(f"/users/{uid}/favorites", headers=_auth_headers(token))
    assert fav_res.status_code == 200
    favs = fav_res.json()
    assert len(favs) == 1
    assert favs[0]["listing_id"] == "cl_001"


def test_remove_user_favorite(app_client):
    token, uid = _register(app_client)
    app_client.post(f"/users/{uid}/favorites", json={"listing_data": _SAMPLE_LISTING}, headers=_auth_headers(token))

    del_res = app_client.delete(f"/users/{uid}/favorites/cl_001", headers=_auth_headers(token))
    assert del_res.status_code == 204

    fav_res = app_client.get(f"/users/{uid}/favorites", headers=_auth_headers(token))
    assert fav_res.json() == []


def test_remove_nonexistent_favorite_404(app_client):
    token, uid = _register(app_client)
    res = app_client.delete(f"/users/{uid}/favorites/no_such_id", headers=_auth_headers(token))
    assert res.status_code == 404


def test_favorites_isolated_per_user(app_client):
    token1, uid1 = _register(app_client, "a@test.com")
    token2, uid2 = _register(app_client, "b@test.com")

    app_client.post(f"/users/{uid1}/favorites", json={"listing_data": _SAMPLE_LISTING}, headers=_auth_headers(token1))

    fav2 = app_client.get(f"/users/{uid2}/favorites", headers=_auth_headers(token2))
    assert fav2.json() == []


# ── /admin/users ──────────────────────────────────────────────────────────────

def _make_admin(app_client, email="admin@test.com", password="adminpass"):
    """Register first user (auto-admin) and return token."""
    token, uid = _register(app_client, email, password)
    return token, uid


def test_admin_list_users(app_client):
    admin_token, _ = _make_admin(app_client)
    _register(app_client, "regular@test.com")

    res = app_client.get("/admin/users", headers=_auth_headers(admin_token))
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_admin_promote_user(app_client):
    admin_token, _ = _make_admin(app_client)
    _, uid2 = _register(app_client, "regular@test.com")

    res = app_client.patch(f"/admin/users/{uid2}", json={"role": "admin"}, headers=_auth_headers(admin_token))
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_admin_invalid_role_rejected(app_client):
    admin_token, _ = _make_admin(app_client)
    _, uid2 = _register(app_client, "regular@test.com")

    res = app_client.patch(f"/admin/users/{uid2}", json={"role": "superuser"}, headers=_auth_headers(admin_token))
    assert res.status_code == 422


def test_admin_delete_user(app_client):
    admin_token, _ = _make_admin(app_client)
    _, uid2 = _register(app_client, "todelete@test.com")

    del_res = app_client.delete(f"/admin/users/{uid2}", headers=_auth_headers(admin_token))
    assert del_res.status_code == 204

    list_res = app_client.get("/admin/users", headers=_auth_headers(admin_token))
    assert len(list_res.json()) == 1


def test_admin_cannot_delete_self(app_client):
    admin_token, admin_uid = _make_admin(app_client)
    res = app_client.delete(f"/admin/users/{admin_uid}", headers=_auth_headers(admin_token))
    assert res.status_code == 400


def test_non_admin_blocked_from_admin_routes(app_client):
    _make_admin(app_client)  # creates first user (admin)
    token2, _ = _register(app_client, "regular@test.com")

    res = app_client.get("/admin/users", headers=_auth_headers(token2))
    assert res.status_code == 403


def test_admin_get_user_searches(app_client):
    admin_token, _ = _make_admin(app_client)
    token2, uid2 = _register(app_client, "regular@test.com")

    body = {"name": "Test", "criteria": {"query": "camry", "zip_code": "85001", "radius_miles": 50}}
    app_client.post(f"/users/{uid2}/searches", json=body, headers=_auth_headers(token2))

    res = app_client.get(f"/admin/users/{uid2}/searches", headers=_auth_headers(admin_token))
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_admin_get_user_favorites(app_client):
    admin_token, _ = _make_admin(app_client)
    token2, uid2 = _register(app_client, "regular@test.com")
    app_client.post(f"/users/{uid2}/favorites", json={"listing_data": _SAMPLE_LISTING}, headers=_auth_headers(token2))

    res = app_client.get(f"/admin/users/{uid2}/favorites", headers=_auth_headers(admin_token))
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_unauthenticated_blocked(app_client):
    """No token → 401 on all protected routes."""
    res = app_client.get("/users/1")
    assert res.status_code == 401

    res = app_client.get("/admin/users")
    assert res.status_code == 401
