"""All service objects of the app, made and connected in one place."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from easy_photo.refinement.commands import CommandParser
from easy_photo.refinement.steps import StepCatalog
from easy_photo.services.ai_words import AiWordsReader
from easy_photo.services.darktable import DarktableRenderer
from easy_photo.services.developer import PhotoDeveloper
from easy_photo.services.exporter import Exporter
from easy_photo.services.faces import FaceFinder, FaceModels, PeopleSorter
from easy_photo.services.history_log import HistoryLog
from easy_photo.services.manifest import ProjectManifest
from easy_photo.services.photo_analyzer import PhotoAnalyzer
from easy_photo.services.photo_finder import PhotoFinder
from easy_photo.services.photo_reader import PhotoReader
from easy_photo.services.preview_cache import PreviewCache
from easy_photo.services.references import ReferenceMeasurer
from easy_photo.services.refiner import Refiner
from easy_photo.services.web_search import WebSearch, WikimediaSearch
from easy_photo.settings import AppFolders, AppSettings


@dataclass
class AppServices:
    """The service objects the window's controller works with.

    :meth:`create` makes them all and connects them, so the rest of the app
    gets its services from here instead of making its own.
    """

    finder: PhotoFinder
    reader: PhotoReader
    analyzer: PhotoAnalyzer
    face_models: FaceModels
    face_finder: FaceFinder
    people_sorter: PeopleSorter
    measurer: ReferenceMeasurer
    darktable: DarktableRenderer
    developer: PhotoDeveloper
    web_search: WebSearch
    parser: CommandParser
    refiner: Refiner
    exporter: Exporter
    manifest: ProjectManifest
    history_log: HistoryLog
    ai_reader: AiWordsReader

    @classmethod
    def create(cls, settings: AppSettings, folders: AppFolders) -> AppServices:
        """Make every service with the user's settings and the app's folders.

        Args:
            settings: Where the face models and darktable-cli are.
            folders: Where caches and lasting files go.

        Returns:
            The services, ready to use.
        """
        finder = PhotoFinder()
        preview_folder = folders.cache / "previews"
        cache = PreviewCache(preview_folder)
        reader = PhotoReader(cache)
        analyzer = PhotoAnalyzer()
        models_folder = Path(settings.models_folder) if settings.models_folder else folders.default_models
        face_models = FaceModels(models_folder)
        face_finder = FaceFinder(face_models)
        people_sorter = PeopleSorter()
        measurer = ReferenceMeasurer(reader, face_finder)
        darktable = DarktableRenderer.locate(settings.darktable_cli)
        developer = PhotoDeveloper(reader, darktable)
        web_search = WikimediaSearch()
        parser = CommandParser()
        refiner = Refiner()
        exporter = Exporter(reader, developer, refiner)
        catalog = StepCatalog()
        manifest = ProjectManifest(catalog)
        history_path = folders.data / "history.jsonl"
        history_log = HistoryLog(history_path)
        ai_reader = AiWordsReader(catalog, settings.ai_api_key, settings.ai_model)
        return cls(
            finder,
            reader,
            analyzer,
            face_models,
            face_finder,
            people_sorter,
            measurer,
            darktable,
            developer,
            web_search,
            parser,
            refiner,
            exporter,
            manifest,
            history_log,
            ai_reader,
        )
