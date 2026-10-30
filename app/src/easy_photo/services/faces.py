"""Finding faces in photos, and sorting them into people.

Both models come from the OpenCV model zoo: YuNet finds faces and SFace
describes each face with 128 numbers. Faces of the same person get similar
numbers, which is how they are sorted into people.
"""

from __future__ import annotations

import os
import threading
import urllib.request
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

import cv2
import numpy as np

from easy_photo import APP_NAME, APP_VERSION
from easy_photo.model.face import Face, FaceBox, Person


class FaceModels:
    """The two model files needed to find and compare faces, and where to download them."""

    DETECTOR_NAME = "face_detection_yunet_2023mar.onnx"
    RECOGNIZER_NAME = "face_recognition_sface_2021dec.onnx"
    BASE_URL = "https://github.com/opencv/opencv_zoo/raw/main/models"
    DETECTOR_URL = f"{BASE_URL}/face_detection_yunet/{DETECTOR_NAME}"
    RECOGNIZER_URL = f"{BASE_URL}/face_recognition_sface/{RECOGNIZER_NAME}"
    USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
    CHUNK_SIZE = 256 * 1024

    def __init__(self, folder: Path) -> None:
        """Create the model set for a folder.

        Args:
            folder: Folder that holds (or will hold) the two model files.
        """
        self._folder = folder

    @property
    def folder(self) -> Path:
        """Folder of the model files."""
        return self._folder

    @property
    def detector_path(self) -> Path:
        """The YuNet face finder model."""
        return self._folder / self.DETECTOR_NAME

    @property
    def recognizer_path(self) -> Path:
        """The SFace face description model."""
        return self._folder / self.RECOGNIZER_NAME

    @property
    def available(self) -> bool:
        """True when both model files are there."""
        return self.detector_path.exists() and self.recognizer_path.exists()

    def download(self, report: Callable[[int, int], None] | None = None) -> None:
        """Download both model files (about 40 MB) into the models folder.

        Args:
            report: Called with (bytes done, bytes expected) while downloading.

        Raises:
            OSError: When a download fails.
        """
        self._folder.mkdir(parents=True, exist_ok=True)
        self._download_file(self.DETECTOR_URL, self.detector_path, report)
        self._download_file(self.RECOGNIZER_URL, self.recognizer_path, report)

    def _download_file(self, url: str, target: Path, report: Callable[[int, int], None] | None) -> None:
        """Download one file under a temporary name and move it into place when complete.

        Args:
            url: Where to download from.
            target: Where the file goes.
            report: Called with (bytes done, bytes expected) while downloading.
        """
        if target.exists():
            return
        unique = uuid.uuid4().hex
        temporary = target.with_name(f"{target.name}.{unique}.part")
        headers = {"User-Agent": self.USER_AGENT}
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            expected_text = response.headers.get("Content-Length", "0")
            expected = int(expected_text)
            done = 0
            while True:
                chunk = response.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
                done += len(chunk)
                if report is not None:
                    report(done, expected)
        os.replace(temporary, target)


class FaceFinder:
    """Finds faces in photos and describes each face with 128 numbers.

    The models are loaded the first time they are needed. OpenCV's face
    models must not be used by two threads at once, so a lock lets one call
    in at a time.
    """

    MIN_SCORE = 0.6
    """Faces the model is less sure about are ignored."""

    MIN_WIDTH = 14
    """Faces narrower than this many pixels are ignored; they are too small to describe."""

    THUMBNAIL_SIDE = 96

    def __init__(self, models: FaceModels) -> None:
        """Create a face finder.

        Args:
            models: The two model files.
        """
        self._models = models
        self._detector: cv2.FaceDetectorYN | None = None
        self._recognizer: cv2.FaceRecognizerSF | None = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        """True when the model files are there."""
        return self._models.available

    def find(self, photo_id: str, pixels: np.ndarray) -> list[Face]:
        """Find the faces in a photo.

        Args:
            photo_id: Id of the photo, used in the face ids.
            pixels: Upright RGB pixels, 8 bits per channel.

        Returns:
            The faces, in the order the model found them.
        """
        with self._lock:
            self._load_models()
            return self._find_faces(photo_id, pixels)

    def _load_models(self) -> None:
        """Load the two models once."""
        if self._detector is not None:
            return
        detector_text = str(self._models.detector_path)
        recognizer_text = str(self._models.recognizer_path)
        self._detector = cv2.FaceDetectorYN.create(detector_text, "", (320, 320), self.MIN_SCORE, 0.3, 5000)
        self._recognizer = cv2.FaceRecognizerSF.create(recognizer_text, "")

    def _find_faces(self, photo_id: str, pixels: np.ndarray) -> list[Face]:
        """Run the face finder on a photo and describe every face it finds.

        Args:
            photo_id: Id of the photo.
            pixels: Upright RGB pixels.

        Returns:
            The faces.
        """
        height, width = pixels.shape[:2]
        bgr = cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)
        self._detector.setInputSize((width, height))
        _, rows = self._detector.detect(bgr)
        if rows is None:
            return []
        faces: list[Face] = []
        for index, row in enumerate(rows):
            face = self._make_face(photo_id, index, row, bgr, pixels)
            if face is not None:
                faces.append(face)
        return faces

    def _make_face(self, photo_id: str, index: int, row: np.ndarray, bgr: np.ndarray, pixels: np.ndarray) -> Face | None:
        """Turn one row of the face finder's output into a :class:`Face`.

        Args:
            photo_id: Id of the photo.
            index: Number of the face in the photo.
            row: The face finder's row: box, five landmarks and score.
            bgr: The photo in the BGR order OpenCV uses.
            pixels: The photo in RGB order, for the thumbnail.

        Returns:
            The face, or None when it is too small.
        """
        x = float(row[0])
        y = float(row[1])
        face_width = float(row[2])
        face_height = float(row[3])
        if face_width < self.MIN_WIDTH:
            return None
        face_row = row.reshape(1, -1)
        aligned = self._recognizer.alignCrop(bgr, face_row)
        feature = self._recognizer.feature(aligned)
        description = feature.flatten()
        length = np.linalg.norm(description)
        if length > 0:
            description = description / length
        height, width = pixels.shape[:2]
        box = FaceBox(x / width, y / height, face_width / width, face_height / height)
        thumbnail = self._thumbnail(pixels, x, y, face_width, face_height)
        score = float(row[-1])
        face_id = f"{photo_id}#{index}"
        return Face(face_id, photo_id, box, score, description, thumbnail)

    def _thumbnail(self, pixels: np.ndarray, x: float, y: float, face_width: float, face_height: float) -> np.ndarray:
        """Cut a square picture around a face, with some room around it.

        Args:
            pixels: The photo in RGB order.
            x: Left edge of the face box.
            y: Top edge of the face box.
            face_width: Width of the face box.
            face_height: Height of the face box.

        Returns:
            A square RGB picture of THUMBNAIL_SIDE pixels.
        """
        height, width = pixels.shape[:2]
        side = 1.6 * max(face_width, face_height)
        centre_x = x + face_width / 2.0
        centre_y = y + face_height / 2.0
        left = int(centre_x - side / 2.0)
        top = int(centre_y - side / 2.0)
        right = int(centre_x + side / 2.0)
        bottom = int(centre_y + side / 2.0)
        left = max(left, 0)
        top = max(top, 0)
        right = min(right, width)
        bottom = min(bottom, height)
        crop = pixels[top:bottom, left:right]
        size = (self.THUMBNAIL_SIDE, self.THUMBNAIL_SIDE)
        return cv2.resize(crop, size, interpolation=cv2.INTER_AREA)


class PeopleSorter:
    """Sorts faces into people by comparing their descriptions.

    Faces are taken one by one, the clearest first. A face joins the person
    whose average description is most similar, when the similarity reaches
    the threshold; otherwise it starts a new person.
    """

    SAME_PERSON = 0.363
    """Cosine similarity from which SFace treats two faces as the same person (OpenCV's value)."""

    def __init__(self, threshold: float = SAME_PERSON) -> None:
        """Create a sorter.

        Args:
            threshold: Lowest similarity for "same person".
        """
        self._threshold = threshold

    def sort(self, faces: Sequence[Face]) -> list[Person]:
        """Sort faces into people.

        Args:
            faces: All faces of the project.

        Returns:
            The people, the one with the most faces first, named "Person 1", "Person 2" and so on.
        """
        ordered = sorted(faces, key=self._score_of, reverse=True)
        people: list[Person] = []
        for face in ordered:
            person = self._best_match(face, people)
            if person is None:
                number = len(people) + 1
                person = Person(f"person-{number}", f"Person {number}")
                people.append(person)
            person.add_face(face)
        people.sort(key=self._face_count_of, reverse=True)
        for number, person in enumerate(people, start=1):
            person.name = f"Person {number}"
        return people

    def _best_match(self, face: Face, people: Sequence[Person]) -> Person | None:
        """Find the person a face is most similar to.

        Args:
            face: The face.
            people: The people so far.

        Returns:
            The most similar person, or None when nobody reaches the threshold.
        """
        best: Person | None = None
        best_similarity = self._threshold
        for person in people:
            average = person.average_description
            similarity = np.dot(average, face.description)
            if similarity >= best_similarity:
                best = person
                best_similarity = similarity
        return best

    def _score_of(self, face: Face) -> float:
        """Sort key: how sure the face finder was.

        Args:
            face: The face.

        Returns:
            Its score.
        """
        return face.score

    def _face_count_of(self, person: Person) -> int:
        """Sort key: how many faces a person has.

        Args:
            person: The person.

        Returns:
            The number of faces.
        """
        return person.face_count
