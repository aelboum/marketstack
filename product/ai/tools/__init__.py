"""Tool definitions (docs/ROADMAP.md Phase 9.1/9.3) -- one module per
tool, each exposing a `build_<name>_tool(provider: LLMProvider) ->
ToolDefinition` factory. See `product/ai/__init__.py`'s own module
docstring for why none of these are registered into
`control_plane.orchestration.default_registry()` by this codebase today.
"""
