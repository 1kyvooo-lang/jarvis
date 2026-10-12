"""Extensible tool registry with schema validation and permission checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import jsonschema


class ToolError(Exception):
    """A tool refused or failed. The message is safe to show the user and Claude."""


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], Any]
    sensitive: bool = False       # always requires explicit user approval
    timeout: float = 20.0
    category: str = "general"
    mac_only: bool = False


@dataclass
class Registry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"duplicate tool {tool.name}")
        schema = dict(tool.input_schema)
        schema.setdefault("type", "object")
        schema.setdefault("additionalProperties", False)
        tool.input_schema = schema
        jsonschema.Draft202012Validator.check_schema(schema)
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise ToolError(f"Unknown tool '{name}'")
        return self.tools[name]

    def validate(self, name: str, args: dict) -> Tool:
        tool = self.get(name)
        if not isinstance(args, dict):
            raise ToolError("Tool arguments must be an object")
        try:
            jsonschema.validate(args, tool.input_schema)
        except jsonschema.ValidationError as e:
            raise ToolError(f"Invalid arguments for {name}: {e.message}") from None
        return tool

    def describe(self, permissions: dict) -> list[dict]:
        out = []
        for t in self.tools.values():
            out.append({
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "category": t.category,
                "sensitive": t.sensitive,
                "requires_approval": t.sensitive or t.name in permissions.get("approval_required", []),
                "enabled": t.name not in permissions.get("disabled_tools", []),
                "mac_only": t.mac_only,
            })
        return out


registry = Registry()


def tool(**kwargs):
    """Decorator: @tool(name=..., description=..., input_schema=...)."""
    def wrap(fn):
        registry.register(Tool(handler=fn, **kwargs))
        return fn
    return wrap
