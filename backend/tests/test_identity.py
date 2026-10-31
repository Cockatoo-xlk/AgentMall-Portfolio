from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from argon2 import PasswordHasher
from conftest import PASSWORD, row
from sqlalchemy import text


async def test_login_and_argon2_hash(env, buyer):
    client, db, _, _ = env
    response = await client.get("/api/v1/me", headers=buyer)
    assert response.status_code == 200
    assert response.json()["role"] == "buyer"
    assert "password_hash" not in response.json()
    stored = row(db, "SELECT password_hash FROM users WHERE login='buyer1'")["password_hash"]
    assert stored.startswith("$argon2id$")
    assert PasswordHasher().verify(stored, PASSWORD)


@pytest.mark.parametrize("login,password", [("buyer1", "bad"), ("missing", PASSWORD)])
async def test_login_failure(client, login, password):
    r = await client.post("/api/v1/auth/login", json={"login": login, "password": password})
    assert r.status_code == 401
    assert set(r.json()) == {"code", "message", "request_id", "retryable", "details"}


async def test_no_self_assigned_role_or_store(client, buyer):
    for field, value in [("role", "merchant"), ("store_id", str(uuid4()))]:
        r = await client.post(
            "/api/v1/auth/login", json={"login": "buyer1", "password": PASSWORD, field: value}
        )
        assert r.status_code == 422
    me = await client.get("/api/v1/me", headers={**buyer, "X-Role": "merchant"})
    assert me.json()["role"] == "buyer"


@pytest.mark.parametrize(
    "change", ["expired", "issuer", "audience", "algorithm", "unknown", "tampered"]
)
async def test_reject_invalid_jwt(env, buyer, change):
    client, _, _, settings = env
    token = buyer["Authorization"].split()[1]
    claims = jwt.decode(token, options={"verify_signature": False})
    secret = settings.jwt_secret.get_secret_value()
    algorithm = "HS256"
    if change == "expired":
        claims["exp"] = datetime.now(UTC) - timedelta(seconds=1)
    elif change == "issuer":
        claims["iss"] = "other"
    elif change == "audience":
        claims["aud"] = "other"
    elif change == "algorithm":
        algorithm = "HS384"
    elif change == "unknown":
        claims["sub"] = str(uuid4())
    elif change == "tampered":
        secret = "wrong-signing-secret-that-is-long-enough"
    token = jwt.encode(claims, secret, algorithm=algorithm)
    assert (
        await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 401


async def test_roles_and_disabled_state_come_from_database(env, buyer):
    client, db, _, settings = env
    claims = jwt.decode(buyer["Authorization"].split()[1], options={"verify_signature": False})
    assert 0 < claims["exp"] - claims["iat"] <= 900
    assert "role" not in claims and "store_id" not in claims
    claims.update(role="merchant", store_id=str(uuid4()))
    forged_role = jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    r = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {forged_role}"})
    assert r.json()["role"] == "buyer"
    assert r.json()["store_id"] == str(settings.storefront_id)
    with db.begin() as conn:
        conn.execute(text("UPDATE users SET disabled=true WHERE login='buyer1'"))
    assert (await client.get("/api/v1/me", headers=buyer)).status_code == 401
    r = await client.post("/api/v1/auth/login", json={"login": "buyer1", "password": PASSWORD})
    assert r.status_code == 401


async def test_merchant_cannot_access_buyer_cart(client):
    login = await client.post(
        "/api/v1/auth/login", json={"login": "merchant", "password": PASSWORD}
    )
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert (await client.get("/api/v1/me", headers=headers)).json()["role"] == "merchant"
    assert (await client.get("/api/v1/cart", headers=headers)).status_code == 403


async def test_anonymous_cart_rejected(client):
    assert (await client.get("/api/v1/cart")).status_code == 401


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("GET", "/api/v1/me", None),
        ("GET", "/api/v1/cart", None),
        (
            "PUT",
            "/api/v1/cart/items/00000000-0000-0000-0000-000000000001",
            {"quantity": 1, "expected_version": 0},
        ),
        (
            "DELETE",
            "/api/v1/cart/items/00000000-0000-0000-0000-000000000001",
            {"expected_version": 0},
        ),
    ],
)
async def test_unauthenticated_requests_rejected_before_database(method, path, payload):
    from httpx import ASGITransport, AsyncClient

    from agentmall.main import create_app

    app = create_app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            response = await http.request(method, path, json=payload)
            assert response.status_code == 401
    finally:
        await app.state.engine.dispose()
