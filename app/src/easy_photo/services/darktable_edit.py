"""darktable edits read from XMP sidecar files, made ready to apply to other photos.

darktable keeps the edit of a raw file in a sidecar file next to it, such as
P1188493.RW2.xmp. The edit is a history: module settings in the order the
user made them. :class:`DarktableEdit` reads that history and writes a new
sidecar that darktable-cli can apply to any other raw file, without the
settings that only fit the photo the edit was made for.
"""

from __future__ import annotations

import base64
import os
import shutil
import struct
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from easy_photo.model.photo import FileKind, Photo


class DarktableEditError(Exception):
    """Raised when a file holds no darktable edit that can be used."""


@dataclass(frozen=True)
class HistoryEntry:
    """One entry of a darktable history: a module with its settings."""

    operation: str
    """darktable's name of the module, such as "toneequal"."""

    attributes: dict[str, str]
    """Every attribute of the entry under its full XML name, so it can be written back unchanged."""


class DarktableEdit:
    """The history of a darktable edit, without the parts that only fit its own photo.

    Left out are the modules tied to the photo's framing or content (crop,
    perspective, orientation, retouch, spots, liquify), the modules that hold
    values of the photo's own sensor or lens (raw black and white points, lens
    correction), every module that uses a drawn mask, and the entries the user
    undid in darktable. darktable then works those modules out for each photo
    by itself. Applying everything else is what darktable's own "copy" and
    "paste" of a history does.
    """

    RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    DARKTABLE = "http://darktable.sf.net/"
    XMP_META = "adobe:ns:meta/"
    NAMESPACES = {"rdf": RDF, "darktable": DARKTABLE, "x": XMP_META}

    PHOTO_ONLY_OPERATIONS = frozenset(
        {"crop", "clipping", "ashift", "flip", "retouch", "spots", "liquify", "rawprepare", "lens"}
    )
    """Modules whose settings only fit the photo they were made for."""

    DRAWN_MASK = 2
    RASTER_MASK = 8
    """Bits of darktable's mask mode: a mask drawn on the photo, and a mask taken from another module."""

    COPIED_SETTINGS = ("xmp_version", "raw_params", "iop_order_version", "iop_order_list")
    """Attributes of the sidecar that the new sidecar keeps: its format and the order of the modules."""

    PLUMBING = frozenset({"demosaic", "colorin", "colorout", "gamma"})
    """Modules every raw development has; :meth:`describe` does not list them."""

    SET_UP_PER_PHOTO = frozenset({"rawprepare", "flip"})
    """Modules darktable sets up for every photo by itself; :meth:`describe_left_out` does not list them."""

    MODULE_NAMES = {
        "ashift": "rotate and perspective",
        "basecurve": "base curve",
        "bilat": "local contrast",
        "channelmixerrgb": "color calibration",
        "clipping": "crop and rotate",
        "colorbalancergb": "color balance rgb",
        "colorcorrection": "color correction",
        "colorzones": "color zones",
        "filmicrgb": "filmic rgb",
        "graduatednd": "graduated density",
        "hazeremoval": "haze removal",
        "highlights": "highlight reconstruction",
        "lens": "lens correction",
        "rgbcurve": "rgb curve",
        "rgblevels": "rgb levels",
        "spots": "spot removal",
        "temperature": "white balance",
        "toneequal": "tone equalizer",
        "tonecurve": "tone curve",
    }
    """darktable's names of common modules as its window shows them; other modules keep their own name."""

    def __init__(
        self,
        path: Path,
        settings: dict[str, str],
        entries: list[HistoryEntry],
        left_out: list[str],
        changed_by_user: bool = True,
    ) -> None:
        """Create an edit. Use :meth:`read` to read one from a file.

        Args:
            path: The XMP file the edit came from.
            settings: The sidecar attributes the new sidecar keeps, by their short name.
            entries: The history entries that suit other photos, in order.
            left_out: Names of the modules that were left out.
            changed_by_user: False when darktable only added its default modules to the history.
        """
        self._path = path
        self._settings = dict(settings)
        self._entries = list(entries)
        self._left_out = list(left_out)
        self._changed_by_user = changed_by_user

    @classmethod
    def edit_file_for(cls, reference: Path) -> Path | None:
        """The darktable edit that a file chosen as a reference stands for.

        Args:
            reference: A file the user chose as a reference.

        Returns:
            The file itself when it is an XMP file; the sidecar of a raw file
            when the user changed that photo in darktable; otherwise None.
        """
        suffix = reference.suffix.lower()
        if suffix == ".xmp":
            return reference
        kind = FileKind.of(reference)
        if kind is not FileKind.RAW:
            return None
        sidecar = reference.with_name(f"{reference.name}.xmp")
        if not sidecar.exists():
            return None
        try:
            edit = cls.read(sidecar)
        except DarktableEditError:
            return None
        if not edit.changed_by_user:
            return None
        return sidecar

    @classmethod
    def read(cls, path: Path) -> DarktableEdit:
        """Read the edit in a darktable XMP file.

        Args:
            path: The XMP file, such as P1188493.RW2.xmp.

        Returns:
            The edit, without the parts that only fit its own photo.

        Raises:
            DarktableEditError: When the file cannot be read, is not a darktable
                sidecar, or keeps nothing that suits other photos.
        """
        try:
            tree = ElementTree.parse(path)
        except (OSError, ElementTree.ParseError) as error:
            raise DarktableEditError(f"Cannot read {path.name}: {error}") from error
        root = tree.getroot()
        description = root.find(".//rdf:Description", cls.NAMESPACES)
        items = []
        if description is not None:
            items = description.findall("darktable:history/rdf:Seq/rdf:li", cls.NAMESPACES)
        if not items:
            raise DarktableEditError(f"{path.name} is not a darktable edit: it has no darktable history.")
        settings = cls._copied_settings(description)
        end_name = cls.qualified("history_end")
        end_text = description.get(end_name)
        try:
            end = len(items) if end_text is None else int(end_text)
            entries, left_out = cls._sort_entries(items, end)
        except ValueError as error:
            raise DarktableEditError(f"The darktable history in {path.name} cannot be read: {error}") from error
        if not entries:
            raise DarktableEditError(f"{path.name} has no darktable edit that suits other photos.")
        changed_by_user = cls._changed_by_user(description)
        return cls(path, settings, entries, left_out, changed_by_user)

    @classmethod
    def qualified(cls, name: str) -> str:
        """The full XML name of a darktable attribute, as ElementTree writes it.

        Args:
            name: The short name, such as "history_end".

        Returns:
            Text such as "{http://darktable.sf.net/}history_end".
        """
        return "{" + cls.DARKTABLE + "}" + name

    @property
    def path(self) -> Path:
        """The XMP file the edit came from."""
        return self._path

    @property
    def operations(self) -> list[str]:
        """darktable's names of the modules the edit applies, each once, in history order."""
        names: list[str] = []
        for entry in self._entries:
            if entry.operation not in names:
                names.append(entry.operation)
        return names

    @property
    def left_out(self) -> list[str]:
        """Names of the modules that were left out, each once."""
        return list(self._left_out)

    @property
    def changed_by_user(self) -> bool:
        """False when darktable only added its default modules, and the user never edited the photo."""
        return self._changed_by_user

    def describe(self) -> str:
        """List the modules the edit applies, as darktable's window names them.

        Returns:
            Text such as "exposure, filmic rgb, tone equalizer, base curve".
        """
        names = self._window_names(self.operations, self.PLUMBING)
        return ", ".join(names)

    def describe_left_out(self) -> str:
        """List the left-out modules the user may have changed, as darktable's window names them.

        Returns:
            Text such as "crop, retouch"; empty when only modules darktable sets up by itself were left out.
        """
        names = self._window_names(self._left_out, self.SET_UP_PER_PHOTO)
        return ", ".join(names)

    def sidecar_text(self) -> str:
        """The edit as an XMP file that darktable-cli applies to another photo.

        The history is numbered again from 0 and ends after its last entry.
        "auto_presets_applied" tells darktable not to add its default modules
        on top, since the history already holds the modules the user wanted.

        Returns:
            The XMP text.
        """
        self.register_prefixes()
        meta_name = "{" + self.XMP_META + "}xmpmeta"
        root = ElementTree.Element(meta_name)
        rdf_name = self._rdf("RDF")
        rdf = ElementTree.SubElement(root, rdf_name)
        description_name = self._rdf("Description")
        description = ElementTree.SubElement(rdf, description_name)
        about_name = self._rdf("about")
        description.set(about_name, "")
        self.fill_description(description)
        return self.xml_text(root)

    @classmethod
    def register_prefixes(cls) -> None:
        """Make ElementTree write darktable's usual namespace prefixes (x, rdf, darktable)."""
        ElementTree.register_namespace("x", cls.XMP_META)
        ElementTree.register_namespace("rdf", cls.RDF)
        ElementTree.register_namespace("darktable", cls.DARKTABLE)

    @classmethod
    def xml_text(cls, root: ElementTree.Element) -> str:
        """Write a sidecar's XML tree as text, indented, with the XML declaration darktable writes.

        Args:
            root: The x:xmpmeta element.

        Returns:
            The XMP text.
        """
        ElementTree.indent(root)
        body = ElementTree.tostring(root, encoding="unicode")
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'

    def fill_description(self, description: ElementTree.Element) -> None:
        """Put the edit into a sidecar's rdf:Description element, which has no darktable history yet.

        Args:
            description: The element; the edit's settings, history end, history and an empty mask history are added.
        """
        for name, value in self._settings.items():
            full_name = self.qualified(name)
            description.set(full_name, value)
        presets_name = self.qualified("auto_presets_applied")
        description.set(presets_name, "1")
        end_name = self.qualified("history_end")
        count = len(self._entries)
        count_text = str(count)
        description.set(end_name, count_text)
        masks_name = self.qualified("masks_history")
        masks = ElementTree.SubElement(description, masks_name)
        sequence_name = self._rdf("Seq")
        ElementTree.SubElement(masks, sequence_name)
        history_name = self.qualified("history")
        history = ElementTree.SubElement(description, history_name)
        sequence = ElementTree.SubElement(history, sequence_name)
        self._write_entries(sequence)

    @classmethod
    def _copied_settings(cls, description: ElementTree.Element) -> dict[str, str]:
        """Read the sidecar attributes the new sidecar keeps.

        Args:
            description: The sidecar's rdf:Description element.

        Returns:
            The attributes that are present, by their short name.
        """
        settings: dict[str, str] = {}
        for name in cls.COPIED_SETTINGS:
            full_name = cls.qualified(name)
            value = description.get(full_name)
            if value is not None:
                settings[name] = value
        return settings

    @classmethod
    def _changed_by_user(cls, description: ElementTree.Element) -> bool:
        """Tell whether the user changed the history, or darktable only set it up.

        darktable stores a hash of the history as it is now, of the history
        right after it added its default modules, and of the bare history. When
        the current hash equals one of the other two, the user changed nothing.

        Args:
            description: The sidecar's rdf:Description element.

        Returns:
            True when the user changed the history, or when the sidecar has no hashes to tell.
        """
        current_name = cls.qualified("history_current_hash")
        automatic_name = cls.qualified("history_auto_hash")
        basic_name = cls.qualified("history_basic_hash")
        current = description.get(current_name)
        if current is None:
            return True
        automatic = description.get(automatic_name)
        basic = description.get(basic_name)
        return current not in (automatic, basic)

    @classmethod
    def _sort_entries(cls, items: list[ElementTree.Element], end: int) -> tuple[list[HistoryEntry], list[str]]:
        """Split the history into the entries that suit other photos and the modules left out.

        Args:
            items: The rdf:li elements of the history.
            end: darktable's history end; entries from this number on were undone.

        Returns:
            The kept entries, and the names of the modules left out, each once.
        """
        number_name = cls.qualified("num")
        operation_name = cls.qualified("operation")
        kept: list[HistoryEntry] = []
        left_out: list[str] = []
        for position, item in enumerate(items):
            number_text = item.get(number_name)
            number = position if number_text is None else int(number_text)
            operation = item.get(operation_name, "")
            if number >= end or not operation:
                continue
            attributes = dict(item.attrib)
            if operation in cls.PHOTO_ONLY_OPERATIONS or cls._uses_drawn_mask(attributes):
                if operation not in left_out:
                    left_out.append(operation)
                continue
            entry = HistoryEntry(operation, attributes)
            kept.append(entry)
        return kept, left_out

    @classmethod
    def _uses_drawn_mask(cls, attributes: dict[str, str]) -> bool:
        """Tell whether an entry blends through a drawn mask or a mask taken from another module.

        Masks made from brightness or color ranges work on any photo and are kept.

        Args:
            attributes: The entry's attributes.

        Returns:
            True when the entry's mask was drawn on its own photo.
        """
        blend_name = cls.qualified("blendop_params")
        text = attributes.get(blend_name, "")
        settings = cls._decode(text)
        if len(settings) < 4:
            return False
        (mask_mode,) = struct.unpack_from("<I", settings, 0)
        photo_masks = cls.DRAWN_MASK | cls.RASTER_MASK
        return bool(mask_mode & photo_masks)

    @classmethod
    def _decode(cls, text: str) -> bytes:
        """Turn darktable's text form of module settings into bytes.

        darktable writes settings as hexadecimal text, or as "gz", two digits
        and base64 text of zlib-packed bytes.

        Args:
            text: The settings text.

        Returns:
            The bytes; empty when the text cannot be read.
        """
        try:
            if text.startswith("gz"):
                packed = base64.b64decode(text[4:])
                return zlib.decompress(packed)
            return bytes.fromhex(text)
        except (ValueError, zlib.error):
            return b""

    def _window_names(self, operations: list[str], skipped: frozenset[str]) -> list[str]:
        """Turn module names into the names darktable's window shows.

        Args:
            operations: darktable's names of the modules.
            skipped: Modules to leave out of the list.

        Returns:
            The window names, in the same order.
        """
        names: list[str] = []
        for operation in operations:
            if operation in skipped:
                continue
            name = self.MODULE_NAMES.get(operation, operation)
            names.append(name)
        return names

    def _write_entries(self, sequence: ElementTree.Element) -> None:
        """Add the kept history entries to the history list, numbered from 0.

        Args:
            sequence: The rdf:Seq element of the history.
        """
        item_name = self._rdf("li")
        number_name = self.qualified("num")
        for number, entry in enumerate(self._entries):
            item = ElementTree.SubElement(sequence, item_name)
            for name, value in entry.attributes.items():
                item.set(name, value)
            number_text = str(number)
            item.set(number_name, number_text)

    def _rdf(self, name: str) -> str:
        """The full XML name of an RDF element or attribute.

        Args:
            name: The short name, such as "Description".

        Returns:
            Text such as "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description".
        """
        return "{" + self.RDF + "}" + name


class EditedPhotos:
    """Tells which raw photos the user edited in darktable, and when, from their sidecar files.

    A photo counts as edited when its sidecar's history holds the user's own
    changes, not only the modules darktable sets up by itself on import. A
    sidecar is read once; after that only its file time is checked, and it is
    read again when that time changed. Checking hundreds of photos again
    therefore takes milliseconds.
    """

    def __init__(self) -> None:
        """Start without any sidecar read."""
        self._known: dict[Path, tuple[int, bool]] = {}
        """Sidecar files read so far: their file time in nanoseconds, and whether the user edited the photo."""

    def edited_at(self, photo: Photo) -> float | None:
        """When the user last changed a photo's darktable edit.

        Args:
            photo: The photo.

        Returns:
            The time its sidecar was last written (seconds since 1970) when
            the sidecar holds the user's own edit; None for other photos.
        """
        if not photo.is_raw:
            return None
        sidecar_name = f"{photo.path.name}.xmp"
        sidecar = photo.path.with_name(sidecar_name)
        try:
            status = sidecar.stat()
        except OSError:
            return None
        stamp = status.st_mtime_ns
        known = self._known.get(sidecar)
        if known is not None and known[0] == stamp:
            edited = known[1]
        else:
            edit_file = DarktableEdit.edit_file_for(photo.path)
            edited = edit_file is not None
            self._known[sidecar] = (stamp, edited)
        if not edited:
            return None
        return status.st_mtime


class SidecarWriter:
    """Writes a darktable edit into photos' own sidecar files, as darktable's paste of a history does.

    A photo's old sidecar is copied to a backup folder first. What the old
    sidecar holds besides the edit, such as the rating, color labels, tags
    and title, stays; its history is replaced by the edit, which leaves out
    the parts that only fit the photo it was made for (crop, retouch and the
    like). The new sidecar has no history hashes: darktable works them out
    again, and the app counts the photo as edited. darktable reads the new
    sidecar when it imports the photo, or when the photo is opened again
    through "Open in darktable".
    """

    REPLACED_ATTRIBUTES = (
        "history_end",
        "iop_order_version",
        "iop_order_list",
        "history_basic_hash",
        "history_auto_hash",
        "history_current_hash",
        "auto_presets_applied",
        "xmp_version",
        "raw_params",
    )
    """The darktable attributes of the old sidecar that belong to its history, and are replaced."""

    REPLACED_ELEMENTS = ("history", "masks_history")

    def sidecar_of(self, photo: Path) -> Path:
        """The sidecar file of a photo, whether or not it exists.

        Args:
            photo: The raw file, such as P1199075.RW2.

        Returns:
            Its sidecar, such as P1199075.RW2.xmp.
        """
        sidecar_name = f"{photo.name}.xmp"
        return photo.with_name(sidecar_name)

    def write(self, edit: DarktableEdit, photo: Path, backup_folder: Path) -> Path | None:
        """Write an edit into a photo's sidecar, after copying the old sidecar to a backup folder.

        Args:
            edit: The edit.
            photo: The raw file.
            backup_folder: Where the old sidecar is copied to; it is made when needed.

        Returns:
            The backup copy of the old sidecar, or None when the photo had no sidecar.

        Raises:
            OSError: When the sidecar or its backup cannot be written.
        """
        sidecar = self.sidecar_of(photo)
        backup = None
        text = None
        if sidecar.exists():
            backup = self._back_up(sidecar, backup_folder)
            text = self._merged_text(edit, sidecar)
        if text is None:
            text = edit.sidecar_text()
        self._replace(sidecar, text)
        return backup

    def _back_up(self, sidecar: Path, backup_folder: Path) -> Path:
        """Copy a sidecar to the backup folder, with its file times.

        Args:
            sidecar: The sidecar.
            backup_folder: Where the copy goes.

        Returns:
            The copy.
        """
        backup_folder.mkdir(parents=True, exist_ok=True)
        backup = backup_folder / sidecar.name
        shutil.copy2(sidecar, backup)
        return backup

    def _merged_text(self, edit: DarktableEdit, sidecar: Path) -> str | None:
        """The old sidecar with its history replaced by the edit.

        Args:
            edit: The edit.
            sidecar: The old sidecar.

        Returns:
            The new XMP text, or None when the old file is not a sidecar that can be read.
        """
        try:
            self._register_prefixes_of(sidecar)
            tree = ElementTree.parse(sidecar)
        except (OSError, ElementTree.ParseError):
            return None
        root = tree.getroot()
        description = root.find(".//rdf:Description", DarktableEdit.NAMESPACES)
        if description is None:
            return None
        for name in self.REPLACED_ATTRIBUTES:
            full_name = DarktableEdit.qualified(name)
            description.attrib.pop(full_name, None)
        for name in self.REPLACED_ELEMENTS:
            full_name = DarktableEdit.qualified(name)
            old_elements = description.findall(full_name)
            for element in old_elements:
                description.remove(element)
        edit.fill_description(description)
        return DarktableEdit.xml_text(root)

    def _register_prefixes_of(self, sidecar: Path) -> None:
        """Keep the namespace prefixes of an old sidecar (dc, xmp, xmpMM and others) when it is written again.

        Args:
            sidecar: The old sidecar.
        """
        DarktableEdit.register_prefixes()
        events = ElementTree.iterparse(sidecar, events=["start-ns"])
        for _event, namespace in events:
            prefix, uri = namespace
            if not prefix:
                continue
            try:
                ElementTree.register_namespace(prefix, uri)
            except ValueError:
                # Prefixes such as "ns0" are kept for ElementTree's own use; it names those itself.
                continue

    def _replace(self, sidecar: Path, text: str) -> None:
        """Write a sidecar under a temporary name, then give it its real name, so no half-written file is left.

        Args:
            sidecar: The sidecar file.
            text: Its new text.
        """
        unique = uuid.uuid4().hex
        temporary = sidecar.with_name(f".{sidecar.name}.{unique}.part")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, sidecar)
