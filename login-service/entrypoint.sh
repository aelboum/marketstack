#!/bin/sh
# Reads the non-secret ids the provisioning step (scripts/
# provision_login_service_credential.py) wrote to the shared
# `login-service-credential` volume, so this container needs no manual
# copy-paste step (unlike OIDC_CLIENT_ID, which genuinely crosses a
# process boundary a developer must complete themselves). The private key
# itself is read directly from that same mount by app/config.py -- never
# exported into an environment variable.
set -eu

export LOGIN_SERVICE_ZITADEL_USER_ID="$(cat /credential/service_user_id.txt)"
export LOGIN_SERVICE_ZITADEL_KEY_ID="$(cat /credential/key_id.txt)"

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
