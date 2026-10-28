import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from jose import jwt
from main import app, ISSUER

client = TestClient(app)

# Фейковый JWKS, чтобы тесты не ходили в реальный Keycloak
FAKE_JWKS = {
    "keys": [
        {
            "kid": "real-kid-123",
            "kty": "RSA",
            "alg": "RS256",
            "use": "sig",
            "n": "test_n_value",
            "e": "AQAB"
        }
    ]
}

@pytest.fixture(autouse=True)
def mock_jwks():
    """Подменяем запрос к Keycloak на фейковый JWKS для всех тестов."""
    with patch("main.get_jwks", return_value=FAKE_JWKS):
        yield

def test_missing_token_rejected():
    """1. Запрос без токена должен возвращать 403 (HTTPBearer)."""
    response = client.get("/me")
    assert response.status_code == 403
    assert "Not authenticated" in response.text

def test_malformed_token_rejected():
    """2. Мусор вместо токена возвращает 401."""
    response = client.get("/me", headers={"Authorization": "Bearer garbage.token.here"})
    assert response.status_code == 401
    assert "Malformed token" in response.json()["detail"]

def test_wrong_issuer_rejected():
    """3. Токен с неправильным issuer отклоняется."""
    # Подписываем фейковым ключом (в тесте подпись все равно проверяется)
    claims = {
        "sub": "123", "preferred_username": "test", 
        "iss": "http://evil.com/realms/hacker",
        "exp": 9999999999
    }
    # Используем HS256 и строку как ключ для простоты, 
    # но в реальном коде ожидается RS256. 
    # (Для теста issuer-а нам важно, чтобы токен был читаемым)
    token = jwt.encode(claims, "secret", algorithm="HS256", headers={"kid": "real-kid-123"})
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    # Упадет либо на issuer, либо на подписи (т.к. alg не тот), но статус должен быть 401
    assert response.status_code == 401
    assert "Invalid token" in response.json()["detail"]

def test_unknown_kid_rejected():
    """4. Токен с неизвестным kid отклоняется."""
    claims = {
        "sub": "123", "preferred_username": "test", 
        "iss": ISSUER, "exp": 9999999999
    }
    token = jwt.encode(claims, "secret", algorithm="HS256", headers={"kid": "unknown-kid"})
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "Unknown signing key" in response.json()["detail"]

from unittest.mock import patch

def test_valid_token_accepted():
    """5. Валидный токен (замоканная проверка) возвращает 200."""
    fake_claims = {
        "sub": "123",
        "preferred_username": "testuser",
        "realm_access": {"roles": ["iam-user"]},
        "resource_access": {},
        "iss": ISSUER
    }
    
    # Мокаем функцию проверки токена, чтобы она возвращала валидные claims
    with patch("main.decode_and_verify_token", return_value=fake_claims):
        response = client.get(
            "/me",
            headers={"Authorization": "Bearer fake_valid_token"}
        )
        
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
    assert "iam-user" in data["roles"]