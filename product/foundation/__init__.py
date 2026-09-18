"""Shared product-level abstractions every other product/<module> may
depend on (BrandingProvider, the product event dispatcher, tenant-scoped
settings helpers, shared value objects). foundation itself must never
import any other product/<module> (docs/ARCHITECTURE.md section 2.2).
Deliberately empty in Phase 1 -- filled in starting Phase 2
(docs/ROADMAP.md)."""
