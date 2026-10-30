"""A record of the user's choices, kept across projects."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class HistoryLog:
    """Keeps the user's choices in a file with one JSON object per line.

    The record grows across sessions and projects: which photos the user set
    aside or kept against the app's advice, which refinement they picked, and
    what they typed. It is the user's selection history that later versions of
    the app can learn from.
    """

    def __init__(self, path: Path) -> None:
        """Create the log.

        Args:
            path: The log file. It is created with the first record.
        """
        self._path = path

    @property
    def path(self) -> Path:
        """The log file."""
        return self._path

    def record(self, kind: str, details: dict) -> None:
        """Add one record.

        Args:
            kind: What happened, such as "decision" or "pick".
            details: Facts about it, such as the photo and the decision.
        """
        now = datetime.now()
        entry = {"time": now.isoformat(timespec="seconds"), "kind": kind}
        entry.update(details)
        line = json.dumps(entry, ensure_ascii=False)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def entries(self) -> list[dict]:
        """Read all records.

        Returns:
            The records, oldest first. Lines that cannot be read are skipped.
        """
        if not self._path.exists():
            return []
        entries: list[dict] = []
        text = self._path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entries.append(entry)
        return entries
