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

## Credential rotation (security audit F-14)

This service's own ZITADEL machine-user credential (private key +
`LOGIN_SERVICE_ZITADEL_USER_ID`/`LOGIN_SERVICE_ZITADEL_KEY_ID`) is
provisioned once by `scripts/provision_login_service_credential.py` (see
that script's own module docstring for the full mechanism) and never
rotates automatically. There is no scheduled/mandatory rotation interval
-- rotate deliberately, as an operator action, for reasons such as:

- suspected exposure of the local private key file;
- a manual/scheduled credential-lifecycle rotation your organization has
  decided on;
- intentionally replacing the Login Service machine-user key for any
  other operational reason.

### Preconditions

- You have the same ZITADEL administrative/bootstrap provisioning
  capability the initial provisioning step already required (the
  bootstrap PAT `provision_login_service_credential.py` reads from
  `ZITADEL_BOOTSTRAP_PAT_PATH`/`deploy-time` bootstrap volume -- never
  the Login Service's own runtime credential, which cannot provision
  itself).
- Perform rotation during a controlled deployment/restart window for
  the Login Service. The Login Service does not hot-reload its
  credential: the **currently running** process keeps using its
  existing, still-valid credential in memory until it is actually
  restarted against the new files -- rotation is safe to prepare ahead
  of a restart, but is not "live" until that restart happens.
- The Login Service must never be left with no valid credential at all.
  The procedure below relies on the provisioning script's own ordering
  guarantee (see "Ordering guarantee" below) to ensure this.

Never commit, log, or otherwise record the private key, the bootstrap
PAT, or any generated credential value anywhere in this repository or in
ticket/chat systems.

### Safe rotation procedure

This reuses the exact same provisioning mechanism the initial
credential was created by -- there is no separate "rotation script".
Re-running `scripts/provision_login_service_credential.py` against an
**empty** local credential directory is what triggers rotation
(`provision()`'s own idempotency check: if the three output files below
already exist, it does nothing).

1. Identify the Login Service's local credential directory. Local
   docker-compose development uses the `login-service-credential` named
   volume, mounted at `/credential` inside `login-service-provision`
   and `login-service`. A non-compose deployment uses whatever
   directory `LOGIN_SERVICE_CREDENTIAL_DIR` was set to (default
   `deploy/login-service`, relative to the repository root) -- confirm
   the actual value for your environment before proceeding.
2. Ensure a controlled restart point for the Login Service (stop it, or
   otherwise ensure your deployment process will restart it once the
   new credential is written -- see step 6).
3. **As part of this controlled rotation only**, remove the three local
   credential files from that directory:
   `private_key.pem`, `service_user_id.txt`, `key_id.txt`. This is what
   makes the provisioning step below actually run instead of exiting as
   "already provisioned."
4. Run the provisioning step again:
   - docker-compose (local development):
     ```
     docker compose run --rm login-service-provision
     ```
   - Any other deployment: run
     `python scripts/provision_login_service_credential.py` with the
     same environment it originally ran with (`ZITADEL_INTERNAL_URL`,
     `ZITADEL_BOOTSTRAP_PAT_PATH`, `OIDC_LOCAL_PROJECT_NAME`,
     `LOGIN_SERVICE_CREDENTIAL_DIR`, `LOGIN_SERVICE_ZITADEL_USERNAME`)
     -- use your environment's actual values, not the local-development
     defaults above.
5. Provisioning finds the existing Login Service machine user (reused,
   never recreated), lists its currently-registered keys, creates and
   verifies a replacement key, then removes the previously-listed
   (now obsolete) keys, and finally writes the three local credential
   files. Watch the command's own `[provision-login-service] ...`
   output as it runs (see "Ordering guarantee" and "What to check in
   the output" below).
6. Start/restart the Login Service so it loads the newly written
   credential files (`docker compose up -d login-service` or your
   deployment's equivalent restart).
7. Verify Login Service readiness: `GET /login-svc/healthz` returns
   `{"status": "ok"}`.
8. Verify a real authentication flow end-to-end through the normal
   path: branded Login Service sign-in (`GET /login-svc/login?
   authRequest=...`) with a real test account, through to SaaS-OS's
   `/auth/callback` completing and `/auth/me` succeeding afterward.

### Ordering guarantee (security audit F-01)

**The replacement key is created and verified before any obsolete key
is removed.** Provisioning never deletes an existing key first "to make
room" -- it lists the obsolete keys, creates the new one, confirms the
new key was actually registered (a `keyId` came back), and only then
attempts to remove the ones it listed earlier. This is why the running
Login Service is never left without a valid credential mid-rotation.

**Limitation to be aware of:** if removing an obsolete key fails after
the replacement was already created and verified, provisioning does
**not** fail the run or invalidate the new credential -- it prints a
`WARNING: could not remove obsolete key ...` line to its output and
continues. A successful (exit 0) provisioning run does **not** by
itself prove every obsolete key was actually removed. After every
rotation, read the provisioning output and confirm there is no such
warning; if there is one, remove the reported stale key through the
same controlled provisioning/ZITADEL-administrative process (never by
manually deleting the newly-created key).

### Post-rotation verification checklist

- [ ] Provisioning exited successfully (exit code 0).
- [ ] Provisioning's own output shows a new key was registered
      (`registered key '...' for user '...'`).
- [ ] Provisioning's output contains no `WARNING: could not remove
      obsolete key` line -- if it does, the old key(s) are still active
      and must be removed through the same provisioning/administrative
      process before considering rotation complete.
- [ ] The three local credential files exist in the credential
      directory with the same ownership/permissions convention the
      initial provisioning run produced (never world-writable, never
      committed -- `.gitignore`'s `deploy/login-service/` entry).
- [ ] The Login Service container/process starts successfully after
      restart.
- [ ] `GET /login-svc/healthz` returns `{"status": "ok"}`.
- [ ] A real password sign-in through the branded Login Service
      succeeds.
- [ ] SaaS-OS's `/auth/callback` completes normally afterward.
- [ ] `/auth/me` succeeds once authenticated.
- [ ] No credential value (private key, PAT, or otherwise) appears in
      any log output collected during the above.

### If something goes wrong

- **Replacement key creation itself fails:** provisioning raises before
  writing any local file and before touching any existing key -- the
  old key was never removed, and the Login Service keeps running on
  its existing credential unaffected. Investigate the failure (check
  `ZITADEL_INTERNAL_URL`, the bootstrap PAT, and ZITADEL's own health)
  before retrying; do not attempt a manual workaround.
- **Replacement succeeds but obsolete-key removal fails:** keep the new
  credential -- it is already valid and in use. Do not delete it
  manually. Remove the reported stale key through the same controlled
  provisioning/ZITADEL-administrative process (e.g. re-running
  provisioning again, which will list and retry removal of any key
  still registered on this user), never by hand-editing ZITADEL state
  outside that process.
- **The Login Service fails to start/authenticate after rotation:**
  verify the three local credential files exist, are readable by the
  service, and match what the latest provisioning run just wrote;
  verify (via the ZITADEL admin console or API, not by re-deriving it
  locally) that the corresponding key is still registered and active on
  the Login Service machine user; inspect Login Service logs without
  printing the private key or any token. If the new credential is
  genuinely unusable, restore service only by re-running the same
  approved provisioning mechanism again (which will again create and
  verify a fresh replacement key) -- there is no separate rollback
  script, and none should be improvised.

### Security notes

- The Login Service's private key is a runtime credential: it must
  never be committed, logged, or pasted into a ticket/chat system.
- It must never be placed in, or reachable from, frontend code -- it is
  read only by this backend process, from a local file path
  (`LOGIN_SERVICE_PRIVATE_KEY_PATH`).
- The running Login Service never uses the bootstrap PAT -- only
  `scripts/provision_login_service_credential.py` does, as a one-time
  administrative action.
- The provisioning bootstrap capability (the PAT, and whoever can run
  the provisioning step) is a separate, more privileged capability from
  the Login Service's own runtime machine-user credential -- do not
  conflate the two when deciding who may perform a rotation.
- Do not leave an old key active longer than necessary once you know a
  replacement is in place and verified -- see "Ordering guarantee"
  above for what to check.
