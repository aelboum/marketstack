"""Vendor-specific `TelephonyProvider` adapters (docs/ROADMAP.md Phase
27.0). Every module under this package owns exactly one vendor's own SDK
imports, request/response shapes, and vocabulary; nothing outside this
package ever imports a vendor-specific type. `product/telephony/provider.py
::TelephonyProvider` is the one shape every adapter here implements --
this package never defines a second, competing provider abstraction of
its own (docs/ROADMAP.md Phase 27.0's own "do not create a generic vendor
abstraction inside the adapter package that duplicates `TelephonyProvider`"
instruction)."""

from __future__ import annotations
