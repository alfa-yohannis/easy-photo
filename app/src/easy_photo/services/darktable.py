"""Developing raw files with darktable-cli."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import cv2
import numpy as np


class DarktableError(Exception):
    """Raised when darktable-cli cannot develop a file."""


class DarktableRenderer:
    """Develops raw files with darktable-cli, from the raw data at full size.

    darktable-cli runs with its own empty settings folder and a library that
    only lives in memory, so it never changes the user's darktable library or
    sidecar files. It runs one file at a time and at low priority, so the
    computer stays usable during a long export.

    darktable writes the developed photo as a 16-bit PNG file in a temporary
    folder. The app reads it back, refines it, and compresses it only once,
    into the exported JPEG; a JPEG from darktable would be compressed twice.
    """

    WINDOWS_PATH = Path("C:/Program Files/darktable/bin/darktable-cli.exe")
    TIMEOUT_SECONDS = 300
    LOW_PRIORITY = "10"
    """The "nice" level darktable-cli runs at on Linux and macOS (0 is normal, 19 the lowest)."""

    def __init__(self, executable: Path | None) -> None:
        """Create a renderer.

        Args:
            executable: The darktable-cli program, or None when it is not installed.
        """
        self._executable = executable
        self._one_at_a_time = threading.Lock()

    @classmethod
    def locate(cls, configured: str) -> DarktableRenderer:
        """Find darktable-cli: the configured path, the PATH, or the usual Windows folder.

        Args:
            configured: Path set by the user; empty to search.

        Returns:
            A renderer; check :attr:`available` before using it.
        """
        if configured:
            path = Path(configured)
            existing = path if path.exists() else None
            return cls(existing)
        found = shutil.which("darktable-cli")
        if found:
            found_path = Path(found)
            return cls(found_path)
        if cls.WINDOWS_PATH.exists():
            return cls(cls.WINDOWS_PATH)
        return cls(None)

    @property
    def available(self) -> bool:
        """True when darktable-cli was found."""
        return self._executable is not None

    def sidecar_for(self, raw: Path) -> Path | None:
        """Find the darktable sidecar file of a raw file.

        Args:
            raw: The raw file, such as P1199075.RW2.

        Returns:
            Its sidecar (P1199075.RW2.xmp), or None when there is none.
        """
        candidate = raw.with_name(f"{raw.name}.xmp")
        if candidate.exists():
            return candidate
        return None

    def render(self, source: Path, edit_text: str | None, max_side: int, high_quality: bool = True) -> np.ndarray:
        """Develop a raw file.

        Args:
            source: The raw file.
            edit_text: A darktable edit to apply, as XMP text (see
                :class:`~easy_photo.services.darktable_edit.DarktableEdit`).
                None develops the file with its own sidecar when it has one,
                and with darktable's defaults when it has none; darktable-cli
                reads a sidecar next to the file by itself.
            max_side: Longest side of the result.
            high_quality: Develop at full size and shrink at the end. False
                shrinks early, which is faster and good enough for previews.

        Returns:
            RGB values from 0 to 1 (float32), in sRGB.

        Raises:
            DarktableError: When darktable-cli is missing or fails.
        """
        if self._executable is None:
            raise DarktableError("darktable-cli is not installed.")
        with tempfile.TemporaryDirectory() as folder_text:
            folder = Path(folder_text)
            output = folder / "render.png"
            config = folder / "config"
            sidecar = None
            if edit_text is not None:
                sidecar = folder / "edit.xmp"
                sidecar.write_text(edit_text, encoding="utf-8")
            command = self._command(source, sidecar, output, config, max_side, high_quality)
            with self._one_at_a_time:
                self._run(command, source, output)
            return self._read_values(output, source)

    def _run(self, command: list[str], source: Path, output: Path) -> None:
        """Run darktable-cli and check that it wrote the photo.

        Args:
            command: The command line.
            source: The raw file, for error messages.
            output: The file darktable-cli should write.

        Raises:
            DarktableError: When darktable-cli does not run or writes nothing.
        """
        flags = self._window_flags()
        try:
            finished = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.TIMEOUT_SECONDS,
                creationflags=flags,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DarktableError(f"darktable-cli did not run: {error}") from error
        if finished.returncode != 0 or not output.exists():
            reason = self._last_line(finished.stderr)
            message = f"darktable-cli could not develop {source.name}. {reason}"
            cleaned = message.strip()
            raise DarktableError(cleaned)

    def _read_values(self, output: Path, source: Path) -> np.ndarray:
        """Read the photo darktable-cli wrote.

        The file is read into memory and decoded there, so folder names with
        any characters work on every system.

        Args:
            output: The 16-bit PNG file.
            source: The raw file, for error messages.

        Returns:
            RGB values from 0 to 1 (float32).

        Raises:
            DarktableError: When the file cannot be decoded.
        """
        data = output.read_bytes()
        buffer = np.frombuffer(data, dtype=np.uint8)
        decoded = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)
        if decoded is None or decoded.ndim != 3:
            raise DarktableError(f"darktable-cli wrote a picture of {source.name} that cannot be read.")
        peak = 65535.0 if decoded.dtype == np.uint16 else 255.0
        blue_green_red = decoded[:, :, :3]
        red_green_blue = blue_green_red[:, :, ::-1]
        values = red_green_blue.astype(np.float32)
        values /= peak
        return values

    def _command(
        self,
        source: Path,
        sidecar: Path | None,
        output: Path,
        config: Path,
        max_side: int,
        high_quality: bool,
    ) -> list[str]:
        """The darktable-cli command line.

        Args:
            source: The raw file.
            sidecar: The sidecar with the edit, or None for the file's own sidecar or darktable's defaults.
            output: The PNG file to write.
            config: An empty settings folder for this run.
            max_side: Longest side of the result.
            high_quality: Develop at full size and shrink at the end.

        Returns:
            The program and its arguments.
        """
        program = str(self._executable)
        source_text = str(source)
        output_text = str(output)
        config_text = str(config)
        side = str(max_side)
        quality_text = "true" if high_quality else "false"
        command = self._priority_prefix()
        command.append(program)
        command.append(source_text)
        if sidecar is not None:
            sidecar_text = str(sidecar)
            command.append(sidecar_text)
        command.extend(
            [
                output_text,
                "--width",
                side,
                "--height",
                side,
                "--hq",
                quality_text,
                "--core",
                "--configdir",
                config_text,
                "--library",
                ":memory:",
                "--conf",
                "write_sidecar_files=never",
                "--conf",
                "plugins/imageio/format/png/bpp=16",
                "--conf",
                "plugins/imageio/format/png/compression=0",
            ]
        )
        return command

    def _priority_prefix(self) -> list[str]:
        """The start of the command line that lowers darktable-cli's priority on Linux and macOS.

        Returns:
            ["nice", "-n", "10"] when the nice program is there; an empty list on
            Windows, where :meth:`_window_flags` lowers the priority instead.
        """
        if sys.platform == "win32":
            return []
        nice = shutil.which("nice")
        if nice is None:
            return []
        return [nice, "-n", self.LOW_PRIORITY]

    def _window_flags(self) -> int:
        """Flags that hide the console window and lower the priority on Windows.

        Returns:
            The flags for subprocess; 0 on other systems.
        """
        if sys.platform == "win32":
            return subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        return 0

    def _last_line(self, text: str | None) -> str:
        """The last line of darktable-cli's messages, which usually says what went wrong.

        Args:
            text: Everything darktable-cli wrote to its error output.

        Returns:
            The last line that is not empty, or an empty text.
        """
        if not text:
            return ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""
        return lines[-1]
