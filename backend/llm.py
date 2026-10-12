"""Errors shared by the brain integrations."""


class LLMError(Exception):
    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind
