import os
import requests
from functools import lru_cache

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import jwt, JWTError, jwk

app = FastAPI(title="IAM Proxy Service (Keycloak Integration Demo)")

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "iam-demo")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "iam-proxy-client")
CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")

TOKEN_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
CERTS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
ISSUER = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"

# Схема безопасности для Swagger (кнопка Authorize)
bearer_scheme = HTTPBearer()


class LoginRequest(BaseModel):
    username: str
    password: str


@lru_cache(maxsize=1)
def get_jwks() -> dict:
    """Кэшируем JWKS Keycloak. В проде — TTL и инвалидация по kid."""
    resp = requests.get(CERTS_URL, timeout=5)
    resp.raise_for_status()
    return resp.json()


def decode_and_verify_token(token: str) -> dict:
    """
    Проверяет подпись JWT по JWKS Keycloak и валидирует issuer.
    Возвращает payload (claims).
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Malformed token: {e}")

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Token header has no 'kid'")

    jwks = get_jwks()
    key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    
    if not key_data:
        # kid мог ротироваться — сбросим кэш и попробуем ещё раз
        get_jwks.cache_clear()
        jwks = get_jwks()
        key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if not key_data:
            raise HTTPException(status_code=401, detail=f"Unknown signing key kid={kid}")

    public_key = jwk.construct(key_data)
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[key_data.get("alg", "RS256")],
            issuer=ISSUER,
            options={"verify_aud": False},  # Keycloak ставит aud='account'. В проде нужен Protocol Mapper и строгая проверка.
        )
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    return payload


@app.post("/login")
def login(req: LoginRequest):
    """
    Принимает креды от клиента, проксирует их в Keycloak,
    возвращает JWT (access + refresh). Client secret не уходит клиенту.
    """
    if not CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="CLIENT_SECRET is not configured")

    payload = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username": req.username,
        "password": req.password,
    }

    try:
        resp = requests.post(TOKEN_URL, data=payload, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.HTTPError:
        error_detail = resp.json() if resp.content else {"error": "Keycloak error"}
        raise HTTPException(status_code=resp.status_code, detail=error_detail)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Keycloak unreachable: {e}")

    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_in": data.get("expires_in"),
        "token_type": data.get("token_type"),
    }


@app.get("/me")
def me(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """
    Валидирует access_token (подпись + issuer) и возвращает identity-контекст:
    sub, username, роли из realm_access.roles и resource_access.<client_id>.roles.
    """
    token = credentials.credentials  # Swagger/FastAPI уже отрезали "Bearer "
    claims = decode_and_verify_token(token)

    # Собираем роли из обоих возможных мест в токене Keycloak
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    client_roles = (
        claims.get("resource_access", {})
        .get(CLIENT_ID, {})
        .get("roles", [])
    )
    all_roles = sorted(set(realm_roles) | set(client_roles))

    return {
        "sub": claims.get("sub"),
        "username": claims.get("preferred_username"),
        "email": claims.get("email"),
        "roles": all_roles,
        "issuer": claims.get("iss"),
        "expires_at": claims.get("exp"),
    }


@app.get("/health")
def health():
    return {"status": "ok"}