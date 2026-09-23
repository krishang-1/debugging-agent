"""Loader for mutation-testing bugs (layer 2 of the benchmark) - mirrors BugRecord's shape from loader.py."""
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MutationBugRecord:
    bug_id: str
    project: str
    base_commit: str
    category: str
    target_file: str
    target_symbol: str
    test_node: str
    description: str
    patch_file: str
    test_file: str
    bug_type: str = "mutation"

    @property
    def commit_message(self) -> str:
        """Alias for description — lets verifier.py's bug.commit_message access work unchanged."""
        return self.description


def load_mutation_bugs(path: str = "benchmark/mutation_corpus/corpus/mutation_bugs.json") -> list[MutationBugRecord]:
    """Reads mutation_corpus/corpus/mutation_bugs.json into a list of MutationBugRecord."""
    data = json.loads(Path(path).read_text())
    return [MutationBugRecord(**entry) for entry in data]
