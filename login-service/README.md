# Login Service

Product-owned custom ZITADEL Login UI/server. See
`docs/ADR/0017-product-owned-zitadel-login-service.md` in the repository
root for the architecture decision, and `app/main.py`'s own module
docstring for the exact flow and its documented, deferred limitations.

A separate process/container from the main product backend and frontend:
it never imports `saas-os`, `product.*`, `core.*`, or `api.*`, and talks
to ZITADEL directly, never through the product backend.

## Local development

```
pip install -e ".[dev]"
pytest
ruff check .
```

Requires (see the repository root `.env.example`,
`LOGIN_SERVICE_*`/`ZITADEL_ISSUER_URL` keys):
`ZITADEL_ISSUER_URL`, `LOGIN_SERVICE_ZITADEL_USER_ID`,
`LOGIN_SERVICE_ZITADEL_KEY_ID`, `LOGIN_SERVICE_PRIVATE_KEY_PATH`,
`LOGIN_SERVICE_PUBLIC_ORIGIN`.
