"""Minimal, dependency-free HTML rendering for the branded Login UI.
Plain f-strings, not a template engine -- this service's own pages are
few and simple enough that adding Jinja2 would be dependency weight with
no real benefit (docs/ADR/0017: "keep dependencies minimal").

Color tokens are copied from `frontend/app/globals.css`'s own neutral
placeholder palette (never imported -- this is a separate process/
container with no access to the frontend's build) so the two surfaces
read as the same product without this service depending on the frontend
in any way. No tenant/white-label branding is available here: this page
is served *before* any tenant is known (docs/ADR/0017 -- the Login
Service runs ahead of SaaS-OS's own tenant resolution), so only the
platform-level default brand name (`LOGIN_SERVICE_BRAND_NAME`) is ever
shown, matching docs/ADR/0001's "default display name is a runtime
configuration value" rule.

Every user-supplied value rendered here (`error`, form field echoes) MUST
go through `_escape()` -- this module has no other XSS defense.
"""

from __future__ import annotations

import html


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


_STYLE = """
  :root {
    color-scheme: light dark;
    --color-bg: #f7f7f8;
    --color-surface: #ffffff;
    --color-border: #e2e2e6;
    --color-text: #17171b;
    --color-text-muted: #5b5b66;
    --color-accent: #3454d1;
    --color-accent-hover: #2c47b3;
    --color-danger: #c0293c;
    --color-danger-muted: #fbeaec;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --color-bg: #101014;
      --color-surface: #17171c;
      --color-border: #2b2b33;
      --color-text: #f2f2f5;
      --color-text-muted: #a8a8b3;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--color-bg);
    color: var(--color-text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    display: flex;
    min-height: 100vh;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
  .card {
    width: 100%;
    max-width: 360px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 12px;
    padding: 32px;
  }
  h1 { font-size: 18px; margin: 0 0 20px; }
  label { display: block; font-size: 13px; color: var(--color-text-muted); margin: 12px 0 4px; }
  input[type=text], input[type=password], input[type=email] {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid var(--color-border);
    border-radius: 8px;
    background: var(--color-bg);
    color: var(--color-text);
    font-size: 14px;
  }
  button {
    width: 100%;
    margin-top: 20px;
    padding: 10px 12px;
    border: none;
    border-radius: 8px;
    background: var(--color-accent);
    color: #fff;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
  }
  button:hover { background: var(--color-accent-hover); }
  button.secondary {
    background: transparent;
    color: var(--color-accent);
    border: 1px solid var(--color-border);
    margin-top: 8px;
  }
  .error {
    background: var(--color-danger-muted);
    color: var(--color-danger);
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 13px;
    margin-bottom: 12px;
  }
  .hint { font-size: 12px; color: var(--color-text-muted); margin-top: 16px; }
"""


def _page(*, title: str, body: str, script: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{_escape(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="card">
{body}
</div>
{script}
</body>
</html>"""


def render_login_page(
    *, brand_name: str, action: str, csrf_token: str, error: str | None = None
) -> str:
    error_html = f'<div class="error" role="alert">{_escape(error)}</div>' if error else ""
    return _page(
        title=f"Sign in - {brand_name}",
        body=f"""
<h1>Sign in to {_escape(brand_name)}</h1>
{error_html}
<form method="post" action="{_escape(action)}" autocomplete="off">
  <input type="hidden" name="csrf_token" value="{_escape(csrf_token)}">
  <label for="login_name">Email or username</label>
  <input type="text" id="login_name" name="login_name" required autofocus
         autocapitalize="off" autocorrect="off" inputmode="email">
  <label for="password">Password</label>
  <input type="password" id="password" name="password" required autocomplete="current-password">
  <button type="submit">Continue</button>
</form>
<p class="hint">You are signing in to {_escape(brand_name)}. This page is served by
{_escape(brand_name)}, not by the identity provider.</p>
""",
    )


def render_totp_page(
    *, brand_name: str, action: str, csrf_token: str, error: str | None = None
) -> str:
    error_html = f'<div class="error" role="alert">{_escape(error)}</div>' if error else ""
    return _page(
        title=f"Verification code - {brand_name}",
        body=f"""
<h1>Enter your verification code</h1>
{error_html}
<form method="post" action="{_escape(action)}" autocomplete="off">
  <input type="hidden" name="csrf_token" value="{_escape(csrf_token)}">
  <label for="code">6-digit code from your authenticator app</label>
  <input type="text" id="code" name="code" required inputmode="numeric" pattern="[0-9]*"
         autocomplete="one-time-code" autofocus maxlength="8">
  <button type="submit">Verify</button>
</form>
""",
    )


def render_webauthn_page(
    *, brand_name: str, csrf_token: str, options_url: str, verify_url: str, error: str | None = None
) -> str:
    if error:
        error_html = f'<div class="error" role="alert" id="webauthn-error">{_escape(error)}</div>'
    else:
        error_html = (
            '<div class="error" role="alert" id="webauthn-error" style="display:none"></div>'
        )
    # base64url <-> ArrayBuffer helpers are standard WebAuthn-client
    # boilerplate (not a homemade cryptographic verifier -- ZITADEL's own
    # Session API performs the actual assertion verification server-side
    # once this JSON is posted back to /webauthn/verify).
    script = f"""
<script>
function b64urlToBuf(s) {{
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  const bin = atob(s);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}}
function bufToB64url(buf) {{
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
}}
async function runWebAuthn() {{
  const errorEl = document.getElementById('webauthn-error');
  try {{
    const optsResp = await fetch({options_url!r}, {{credentials: 'same-origin'}});
    if (!optsResp.ok) throw new Error('could not start verification');
    const opts = await optsResp.json();
    const publicKey = opts.publicKey || opts;
    publicKey.challenge = b64urlToBuf(publicKey.challenge);
    if (publicKey.allowCredentials) {{
      publicKey.allowCredentials = publicKey.allowCredentials.map(
        c => ({{...c, id: b64urlToBuf(c.id)}})
      );
    }}
    const assertion = await navigator.credentials.get({{publicKey}});
    const assertionJson = {{
      id: assertion.id,
      rawId: bufToB64url(assertion.rawId),
      type: assertion.type,
      response: {{
        authenticatorData: bufToB64url(assertion.response.authenticatorData),
        clientDataJSON: bufToB64url(assertion.response.clientDataJSON),
        signature: bufToB64url(assertion.response.signature),
        userHandle: assertion.response.userHandle
          ? bufToB64url(assertion.response.userHandle) : null
      }}
    }};
    const verifyResp = await fetch({verify_url!r}, {{
      method: 'POST',
      credentials: 'same-origin',
      headers: {{'Content-Type': 'application/json', 'X-Ceremony-CSRF': {csrf_token!r}}},
      body: JSON.stringify(assertionJson)
    }});
    const result = await verifyResp.json();
    if (verifyResp.ok && result.redirect) {{
      window.location = result.redirect;
    }} else {{
      errorEl.textContent = result.error || 'Verification failed.';
      errorEl.style.display = 'block';
    }}
  }} catch (e) {{
    errorEl.textContent = 'Your browser could not complete the security key/passkey check.';
    errorEl.style.display = 'block';
  }}
}}
</script>
"""
    return _page(
        title=f"Security key - {brand_name}",
        body=f"""
<h1>Confirm with your security key or passkey</h1>
{error_html}
<button type="button" onclick="runWebAuthn()">Use security key / passkey</button>
""",
        script=script,
    )


def render_error_page(*, brand_name: str, message: str, status_hint: str = "") -> str:
    return _page(
        title=f"Sign-in problem - {brand_name}",
        body=f"""
<h1>We couldn't sign you in</h1>
<div class="error" role="alert">{_escape(message)}</div>
<p class="hint">{_escape(status_hint)}</p>
""",
    )
