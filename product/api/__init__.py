"""Composition root: mounts the installed saas-os api.platform
.build_platform_app() (the shared auth/tenant-resolution/RBAC middleware
chain, ADR-0017 in saas-os) plus this product's own module routers.
Phase 1 mounts no product routers yet -- see product/api/main.py."""
