from dataclasses import dataclass, asdict
from typing import Any
import json

@dataclass
class ToolResult:
    success: bool
    tool: str
    message: str = ""
    data: Any = None
    error: str | None = None
    requires_confirmation: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)
