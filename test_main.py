import pytest
from fastapi.testclient import TestClient
from jose import jwt
from main import app, ISSUER

client = TestClient(app)

# Фейковый секрет для генерации тестовых токенов
# (в реальном Keycloak подпись другая, поэтому мы тестируем логику отказов)
FAKE_SECRET = "test_secret_123"

def get_token_with_claims(claims: dict, key: str = FAKE_SECRET):
    """Генерирует JWT с заданными claims для тестов."""
    return jwt.encode(claims, key, algorithm="HS256", headers={"kid": "test-kid"})

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
    claims = {
        "sub": "123", "preferred_username": "test", 
        "iss": "http://evil.com/realms/hacker",
        "exp": 9999999999
    }
    token = get_token_with_claims(claims)
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    # Проверяем, что ошибка именно про issuer или подпись (так как ключ тоже не тот)
    assert "Invalid token" in response.json()["detail"]

def test_unknown_kid_rejected():
    """4. Токен с неизвестным kid отклоняется."""
    # kid="test-kid" точно нет в JWKS реального Keycloak
    claims = {
        "sub": "123", "preferred_username": "test", 
        "iss": ISSUER, "exp": 9999999999
    }
    token = get_token_with_claims(claims)
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "Unknown signing key" in response.json()["detail"]