# easy-photo

easy-photo is a desktop app for turning a camera card full of photos into a set of finished ones. It sets aside the photos that can't be used, groups the rest, and refines each group with an option you pick: one learned from photos you selected before, one found on the internet, one copied from examples you give, or one you describe in your own words.

It runs on Ubuntu and Windows. The app lives in [app/](app/).

## Running the app

You need Python 3.10 or newer. The app installs into a virtual environment inside `app/`, so nothing is installed system-wide.

Ubuntu:

```bash
sudo apt install python3-venv libxcb-cursor0   # once; Qt needs libxcb-cursor0 to open windows
./run.sh                                       # makes app/.venv on the first run, then starts the app
./run.sh ~/Pictures/easy-photo/japan           # opens that project directly
```

Or by hand:

```bash
cd app
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/easy-photo
```

Windows (PowerShell):

```powershell
cd app
py -3.12 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\easy-photo
```

`easy-photo PATH` opens the project at `PATH` directly. Run the tests with `.venv/bin/python -m pytest` (or `.venv\Scripts\python -m pytest`).

Three things are optional:

- Face recognition needs two model files from the OpenCV model zoo (about 40 MB). The Group step has a button that downloads them, or you can point it at a folder that already has them.
- darktable 4.6 or newer, to develop raw files from their raw data and to apply darktable edits (`.xmp` files). Without it, raw files are exported from the small JPEG preview the camera stores inside them. The app finds `darktable-cli` on the PATH or in `C:\Program Files\darktable\bin`.
- [Claude Code](https://claude.com/claude-code), logged in, for typed refinements the app's own phrases do not cover (see below).

## Projects

A project is a folder with a manifest file, `easy-photo-project.json`. The manifest holds everything you decided: the sources, the limits of the filter, your own keep and set-aside choices, the names you gave people, the groups, the refinement options with their steps, and the option picked for each group. One project is open at a time; the start screen lists recent ones. Every change is saved a moment after you make it.

Measurements are not stored in the manifest. They are made again when a project opens, which is quick because the previews of raw files are cached.

## The six steps

```text
1 Source -> 2 Filter -> 3 Group -> 4 References -> 5 Refine -> 6 Export
```

### 1. Source

Drop folders or photos on the window, or browse for them. While you filter and group, raw files (RW2, CR3, NEF, ARW, DNG and others) are shown from the JPEG picture the camera stored inside each one, read with [rawpy](https://github.com/letmaik/rawpy) (LibRaw). That takes about 70 to 100 ms per photo, measuring included. The Refine previews and the export develop the raw data itself with darktable (see Export).

### 2. Filter

A photo is set aside when it is:

- badly blurred, with no sharp part that a crop could keep
- unclear, with no subject that stands out even after cropping
- too dark or too bright to recover

Sharpness and detail are measured in nine overlapping windows, each half the width and height of the photo, and the best window counts. A photo with one sharp part is therefore kept, and the crop can come later. Photos near a limit are marked unsure and stay in until you decide. Nothing is deleted: set-aside photos have their own view, and K, X and U keep, set aside or undo for the selected photos. The limits are sliders; the defaults come from 813 raw files of a Lumix S5, where they set aside blurred shots of grass and food and near-black frames but kept shallow depth-of-field portraits.

### 3. Group

Photos are grouped one of two ways:

- Similar photos: neighbouring photos share a group when the pause between them is short (10 minutes by default) and they look alike (colors and rough layout).
- Same people: the app finds faces with YuNet, describes them with SFace, and sorts them into people. Photos with the same people form a group. You can rename people and merge two that are the same person.

The sharpest photo of each group stands for it in the next steps. Within a group you can select and unselect photos one by one (K and X) or all at once; unselected photos stay in the group but are not exported.

### 4. References

Each group has its own references. Choose the group in "References for" at the top of the page, then add references; each one becomes a refinement option for that group only, and the list below shows that group's options. Choose "All groups" to add an option for every group. "Remove from this group" takes an option out of the chosen group only (an option no group uses any more is removed); under "All groups", "Remove option" removes it everywhere.

- Your history: folders or photos you picked before. The app learns how bright you like photos, and faces when enough photos have them.
- The internet: a search on [Wikimedia Commons](https://commons.wikimedia.org), a free photo library that needs no account. The photos found are only measured on your computer.
- Examples: files you edited or like right now. Ordinary photos teach the app how bright you like them; a raw file without your own edit is developed with `darktable-cli` and measured the same way.
- darktable edits: a raw file you edited in darktable (under Examples), or a darktable sidecar (`.xmp` file, under Examples or Your history). `darktable-cli` applies the edit itself to every raw photo of the group, module by module, as darktable does when you paste a copied history. The parts that only fit the edited photo are left out: crop, perspective, orientation, retouch, spots, liquify, lens correction, the raw black and white points, and any module with a drawn mask. A raw file counts as edited when its sidecar's history differs from what darktable set up on import (darktable keeps a hash of both). The option points at the sidecar, so if you change the edit in darktable later, the next export uses the new version.
- Your own words, such as "brighter faces, less contrast" or "neutral, not warm, not cool".

`darktable-cli` always runs in its own settings folder with a library in memory, so your darktable library and sidecar files are never touched.

The unchanged photo is always an option too: darktable's development of it (with the photo's own sidecar when it has one), or the camera's picture when darktable is not installed.

### 5. Refine

For each group, its options are shown side by side on its sample photo, together with a slightly brighter and a slightly darker copy of its newest reference option. Each version is made the way the export makes it, at 1280 px: the same darktable development (about three seconds for each darktable edit among the options), the same steps, and the same light sharpen when the export sharpens. Pick one with a click or the keys 1 to 9; it applies to every photo of the group. If none fits, type the change you want. The app makes that version at once, on top of the version you had picked, and picks it. You can also skip a group.

Brightness options change the whole photo with one curve and keep the colors, so faces are never lifted as a bright patch on a darker photo.

### 6. Export

Every kept photo of the groups with a pick is developed, refined and written as a JPEG file: 1920 px on the long side and quality 100 by default, with the date, camera and exposure copied from the original. A file that already exists is never overwritten, and a stopped export leaves no half-written files.

A raw file is developed by `darktable-cli` from its raw data, at full size and shrunk to the export size at the end, with the picked option's darktable edit, or else the photo's own sidecar, or darktable's default development when it has none. darktable hands the result over as a 16-bit PNG in a temporary folder. The app applies the option's own steps to it, sharpens it a little (radius 0.75 px at 75 %; this can be switched off), and compresses it once, into the JPEG, with an sRGB color profile. That takes about three seconds per photo. `darktable-cli` develops one photo at a time at low priority, so the computer stays usable.

Without darktable, a raw file is exported from the camera's JPEG preview, which is about 1920 px wide and already compressed, so the export has visibly less detail and smaller files.

## What you can type

A command is a list of changes separated by commas, "and" or "then". "slightly" or "a little" halves a change, "much" doubles it, and a number sets it.

| change | examples |
|---|---|
| exposure | brighter, darker, exposure +0.5 |
| contrast | more contrast, less contrast, contrast -10 |
| shadows | lift shadows, deeper shadows, shadows +0.4 |
| highlights | recover highlights, brighter highlights, highlights -0.5 |
| color | more color, less color, saturation +10, black and white |
| warmth | warmer, cooler, warmth +5 |
| neutral colors | neutral, not warm, not cool, remove color cast |
| faces | brighter faces, darker faces, faces +0.3 |

When the app's own phrases do not cover what you typed, Claude reads it (see below). Without Claude, anything the app does not understand is listed back to you with examples, and nothing is changed.

## Claude for your own words

Claude reads any refinement you type, in any language ("make it moody like old film", "bikin lebih cerah tapi jangan pucat"), and turns it into the app's own adjustments. Claude's one-sentence reading is shown next to the new option.

The app asks Claude through [Claude Code](https://claude.com/claude-code)'s `claude` command in print mode, with your own Claude login, so no API key is needed; each request counts toward your Claude plan's usage. Install Claude Code and run `claude` once to log in; the app finds it on the PATH or in `~/.local/bin`. The app sends only your words, through the command's input, never your photos. The run is kept bare: no tools, no MCP servers, no user settings or hooks, an empty temporary folder, and no saved session. Claude's answer must follow a fixed JSON schema (`--json-schema`), so only adjustments the app knows can come back, each kept within its range. An answer takes about 7 seconds.

When Claude Code is installed but not logged in, a request fails with "Not logged in". The app then checks `claude auth status` and, if nobody is logged in, offers to open a terminal window that runs `claude auth login`. Claude Code opens the browser to sign in to your Claude account, so the app never sees your credentials. The app checks the login every few seconds, for up to ten minutes, and reads the words you typed as soon as you are logged in.

In Settings, "AI for your own words", you can switch Claude off, choose the model (Claude Opus 5.5 at low effort by default, or Sonnet 5.5 or Haiku 5.5), see which account Claude Code is logged in to, and log in.

## Rules learned from the manual runs

Before this app, the workflow ran as Python scripts driven from Claude Code sessions, on two batches of raw files from a 2024 trip (684 and 820 files). These rules came out of it and are built into the app:

- Guess, then ask. Pre-selected guesses keep the questions fast: in one batch the author changed 1 of 269 face labels.
- Set aside only bad blur, and ask first. The author kept 26 of the 27 frames an earlier focus check would have dropped.
- Change brightness with one global adjustment per photo. A face lifted on its own looked like a bright spot on a darker photo and was rejected.
- Bring faces to the brightness of faces in photos you kept, and no further. Early exports with brighter faces were sent back as too bright.
- Leave colors to the references. For photos of people, the author rejected changes to warmth and tint and overlays such as vignettes, and asked only for exposure, base curve and tone equalizer changes. For landscapes, the same author chose warm grades with vignettes.
- Never overwrite. Exports go only to free file names.
- Keep the machine usable. Three parallel full-size exports once froze the machine, so background work uses at most two threads, `darktable-cli` develops one photo at a time at low priority, and a stopped export picks up where it left off.
- Work with darktable through files only. A remote query into a running darktable crashed it, and a Lua plugin kept it from starting until the plugin was switched off.

## How the code is organized

The code is object-oriented, with one job per class and plain names. Everything below `gui` works without Qt, so it can be tested and reused on its own.

| package | what it holds | main classes |
|---|---|---|
| `easy_photo.model` | the data: photos, check results, groups, faces, people, the project | `Photo`, `QualityResult`, `PhotoGroup`, `Person`, `Project` |
| `easy_photo.refinement` | the refinement steps, the options made of them, typed commands | `RefinementStep` and its subclasses, `RefinementPipeline`, `CommandParser`, `BrightnessCurve` |
| `easy_photo.services` | the work: reading, developing, measuring, checking, faces, grouping, references, export, manifest | `PhotoReader`, `PhotoDeveloper`, `DarktableRenderer`, `DarktableEdit`, `PhotoAnalyzer`, `QualityChecker`, `FaceFinder`, `Grouper`, `PipelineBuilder`, `Exporter`, `ProjectManifest` |
| `easy_photo.gui` | the PySide6 window | `ProjectController`, `MainWindow`, one `WorkflowPage` subclass per step |

The places where the app can grow are abstract classes: a new filter rule is a `QualityCheck`, a new way to group is a `Grouper`, a new kind of reference is a `PipelineBuilder`, a new refinement is a `RefinementStep`, and a new search service is a `WebSearch`. `AppServices.create` makes and connects all services in one place, and `ProjectController` runs slow work on a two-thread pool and stores the results in the project on the window thread.

Two coding rules hold everywhere, and [tests/test_code_rules.py](app/tests/test_code_rules.py) fails when one is broken:

- Every module, class, function and method has a docstring.
- No nested calls: a call never has another call in its arguments, so every intermediate result has a name.

## Tech stack

- Python 3.10 or newer (developed on 3.12)
- [PySide6](https://doc.qt.io/qtforpython-6/) (Qt 6) for the window, with a light and a dark theme that follow the system
- [OpenCV](https://opencv.org) for measuring photos, and the YuNet and SFace models for faces
- [rawpy](https://github.com/letmaik/rawpy) for the pictures inside raw files, and Pillow for JPEG files and EXIF data
- numpy for the image math
- [platformdirs](https://github.com/tox-dev/platformdirs) for the settings and cache folders of each system
- Claude Code's `claude` command, optional, for reading typed refinements with Claude
- darktable-cli, optional, to develop raw files and apply darktable edits

Python fits because the manual workflow already ran as Python scripts, and the slow parts (decoding pictures, running the face models) run in C and C++ inside the libraries, so a compiled language would not make the app noticeably faster. The references depend on image and machine-learning libraries, and Python has the widest choice of them. PySide6 replaced the Tkinter windows of the scripts because the app needs large photo grids with zoom and background work with progress, and because it installs from pip on both systems, while Tkinter depends on how Python was built.

## Repository layout

| path | contents |
|---|---|
| `run.sh` | starts the app on Ubuntu, making `app/.venv` on the first run |
| `app/pyproject.toml` | the package, its dependencies, and the `easy-photo` command |
| `app/src/easy_photo/` | the source |
| `app/tests/` | the tests, including an end-to-end test of the window that runs without a screen |
| `images` | link to the local photo library (`/data1/images` on the development machine), ignored by git |

## License

MIT, see [LICENSE](LICENSE).
