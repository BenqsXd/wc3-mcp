class ToolError(Exception):
    """An expected, user-facing failure with a stable code and an optional hint."""

    def __init__(self, code: str, message: str, hint: str | None = None, **details):
        super().__init__(message)
        self.code, self.message, self.hint, self.details = code, message, hint, details

    def to_dict(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        if self.details:
            d["details"] = self.details
        return d
