from __future__ import annotations

from dataclasses import dataclass

DEFAULT_BASE_URL = "https://api.openai.com/v1"


@dataclass
class SkillCard:
    name: str
    category: str
    summary: str
    instruction: str
    use_cases: str = ""
    risk_note: str = ""

    def to_record(self) -> dict[str, str]:
        return {
            "name": self.name,
            "category": self.category,
            "summary": self.summary,
            "instruction": self.instruction,
            "use_cases": self.use_cases,
            "risk_note": self.risk_note,
        }
