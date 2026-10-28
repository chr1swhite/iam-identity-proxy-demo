# IAM Proxy Service --- Keycloak Integration Demo

A minimal FastAPI proxy for Keycloak demonstrating JWT validation, RBAC,
and secret isolation.

## Interactive API Documentation

-   **Static API Docs (GitHub Pages):**
    https://chr1swhite.github.io/iam-identity-proxy-demo/index.html
-   **Local Swagger UI:** `http://localhost:8000/docs` (available after
    starting the proxy)

## 1. Концепция

Проект демонстрирует паттерн безопасной интеграции микросервисов с
Identity Provider (Keycloak) через слой проксирования. Фронтенд или
клиентское приложение не обращается к Keycloak напрямую: прокси скрывает
`client_secret`, централизует логику аутентификации и валидации JWT, а
также извлекает роли пользователя для последующего контроля доступа
(RBAC).

Такой слой позволяет заменить IdP без изменения клиентского кода и не
выпускать Keycloak во внешний периметр.

## 2. Как это работает под капотом (Deep Dive)

Взаимодействие разделено на два ключевых этапа: получение токена
(аутентификация) и его проверка (авторизация).

### 2.1. Аутентификация --- `POST /login`

1.  Клиент отправляет `username` и `password` в открытом виде (по HTTPS)
    на наш прокси.
2.  Прокси **не проверяет пароль сам** и **не хранит хэши**. Он берет
    эти данные и добавляет к ним `client_id` и `client_secret` (которые
    знает только он).
3.  Прокси отправляет POST-запрос в Keycloak по эндпоинту `/token` с
    `grant_type=password`.
4.  **Keycloak берет на себя всю криптографию**: находит пользователя в
    своей БД, достает его соленый хэш пароля (например, PBKDF2 или
    Argon2), хэширует полученный от прокси пароль и сравнивает
    результаты.
5.  Если пароли совпали, Keycloak генерирует JWT (JSON Web Token) и
    подписывает его своим приватным ключом (RS256). Прокси возвращает
    этот токен клиенту.

**Почему это безопасно:** фронтенд не знает `client_secret`. Если
злоумышленник перехватит пароль, он не сможет получить токен напрямую от
Keycloak, так как Keycloak не принимает запросы от неизвестных клиентов
без секрета. Прокси выступает как «щит».

### 2.2. Авторизация и валидация --- `GET /me`

1.  Клиент передает полученный JWT в заголовке
    `Authorization: Bearer <token>`.
2.  Прокси идет в Keycloak по эндпоинту `/certs`, чтобы забрать
    **публичный ключ** (JWKS).
3.  Прокси проверяет **подпись токена** этим публичным ключом. Если
    токен подделан (изменен хотя бы один символ в payload), подпись не
    сойдется, и прокси вернет `401`.
4.  Прокси также проверяет поле `iss` (`issuer`), чтобы убедиться, что
    токен выпущен именно нашим Keycloak, а не сторонним сервером.
5.  Если проверки пройдены, прокси парсит payload и достает роли
    (`iam-user`) для дальнейшего контроля доступа (RBAC).

## 3. Архитектурная схема (Workflow)

``` text
Клиент (Postman / Frontend)
        |
        | 1. POST /login {username, password}
        v
IAM Proxy (FastAPI)  <--- добавляет client_id и client_secret
        |
        | 2. POST /token (grant_type=password)
        v
Keycloak (IdP)       <--- проверяет хэш пароля в своей БД, подписывает JWT
        |
        | 3. JWT (access + refresh)
        v
IAM Proxy (FastAPI)  <--- отдает токен клиенту
        |
        | 4. JWT клиенту
        v
Клиент

Далее:
Клиент -> GET /me (Authorization: Bearer <access_token>)
        -> IAM Proxy (берет публичный ключ из Keycloak, проверяет подпись JWT, извлекает роли)
           -> возвращает identity-контекст
```

## 4. Реализованный функционал

-   Локальное развёртывание Keycloak в изолированном контейнере: Docker
    Compose и персистентный volume.
-   Эндпоинт `POST /login`: проброс `grant_type=password` в Keycloak с
    обогащением запроса `client_id` и `client_secret` на стороне прокси.
    Секрет не уходит клиенту.
-   Эндпоинт `GET /me`: валидация подписи JWT по JWKS Keycloak (RS256),
    проверка `iss`, извлечение `sub`, `preferred_username`, ролей из
    `realm_access` и `resource_access`.
-   **Изоляция секретов:** все параметры подключения и `client_secret`
    читаются из переменных окружения.
-   Интерактивная документация Swagger UI с поддержкой авторизации по
    Bearer-токену.
-   Health-check: `GET /health`.

## 5. Quick Start

Для локального запуска потребуются Docker и Python 3.10+.

### Шаг 1. Клонировать репозиторий

``` bash
git clone https://github.com/chr1swhite/iam-identity-proxy-demo.git
cd iam-identity-proxy-demo
```

### Шаг 2. Настроить переменные окружения

Скопируйте шаблон и заполните `KEYCLOAK_CLIENT_SECRET`. Его можно взять
в Keycloak UI: **Clients → iam-proxy-client → Credentials**.

``` bash
cp .env.example .env
```

### Шаг 3. Поднять Keycloak

``` bash
docker compose up -d
```

Дождитесь запуска (около 30 секунд) и откройте Admin Console:
`http://localhost:8080`. Логин и пароль по умолчанию: `admin` / `admin`.

### Шаг 4. Импортировать преднастроенный Realm

В Keycloak UI выберите **Create Realm → Browse**, укажите файл
`realm-export.json` из корня проекта и нажмите **Create**.

Это создаст realm `iam-demo`, клиента `iam-proxy-client` и пользователя
`testuser`.

### Шаг 5. Запустить прокси

``` bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Сервис будет доступен по адресу `http://localhost:8000`.

## 6. Проверка работы через Swagger UI

Проект использует встроенную в FastAPI генерацию OpenAPI-документации.

-   **Static API Docs (GitHub Pages):**
    https://chr1swhite.github.io/iam-identity-proxy-demo/index.html
-   **Local Swagger UI:** `http://localhost:8000/docs`

Как проверить работу локально:

1.  Выполните `POST /login` через **Try it out → Execute**.
2.  Скопируйте `access_token` из ответа.
3.  Нажмите **Authorize** (иконка замка в правом верхнем углу).
4.  Вставьте токен без слова `Bearer` и нажмите **Authorize → Close**.
5.  Выполните `GET /me`. Эндпоинт вернет `username` и список `roles`,
    извлеченных из JWT.

## 7. API Specification

### 7.1. `POST /login`

**Пример запроса:**

``` bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"password123"}'
```

**Пример ответа `200 OK`:**

``` json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "expires_in": 300,
  "token_type": "Bearer"
}
```

### 7.2. `GET /me`

**Пример запроса:**

``` bash
curl -X GET http://localhost:8000/me \
  -H "Authorization: Bearer <access_token>"
```

**Пример ответа `200 OK`:**

``` json
{
  "sub": "489a5af2-0726-44d2-a267-f1aa81eb20fb",
  "username": "testuser",
  "email": "testuser@example.com",
  "roles": [
    "default-roles-iam-demo",
    "iam-user",
    "offline_access",
    "uma_authorization"
  ],
  "issuer": "http://localhost:8080/realms/iam-demo",
  "expires_at": 1793148254
}
```

**Пример ответа `401 Unauthorized` для невалидного токена:**

``` json
{
  "detail": "Invalid token: Signature verification failed."
}
```

## 8. Осознанные упрощения и отличия от production

-   **`grant_type=password` (Direct Grant):** используется для
    наглядности в демо. В production рекомендуется Authorization Code +
    PKCE.
-   **Кэширование JWKS:** кэшируется без TTL (`lru_cache`). В production
    нужны TTL и инвалидация по `kid`.
-   **Проверка audience:** `verify_aud: False`, поскольку Keycloak
    кладёт в `aud` значение `account`. В production следует настроить
    Protocol Mapper, добавляющий `client_id` в `aud`, и включить строгую
    проверку audience.
-   **Хранение секретов:** секреты читаются из `.env`. В production
    следует использовать secret manager, Vault или Kubernetes Secrets.
-   **TLS:** в демо используется HTTP без TLS. В production нужна
    TLS-терминация на ingress/gateway.
