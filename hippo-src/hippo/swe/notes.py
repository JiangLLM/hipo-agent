"""File-keyed mechanism notes — v2 memory organized around the codebase, not tasks.

The align-settings postmortem found three failures of task-keyed memory: the right
knowledge existed but was scattered across a task-similarity index (never retrieved),
injected at task start (60+ steps before the decision point), and lacked sub-file
anchors. This module fixes the organization and timing:

  * unit   = a short verified fact about how a specific file/class/method behaves
  * key    = the file path (with a class/method anchor inside the note)
  * moment = injected into the observation the FIRST time the agent's command touches
             that file — the knowledge arrives exactly when the agent engages the code.

Storage is a plain JSON dict {file_path: [ {anchor, note}, ... ]}. Exact-key lookup;
no embeddings involved.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


class FileNotes:
    def __init__(self, path: str | Path | None = None):
        self.by_file: dict[str, list[dict]] = {}
        if path:
            self.by_file = json.loads(Path(path).read_text())

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.by_file, indent=1))

    def add(self, file: str, anchor: str, note: str, cap: int = 8) -> bool:
        notes = self.by_file.setdefault(file, [])
        key = " ".join(note.lower().split())[:80]
        if any(" ".join(n["note"].lower().split())[:80] == key for n in notes):
            return False
        if len(notes) >= cap:
            return False
        notes.append({"anchor": anchor, "note": note})
        return True

    def stats(self) -> dict:
        return {"files": len(self.by_file),
                "notes": sum(len(v) for v in self.by_file.values())}


def render_notes(notes: list[dict], file: str, limit_chars: int = 1500) -> str:
    lines = [f"[repo-notes] Things you verified about {file} while fixing past issues here:"]
    total = len(lines[0])
    for n in notes:
        line = f"- ({n['anchor']}) {n['note']}" if n.get("anchor") else f"- {n['note']}"
        if total + len(line) > limit_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


class NotesInjector:
    """Tracks which files' notes have been shown; call `peek(command)` after every
    executed command and append the returned text (if any) to the observation."""

    _PATH = re.compile(r"[\w./-]+\.py")

    def __init__(self, notes: FileNotes):
        self.notes = notes
        self.shown: set[str] = set()

    def peek(self, command: str) -> str:
        hits = []
        for raw in self._PATH.findall(command or ""):
            path = raw.lstrip("/").removeprefix("testbed/")
            if path in self.notes.by_file and path not in self.shown:
                self.shown.add(path)
                hits.append(render_notes(self.notes.by_file[path], path))
        return "\n\n".join(hits)
