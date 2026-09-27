"""Focused tests for `app/templates.py`'s F-11 fix: values embedded into
the WebAuthn page's inline `<script>` must be serialized via
`json.dumps()`, not Python `repr()`.
"""

from __future__ import annotations

import json

from app.templates import render_webauthn_page


def test_webauthn_page_uses_json_serialization_not_python_repr_for_js_values():
    """Uses a value containing a double quote -- a case where Python
    `repr()` and JSON string serialization produce materially different
    text: `repr()` picks a single-quote delimiter and leaves the double
    quote unescaped (`'tok"en'`), while JSON always uses a double-quote
    delimiter and must escape it (`"tok\\"en"`). Asserts the rendered
    page contains the JSON form and never the `repr()` form, for all
    three F-11 interpolation sites (options_url, verify_url, csrf_token)."""
    options_url = '/login-svc/login/webauthn/options?x="tainted"'
    verify_url = '/login-svc/login/webauthn/verify?y="tainted"'
    csrf_token = 'tok"en'

    html_out = render_webauthn_page(
        brand_name="Test",
        csrf_token=csrf_token,
        options_url=options_url,
        verify_url=verify_url,
    )

    for value in (options_url, verify_url, csrf_token):
        json_form = json.dumps(value)
        python_repr_form = repr(value)
        # Sanity check: this synthetic value actually exercises a case
        # where the two serializations differ -- otherwise the assertions
        # below would pass trivially without proving anything.
        assert python_repr_form != json_form
        assert json_form in html_out
        assert python_repr_form not in html_out


def test_webauthn_page_still_renders_plain_values_correctly():
    """Existing, unexploitable-but-still-correct values continue to round-
    trip through JSON serialization unchanged -- F-11 must not alter the
    actual runtime values for today's constrained inputs."""
    options_url = "/login-svc/login/webauthn/options"
    verify_url = "/login-svc/login/webauthn/verify"
    csrf_token = "abc123"

    html_out = render_webauthn_page(
        brand_name="Test",
        csrf_token=csrf_token,
        options_url=options_url,
        verify_url=verify_url,
    )

    assert json.dumps(options_url) in html_out
    assert json.dumps(verify_url) in html_out
    assert json.dumps(csrf_token) in html_out
