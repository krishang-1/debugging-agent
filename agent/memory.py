"""Short-term memory for a single agent attempt — the running history passed to each model
call. Episodic (cross-attempt) memory via a database is deferred until full benchmark
evaluations are actually running; wiring real infra before it's needed would be premature.
"""

from dataclasses import dataclass, field


@dataclass
class AttemptMemory:
    """Accumulates everything said and observed during one debugging attempt, in order."""
    turns: list[dict] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        """Appends one turn. role is 'assistant' for the model's thought/action, 'observation' for tool output."""
        self.turns.append({"role": role, "content": content})

    def as_transcript(self) -> str:
        """Renders the full history as plain text, for feeding back into the next model call."""
        return "\n\n".join(f"[{t['role']}] {t['content']}" for t in self.turns)
