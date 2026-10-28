from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_invalid_token_rejected():
    """Проверяем, что поддельный токен отклоняется."""
    response = client.get(
        "/me",
        headers={"Authorization": "Bearer invalid.token.here"}
    )
    assert response.status_code == 401
    assert "Malformed token" in response.json()["detail"] or "Invalid token" in response.json()["detail"]

def test_missing_token_rejected():
    """Проверяем, что запрос без токена отклоняется."""
    response = client.get("/me")
    assert response.status_code == 403  # HTTPBearer возвращает 403, если токена нет