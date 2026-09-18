"""Product layer: the HighLevel-like agency SaaS platform built on top of
SaaS-OS (saas-os package). Every subpackage here is Category C (product-
specific) unless its own docstring says otherwise -- see
docs/RESPONSIBILITY-MATRIX.md. No product/<module> imports another
product/<module> directly (docs/ARCHITECTURE.md section 2.2); only
product.foundation and the installed saas-os package are always-allowed
dependencies."""
