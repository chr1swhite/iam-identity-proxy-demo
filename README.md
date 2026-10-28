# IAM Proxy Service (Keycloak Integration Demo)

## Концепция

Проект демонстрирует паттерн безопасной интеграции микросервисов с Identity Provider (Keycloak)
через слой проксирования. Фронтенд или клиентское приложение не обращается к Keycloak напрямую:
прокси скрывает `client_secret`, централизует логику аутентификации и валидации JWT, а также
извлекает роли пользователя для последующего контроля доступа (RBAC). Такой слой позволяет
заменить IdP без изменения клиентского кода и не выпускать Keycloak во внешний периметр.

## Архитектурная схема (Workflow)

```text
Клиент (Postman / Frontend)
        |
        | 1. POST /login {username, password}
        v
IAM Proxy (FastAPI)
        |
        | 2. POST /token (grant_type=password, client_id, client_secret, username, password)
        v
Keycloak (IdP)
        |
        | 3. JWT (access + refresh)
        v
IAM Proxy (FastAPI)
        |
        | 4. JWT клиенту
        v
Клиент

Далее:
Клиент -> GET /me (Authorization: Bearer <access_token>)
        -> IAM Proxy валидирует подпись по JWKS Keycloak, проверяет issuer,
           извлекает realm_access.roles и resource_access.<client_id>.roles
           и возвращает identity-контекст.