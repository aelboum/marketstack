"""Composition root: mounts the installed saas-os api.platform
.build_platform_app() (the shared auth/tenant-resolution/RBAC middleware
chain, ADR-0017 in saas-os) plus this product's own middleware, purge
participants, and (starting with the first module that ships one) its
own routers. See product/api/main.py."""
