"""Automation / workflow builder: trigger/condition/action definitions
specific to this product's domain (pipeline stage changed, form
submitted, invoice overdue, ...). Single-step actions run on the
installed saas-os infra.jobs queue; multi-step/branching/delayed
workflows need a durable engine, evaluated as its own Phase 10.1 spike
(docs/ARCHITECTURE.md section 5)."""
