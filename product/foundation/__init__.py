"""Shared product-level abstractions every other product/<module> may
depend on: value objects (values.py), tenant-scoped settings
(settings.py, models.py), and the product event dispatcher (events.py)
-- docs/ROADMAP.md Phase 2. `BrandingProvider` itself lives in
product/white_label/ (docs/ARCHITECTURE.md's own module-boundary table),
not here. foundation itself must never import any other product/<module>
(docs/ARCHITECTURE.md section 2.2, enforced by this repository's own
import-linter contract)."""
