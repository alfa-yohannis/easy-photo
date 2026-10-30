"""Tests of reading typed refinements with Claude, with a stand-in for Claude Code (no network, no cost)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from easy_photo.refinement.steps import StepCatalog
from easy_photo.services.ai_words import (
    AiLoginNeeded,
    AiWordsError,
    AiWordsReader,
    ClaudeCodeLogin,
    CommandOutput,
    CommandRunner,
)

PROGRAM = Path("/usr/local/bin/claude")


class StandInRunner(CommandRunner):
    """Stands in for running Claude Code: remembers each run and prints prepared results."""

    def __init__(self, result: dict, exit_code: int = 0, logged_in: bool = True) -> None:
        """Prepare the results.

        Args:
            result: The JSON object Claude Code would print with --output-format json.
            exit_code: The exit code it would end with.
            logged_in: What ``claude auth status`` would say.
        """
        self.commands: list[list[str]] = []
        self.inputs: list[str] = []
        self.folders: list[Path] = []
        self.windows: list[list[str]] = []
        self._result = result
        self._exit_code = exit_code
        self._logged_in = logged_in

    def run(self, command: list[str], text: str, folder: Path, timeout: float) -> CommandOutput:
        """Remember the run and return the prepared result, or the login status for ``auth status``.

        Args:
            command: The program and its arguments.
            text: The text on the program's input.
            folder: The folder the program would run in.
            timeout: Longest time to wait (not used).

        Returns:
            The prepared result as printed JSON.
        """
        self.commands.append(command)
        self.inputs.append(text)
        self.folders.append(folder)
        if command[1:3] == ["auth", "status"]:
            status = {"loggedIn": self._logged_in, "email": "someone@example.com"}
            status_text = json.dumps(status)
            return CommandOutput(0, status_text, "")
        printed = json.dumps(self._result)
        return CommandOutput(self._exit_code, printed, "")

    def start_window(self, command: list[str]) -> None:
        """Remember the window that would open.

        Args:
            command: The program and its arguments.
        """
        self.windows.append(command)


def only_xterm(name: str) -> str | None:
    """Stands in for ``shutil.which`` on a computer whose only terminal program is xterm.

    Args:
        name: The program looked for.

    Returns:
        A path for xterm and for nothing else.
    """
    if name == "xterm":
        return "/usr/bin/xterm"
    return None


def success(answer: dict) -> dict:
    """What Claude Code prints when Claude answered with JSON that follows the schema.

    Args:
        answer: Claude's answer.

    Returns:
        Claude Code's result object.
    """
    answer_text = json.dumps(answer)
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "stop_reason": "end_turn",
        "result": answer_text,
        "structured_output": answer,
    }


def make_reader(result: dict) -> tuple[AiWordsReader, StandInRunner]:
    """A reader that runs a stand-in for Claude Code.

    Args:
        result: What the stand-in prints.

    Returns:
        The reader and the stand-in, which keeps the runs.
    """
    runner = StandInRunner(result)
    catalog = StepCatalog()
    reader = AiWordsReader(catalog, PROGRAM, runner=runner)
    return reader, runner


def test_reader_turns_the_answer_into_steps() -> None:
    """The steps in the answer become step objects, with amounts kept in range."""
    answer = {
        "understood": True,
        "steps": [{"kind": "neutral_colors", "amount": 1}, {"kind": "contrast", "amount": -500}],
        "explanation": "Neutral colors, a little softer.",
    }
    result = success(answer)
    reader, _runner = make_reader(result)
    reading = reader.read("neutral, not warm, not cool, soft")
    kinds = [step.KIND for step in reading.steps]
    amounts = [step.amount for step in reading.steps]
    assert kinds == ["neutral_colors", "contrast"]
    assert amounts == [1.0, -100.0]
    assert reading.explanation == "Neutral colors, a little softer."


def test_reader_runs_claude_code_bare_with_the_schema() -> None:
    """Claude Code runs in print mode with the schema and the model, no tools, settings or session.

    The words go to its input, not onto the command line, and it runs in a
    temporary folder that is gone afterwards.
    """
    answer = {"understood": True, "steps": [{"kind": "exposure", "amount": 0.3}], "explanation": "Brighter."}
    result = success(answer)
    reader, runner = make_reader(result)
    reader.read("-0.3 stops? no, a bit brighter please")
    command = runner.commands[0]
    schema_text = command[command.index("--json-schema") + 1]
    schema = json.loads(schema_text)
    assert command[0] == str(PROGRAM)
    assert "--print" in command
    assert command[command.index("--output-format") + 1] == "json"
    assert command[command.index("--model") + 1] == "claude-opus-5-5"
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--setting-sources") + 1] == "project"
    assert "--strict-mcp-config" in command
    assert "--no-session-persistence" in command
    assert schema["required"] == ["understood", "steps", "explanation"]
    assert runner.inputs == ["-0.3 stops? no, a bit brighter please"]
    assert not runner.folders[0].exists()


def test_reader_says_what_claude_cannot_do() -> None:
    """When Claude says the app cannot do it, its explanation becomes the error."""
    answer = {"understood": False, "steps": [], "explanation": "Removing a person needs a retouch tool."}
    result = success(answer)
    reader, _runner = make_reader(result)
    with pytest.raises(AiWordsError, match="retouch"):
        reader.read("remove the man on the left")


def test_reader_reports_what_went_wrong_in_claude_code() -> None:
    """When Claude Code reports an error while logged in, its message reaches the user."""
    result = {"type": "result", "subtype": "success", "is_error": True, "result": "API Error: overloaded"}
    reader, _runner = make_reader(result)
    with pytest.raises(AiWordsError, match="overloaded"):
        reader.read("dramatic")


def test_reader_tells_when_claude_code_needs_a_login() -> None:
    """When Claude Code fails and its status says nobody is logged in, the reader asks for a login."""
    result = {"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in · Please run /login"}
    runner = StandInRunner(result, 1, False)
    catalog = StepCatalog()
    reader = AiWordsReader(catalog, PROGRAM, runner=runner)
    with pytest.raises(AiLoginNeeded):
        reader.read("dramatic")
    status_command = runner.commands[1]
    assert status_command[1:] == ["auth", "status", "--json"]


def test_login_status_and_login_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The login status comes from ``claude auth status``; the login opens ``claude auth login`` in a terminal.

    Args:
        monkeypatch: Pretends xterm is the only terminal program.
    """
    monkeypatch.setattr(shutil, "which", only_xterm)
    result = success({"understood": True, "steps": [], "explanation": ""})
    runner = StandInRunner(result)
    login = ClaudeCodeLogin(PROGRAM, runner)
    status = login.status()
    login.open_login_window()
    window = runner.windows[0]
    joined = " ".join(window)
    assert status.logged_in
    assert status.account == "someone@example.com"
    assert "auth login" in joined
    missing = ClaudeCodeLogin(None, runner)
    missing_status = missing.status()
    assert not missing_status.logged_in
    with pytest.raises(AiWordsError, match="Claude Code"):
        missing.open_login_window()


def test_reader_reports_a_refusal() -> None:
    """A declined request ends in a clear error."""
    result = {"type": "result", "subtype": "success", "is_error": False, "stop_reason": "refusal", "result": ""}
    reader, _runner = make_reader(result)
    with pytest.raises(AiWordsError, match="declined"):
        reader.read("something")


def test_reader_skips_kinds_it_does_not_know() -> None:
    """Steps of an unknown kind are left out; the known ones stay."""
    answer = {
        "understood": True,
        "steps": [{"kind": "dehaze", "amount": 1}, {"kind": "warmth", "amount": -5}],
        "explanation": "",
    }
    result = success(answer)
    reader, _runner = make_reader(result)
    reading = reader.read("clear the haze and cool it a little")
    kinds = [step.KIND for step in reading.steps]
    assert kinds == ["warmth"]


def test_reader_needs_claude_code(tmp_path: Path) -> None:
    """Without the claude program the reader says how to get it, and runs nothing.

    Args:
        tmp_path: Folder for a stand-in program file.
    """
    catalog = StepCatalog()
    missing_path = tmp_path / "missing" / "claude"
    missing_text = str(missing_path)
    missing = AiWordsReader.locate(catalog, missing_text, "claude-haiku-5-5")
    program_path = tmp_path / "claude"
    program_path.write_text("", encoding="utf-8")
    program_text = str(program_path)
    found = AiWordsReader.locate(catalog, program_text, "claude-haiku-5-5")
    assert not missing.available
    assert found.program == program_path
    with pytest.raises(AiWordsError, match="Claude Code"):
        missing.read("dramatic")
