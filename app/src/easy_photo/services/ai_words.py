"""Reading a refinement described in the user's own words with Claude, through the Claude Code CLI."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from easy_photo.refinement.steps import RefinementStep, StepCatalog


class AiWordsError(Exception):
    """Raised when Claude cannot be asked, or cannot turn the words into refinement steps."""


class AiLoginNeeded(AiWordsError):
    """Raised when Claude Code is installed but nobody is logged in to it."""


@dataclass(frozen=True)
class LoginStatus:
    """Whether Claude Code is logged in, and to which account."""

    logged_in: bool
    account: str = ""


@dataclass(frozen=True)
class AiReading:
    """What Claude made of the user's words: the steps, and one sentence about them."""

    steps: tuple[RefinementStep, ...]
    explanation: str


@dataclass(frozen=True)
class CommandOutput:
    """What a finished program printed, and how it ended."""

    exit_code: int
    printed: str
    errors: str


class CommandRunner:
    """Runs a program with text on its input and collects what it prints.

    The tests replace it with a stand-in, so they never start Claude Code.
    """

    def run(self, command: list[str], text: str, folder: Path, timeout: float) -> CommandOutput:
        """Run a program and wait for it.

        Args:
            command: The program and its arguments.
            text: Text for the program's input.
            folder: The folder the program runs in.
            timeout: Longest time to wait, in seconds.

        Returns:
            Its exit code and what it printed.

        Raises:
            OSError: When the program cannot be started.
            subprocess.TimeoutExpired: When it takes longer than the timeout.
        """
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        finished = subprocess.run(
            command,
            input=text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=folder,
            timeout=timeout,
            creationflags=flags,
            check=False,
        )
        return CommandOutput(finished.returncode, finished.stdout, finished.stderr)

    def start_window(self, command: list[str]) -> None:
        """Start a program that opens its own window, such as a terminal, without waiting for it.

        Args:
            command: The program and its arguments.

        Raises:
            OSError: When the program cannot be started.
        """
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ClaudeCodeLogin:
    """Tells whether Claude Code is logged in, and opens a terminal window where the user logs in.

    Logging in happens in Claude Code itself (``claude auth login``): it opens
    the browser to sign in to the user's Claude account, and the terminal
    window shows a code to paste when the browser cannot reach it. The app
    never sees the user's credentials.
    """

    STATUS_TIMEOUT_SECONDS = 30.0

    LINUX_TERMINALS = (
        ("x-terminal-emulator", "-e"),
        ("gnome-terminal", "--"),
        ("konsole", "-e"),
        ("xfce4-terminal", "-x"),
        ("xterm", "-e"),
    )
    """Terminal programs to try on Linux, each with the option after which the command follows."""

    def __init__(self, program: Path | None, runner: CommandRunner) -> None:
        """Create the login helper.

        Args:
            program: The claude program, or None when Claude Code is not installed.
            runner: Runs the program; tests pass a stand-in.
        """
        self._program = program
        self._runner = runner

    def status(self) -> LoginStatus:
        """Ask Claude Code whether it is logged in (``claude auth status --json``).

        Returns:
            The status; not logged in when Claude Code is missing or does not answer.
        """
        if self._program is None:
            return LoginStatus(False)
        program = str(self._program)
        command = [program, "auth", "status", "--json"]
        with tempfile.TemporaryDirectory() as folder_text:
            folder = Path(folder_text)
            try:
                output = self._runner.run(command, "", folder, self.STATUS_TIMEOUT_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                return LoginStatus(False)
        try:
            answer = json.loads(output.printed)
        except json.JSONDecodeError:
            return LoginStatus(False)
        if not isinstance(answer, dict):
            return LoginStatus(False)
        logged_in = answer.get("loggedIn") is True
        account = answer.get("email") or answer.get("orgName") or ""
        return LoginStatus(logged_in, f"{account}")

    def open_login_window(self) -> None:
        """Open a terminal window that runs ``claude auth login`` and stays open until the user presses Enter.

        Raises:
            AiWordsError: When Claude Code is missing, or no terminal program can be started.
        """
        if self._program is None:
            raise AiWordsError(AiWordsReader.NOT_INSTALLED)
        command = self._terminal_command()
        if command is None:
            program = str(self._program)
            raise AiWordsError(f"No terminal program was found. Open a terminal and run: {program} auth login")
        try:
            self._runner.start_window(command)
        except OSError as error:
            raise AiWordsError(f"The terminal window could not be opened: {error}") from error

    def _terminal_command(self) -> list[str] | None:
        """The command that opens a terminal window running the login.

        Returns:
            The command, or None when no known terminal program is installed.
        """
        program = str(self._program)
        if sys.platform == "win32":
            return ["cmd.exe", "/c", "start", "Claude Code login", "cmd.exe", "/k", program, "auth", "login"]
        quoted = shlex.quote(program)
        script = f"{quoted} auth login; echo; printf 'Press Enter to close this window. '; read -r _"
        for name, run_option in self.LINUX_TERMINALS:
            terminal = shutil.which(name)
            if terminal:
                return [terminal, run_option, "sh", "-c", script]
        return None


class AiWordsReader:
    """Asks Claude to turn a refinement described in the user's own words into refinement steps.

    The app runs Claude Code's command line program, ``claude``, in print mode,
    so Claude answers with the user's own Claude login and no API key is
    needed. Only the words are sent, never the photos. The run is kept bare:
    no tools, no MCP servers, no user settings or hooks, an empty working
    folder, and no saved session. Claude answers with JSON that Claude Code
    checks against a fixed schema (``--json-schema``): a list of steps, each
    of a kind the app knows, with an amount. The app checks the answer again,
    and each step keeps its amount within its own range.
    """

    DEFAULT_MODEL = "claude-opus-5-5"
    MODELS = (
        ("claude-opus-5-5", "Claude Opus 5.5 (best)"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
        ("claude-haiku-5-5", "Claude Haiku 5.5 (fastest, uses the least of your plan)"),
    )
    """The models the user can choose, with their names for the window."""

    TIMEOUT_SECONDS = 120.0
    EFFORT = "low"
    """Reading a short request needs little thinking; low effort keeps the answer quick."""

    PROGRAM_NAME = "claude"
    WINDOWS_NAMES = ("claude.exe", "claude.cmd")

    STEP_KINDS = (
        "exposure",
        "contrast",
        "shadows",
        "highlights",
        "saturation",
        "warmth",
        "neutral_colors",
        "face_brightness",
    )

    NOT_INSTALLED = (
        "Claude Code (the claude command) was not found. Install it from claude.com/claude-code "
        "and run claude once to log in."
    )

    LOGIN_NEEDED = "Claude Code is not logged in yet, so Claude cannot read your words."

    SYSTEM_PROMPT = (
        "You turn a photographer's request, written in their own words, into adjustments for a photo app. "
        "The app can only make these adjustments to the whole photo, each with an amount:\n"
        "- exposure: brightness of the whole photo in stops, from -3 to 3; 0.3 is a small step.\n"
        "- contrast: in percent, from -100 to 100; 20 is a clear step.\n"
        "- shadows: brightens (positive) or deepens (negative) the dark tones, from -1 to 1.5.\n"
        "- highlights: brightens (positive) or tones down (negative) the bright tones, from -1.5 to 1.\n"
        "- saturation: color strength in percent, from -100 (black and white) to 100.\n"
        "- warmth: in percent, from -30 (cooler, bluer) to 30 (warmer, more orange).\n"
        "- neutral_colors: removes a color cast so the photo is neither warm nor cool, "
        "from 0 to 1 (1 removes it fully).\n"
        "- face_brightness: changes the whole photo so the faces get brighter or darker, in stops, from -2 to 2.\n\n"
        "Use as few adjustments as the request needs, in the order they should be applied, with moderate "
        "amounts unless the request asks for strong ones. Do not change colors the request does not mention. "
        "If the request needs something these adjustments cannot do, such as removing an object or cropping, "
        "set understood to false and say why in the explanation. Write the explanation as one short sentence "
        "in the language of the request."
    )

    SCHEMA = {
        "type": "object",
        "properties": {
            "understood": {"type": "boolean"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(STEP_KINDS)},
                        "amount": {"type": "number"},
                    },
                    "required": ["kind", "amount"],
                    "additionalProperties": False,
                },
            },
            "explanation": {"type": "string"},
        },
        "required": ["understood", "steps", "explanation"],
        "additionalProperties": False,
    }
    """The JSON schema Claude's answer must follow."""

    def __init__(
        self,
        catalog: StepCatalog,
        program: Path | None,
        model: str = DEFAULT_MODEL,
        runner: CommandRunner | None = None,
    ) -> None:
        """Create a reader.

        Args:
            catalog: Turns the steps in Claude's answer into step objects.
            program: The claude program, or None when Claude Code is not installed.
            model: The Claude model to ask.
            runner: Runs the program; tests pass a stand-in.
        """
        self._catalog = catalog
        self._program = program
        self._model = model
        self._runner = runner or CommandRunner()
        self._login = ClaudeCodeLogin(program, self._runner)

    @classmethod
    def locate(cls, catalog: StepCatalog, configured: str, model: str) -> AiWordsReader:
        """Make a reader with the claude program found on this computer.

        The program is looked for at the configured path, on the PATH, and in
        the folder Claude Code's installer uses (``~/.local/bin``), since an
        app started from the desktop may not get the shell's PATH.

        Args:
            catalog: Turns the steps in Claude's answer into step objects.
            configured: Path set by the user; empty to search.
            model: The Claude model to ask.

        Returns:
            The reader; check :attr:`available` before using it.
        """
        program = cls._find_program(configured)
        return cls(catalog, program, model)

    @property
    def model(self) -> str:
        """The Claude model the reader asks."""
        return self._model

    @property
    def program(self) -> Path | None:
        """The claude program, or None when it was not found."""
        return self._program

    @property
    def available(self) -> bool:
        """True when the claude program was found."""
        return self._program is not None

    @property
    def login(self) -> ClaudeCodeLogin:
        """Tells whether Claude Code is logged in, and opens the login window."""
        return self._login

    def read(self, text: str) -> AiReading:
        """Ask Claude to read a refinement described in words.

        Args:
            text: What the user typed, such as "neutral, not warm, not cool".

        Returns:
            The steps and Claude's one-sentence explanation.

        Raises:
            AiLoginNeeded: When Claude Code is installed but not logged in.
            AiWordsError: When Claude cannot be reached, declines, or finds nothing it can do.
        """
        cleaned = text.strip()
        if not cleaned:
            raise AiWordsError("Type what you would like to change.")
        if self._program is None:
            raise AiWordsError(self.NOT_INSTALLED)
        answer = self._ask(cleaned)
        return self._reading_from(answer)

    @classmethod
    def _find_program(cls, configured: str) -> Path | None:
        """Find the claude program.

        Args:
            configured: Path set by the user; empty to search.

        Returns:
            The program, or None when it is not there.
        """
        if configured:
            path = Path(configured)
            return path if path.exists() else None
        found = shutil.which(cls.PROGRAM_NAME)
        if found:
            return Path(found)
        names = cls.WINDOWS_NAMES if sys.platform == "win32" else (cls.PROGRAM_NAME,)
        installer_folder = Path.home() / ".local" / "bin"
        for name in names:
            candidate = installer_folder / name
            if candidate.exists():
                return candidate
        return None

    def _command(self) -> list[str]:
        """The command line that asks Claude Code; the words go to its input.

        Returns:
            The program and its arguments.
        """
        program = str(self._program)
        schema_text = json.dumps(self.SCHEMA)
        return [
            program,
            "--print",
            "--output-format",
            "json",
            "--json-schema",
            schema_text,
            "--model",
            self._model,
            "--effort",
            self.EFFORT,
            "--system-prompt",
            self.SYSTEM_PROMPT,
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "project",
            "--no-session-persistence",
        ]

    def _ask(self, text: str) -> dict:
        """Send the words to Claude through Claude Code and return the JSON answer.

        Claude Code runs in an empty temporary folder, so no project settings,
        CLAUDE.md file or memory of a folder comes along.

        Args:
            text: The cleaned words.

        Returns:
            The answer, as a dictionary that follows :attr:`SCHEMA`.

        Raises:
            AiWordsError: When Claude Code cannot be run or its answer cannot be used.
        """
        command = self._command()
        with tempfile.TemporaryDirectory() as folder_text:
            folder = Path(folder_text)
            try:
                output = self._runner.run(command, text, folder, self.TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as error:
                raise AiWordsError("Claude did not answer in time. Try again later.") from error
            except OSError as error:
                raise AiWordsError(f"Claude Code could not be started: {error}") from error
        return self._answer_from(output)

    def _answer_from(self, output: CommandOutput) -> dict:
        """Take the JSON answer out of what Claude Code printed.

        With ``--output-format json``, Claude Code prints one JSON object; the
        answer checked against the schema is in its "structured_output".

        Args:
            output: What Claude Code printed.

        Returns:
            The answer as a dictionary.

        Raises:
            AiLoginNeeded: When Claude Code failed because nobody is logged in.
            AiWordsError: When Claude Code failed otherwise, Claude declined, or the answer cannot be read.
        """
        try:
            result = json.loads(output.printed)
        except json.JSONDecodeError as error:
            self._check_login()
            reason = self._last_line(output.errors)
            raise AiWordsError(f"Claude Code did not answer. {reason}") from error
        if not isinstance(result, dict):
            raise AiWordsError("Claude Code's answer could not be read.")
        if result.get("is_error") or output.exit_code != 0:
            self._check_login()
            message = result.get("result") or result.get("subtype") or "an unknown error"
            raise AiWordsError(f"Claude Code could not answer: {message}")
        if result.get("stop_reason") == "refusal":
            raise AiWordsError("Claude declined to read these words.")
        answer = result.get("structured_output")
        if not isinstance(answer, dict):
            raise AiWordsError("Claude's answer could not be read.")
        return answer

    def _check_login(self) -> None:
        """After Claude Code failed, find out whether a missing login is the reason.

        Raises:
            AiLoginNeeded: When Claude Code says nobody is logged in.
        """
        status = self._login.status()
        if not status.logged_in:
            raise AiLoginNeeded(self.LOGIN_NEEDED)

    def _reading_from(self, answer: dict) -> AiReading:
        """Turn Claude's JSON answer into steps.

        Args:
            answer: The answer, following :attr:`SCHEMA`.

        Returns:
            The steps and the explanation.

        Raises:
            AiWordsError: When Claude did not understand the request or found nothing to change.
        """
        explanation_value = answer.get("explanation", "")
        explanation = explanation_value if isinstance(explanation_value, str) else ""
        if not answer.get("understood", False):
            raise AiWordsError(explanation or "Claude could not turn these words into a refinement.")
        steps: list[RefinementStep] = []
        for item in answer.get("steps", []):
            step = self._step_from(item)
            if step is not None:
                steps.append(step)
        if not steps:
            raise AiWordsError(explanation or "Claude found nothing to change.")
        step_tuple = tuple(steps)
        return AiReading(step_tuple, explanation)

    def _step_from(self, item: object) -> RefinementStep | None:
        """Make one step from an entry of Claude's answer.

        Args:
            item: One entry of the "steps" list.

        Returns:
            The step, or None when the entry is not a known kind with a number.
        """
        if not isinstance(item, dict):
            return None
        kind = item.get("kind")
        amount = item.get("amount")
        if kind not in self.STEP_KINDS or not isinstance(amount, (int, float)):
            return None
        data = {"kind": kind, "amount": amount}
        return self._catalog.load(data)

    def _last_line(self, text: str) -> str:
        """The last line Claude Code wrote to its error output, which usually says what went wrong.

        Args:
            text: Everything it wrote there.

        Returns:
            The last line that is not empty, or an empty text.
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        return lines[-1]
