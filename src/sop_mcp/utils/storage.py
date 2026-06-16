# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Local filesystem storage backend for SOP files.

SOPs are stored as ``*.sop.md`` markdown files with YAML frontmatter,
each inside its own enclosing folder.  Feedback is a JSONL log sitting
*next to* the SOP's folder, not inside it::

    {base_dir}/{name}/{name}.sop.md       # SOP document
    {base_dir}/{name}/{name}.feedback.jsonl  # append-only feedback log
    {base_dir}/{name}/rubric.md           # optional sibling attachments
    {base_dir}/{name}/examples/diff.png   # …at any depth

Callers may group SOPs under a parent directory via ``path=`` on
``write_sop``; the SOP's own folder is nested beneath that parent::

    {base_dir}/generated/{name}/{name}.sop.md
    {base_dir}/generated/{name}/{name}.feedback.jsonl
    {base_dir}/teams/eng/{name}/{name}.sop.md
    {base_dir}/teams/eng/{name}/{name}.feedback.jsonl

Feedback is treated as **append-only**: the ``submit_sop_feedback`` tool
appends entries via ``append_feedback``.  Feedback files are not exposed
as MCP resources — they live inside the SOP folder but are hidden from
``list_attachments`` and ``read_attachment``.

Discovery is recursive: any ``*.sop.md`` under ``base_dir`` at any depth
is picked up.  SOP identity is the frontmatter ``name`` — the folder
name is advisory (defaults to the SOP's name, but may differ).  When two
files declare the same ``name``, the first one discovered wins and the
duplicates are reported through ``duplicate_name_warnings`` so callers
can surface the problem without crashing the server.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import ClassVar

from .sop_parser import SOP, SOP_SUFFIX, set_version_in_content

logger = logging.getLogger(__name__)

# Directory containing the SOPs bundled with the package.
BUNDLED_SOPS_DIR = Path(__file__).parent.parent / "resources"

# Upper bound on the number of *.sop.md files the backend will scan in a
# single directory walk. A storage dir with more SOPs than this is almost
# certainly hostile (or misconfigured); we stop scanning and warn rather
# than spend unbounded time/memory parsing frontmatter.
MAX_SOPS_SCANNED = 10_000

FEEDBACK_SUFFIX = ".feedback.jsonl"


class LocalFilesystemBackend:
    """Storage backend that reads/writes SOP files on the local filesystem.

    Discovery is recursive — ``*.sop.md`` files at any depth under
    ``base_dir`` are included.  SOP identity is the frontmatter ``name``
    field; path information is ignored for lookup so two files sharing a
    name would collide.  Collisions are reported (not raised) — first file
    discovered wins, others are logged and exposed via
    ``duplicate_name_warnings``.
    """

    def __init__(
        self,
        base_dir: Path,
        seed_dir: Path | None = None,
    ) -> None:
        self._base_dir = base_dir
        self._duplicate_warnings: list[str] = []
        # Cached {name: path} map from the last scan.  ``None`` means
        # dirty — callers must re-scan before trusting the result.  The
        # cache is invalidated on any write through this backend (see
        # ``write_sop`` / ``append_feedback``).  Direct filesystem writes
        # by a third party are not tracked.
        self._scan_cache: dict[str, Path] | None = None

        self._base_dir.mkdir(parents=True, exist_ok=True)

        if seed_dir is not None:
            self._seed(seed_dir)

    @classmethod
    def from_env(cls) -> LocalFilesystemBackend:
        """Create from environment variables.

        ``SOP_STORAGE_DIR`` → use that path, seed from bundled SOPs on first run.
        Otherwise → default to ``~/.sop_mcp`` (also seeded from bundled).

        We never write into the installed package directory: ``uvx`` caches
        get wiped and replaced, so any SOPs a user publishes would silently
        disappear. A stable per-user default avoids that footgun.
        """
        storage_dir = os.environ.get("SOP_STORAGE_DIR", "").strip()
        base_dir = _validate_storage_path(storage_dir) if storage_dir else Path.home() / ".sop_mcp"
        return cls(base_dir=base_dir, seed_dir=BUNDLED_SOPS_DIR)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def duplicate_name_warnings(self) -> list[str]:
        """Warnings produced by the last ``list_sops`` scan for collisions."""
        return list(self._duplicate_warnings)

    # --- SOP discovery ---

    def _scan(self) -> dict[str, Path]:
        """Walk ``base_dir`` recursively and return ``{name: path}``.

        The frontmatter ``name`` field is the key.  When two files declare
        the same name, the lexicographically earlier path wins and the
        collision is recorded in ``_duplicate_warnings``.

        Results are cached inside the backend to keep repeated lookups
        (``list_sops``, ``read_sop``, ``list_attachments`` inside the same
        request) O(1) instead of O(N) per call.  Any write through this
        backend (``write_sop`` / ``append_feedback``) clears the cache.
        """
        if self._scan_cache is not None:
            return self._scan_cache

        self._duplicate_warnings = []
        if not self._base_dir.exists():
            self._scan_cache = {}
            return self._scan_cache

        name_to_path: dict[str, Path] = {}
        scanned = 0
        base_resolved = self._base_dir.resolve()
        for path in sorted(self._base_dir.rglob(f"*{SOP_SUFFIX}")):
            if not path.is_file():
                continue

            # Reject any SOP file that resolves outside the storage root.
            # rglob can surface a symlinked *.sop.md whose target lives
            # elsewhere on disk; reading it would relay out-of-tree content
            # to the agent. Containment here mirrors the relative_to() guard
            # already applied to user-supplied subdir/attachment paths.
            try:
                path.resolve().relative_to(base_resolved)
            except (ValueError, OSError) as exc:
                msg = (
                    f"Skipping SOP at '{path}' — it resolves outside the storage "
                    f"directory '{self._base_dir}' (symlink or junction). "
                    "Out-of-tree SOP files are ignored."
                )
                logger.error("%s (%s)", msg, exc)
                self._duplicate_warnings.append(msg)
                continue

            scanned += 1
            if scanned > MAX_SOPS_SCANNED:
                msg = (
                    f"SOP scan stopped at {MAX_SOPS_SCANNED} files — storage directory "
                    f"'{self._base_dir}' holds more SOPs than the supported limit. "
                    "Remaining files are ignored; split the storage directory."
                )
                logger.error(msg)
                self._duplicate_warnings.append(msg)
                break

            try:
                content = path.read_text(encoding="utf-8")
                sop = SOP.from_content(content)
            except (ValueError, OSError) as exc:
                logger.warning("Skipping unreadable SOP at %s: %s", path, exc)
                continue

            if sop.name in name_to_path:
                existing = name_to_path[sop.name]
                msg = (
                    f"Duplicate SOP name '{sop.name}': "
                    f"'{path.relative_to(self._base_dir)}' "
                    f"collides with '{existing.relative_to(self._base_dir)}' "
                    "— first wins, later duplicates are ignored."
                )
                logger.error(msg)
                self._duplicate_warnings.append(msg)
                continue

            name_to_path[sop.name] = path

        self._scan_cache = name_to_path
        return name_to_path

    def _invalidate_scan(self) -> None:
        """Clear the scan cache after a write so the next read re-scans."""
        self._scan_cache = None

    def _sop_path(self, name: str) -> Path | None:
        """Return the on-disk path of an SOP by name, or ``None`` if absent."""
        return self._scan().get(name)

    def _feedback_path_for(self, sop_path: Path) -> Path:
        """Compute the feedback path for an SOP.

        Feedback lives **inside** the SOP's folder alongside the markdown
        file, keeping all SOP artifacts co-located.

        - Nested layout (``{…}/{name}/{name}.sop.md``) →
          ``{…}/{name}/{name}.feedback.jsonl`` inside the folder.
        - Flat layout (``{…}/{name}.sop.md``) →
          ``{…}/{name}.feedback.jsonl`` sibling of the file.
        """
        name = sop_path.name[: -len(SOP_SUFFIX)]
        parent = sop_path.parent
        # Nested layout: the SOP's parent folder is named after the SOP.
        if parent.name == name:
            return parent / f"{name}{FEEDBACK_SUFFIX}"
        # Flat layout: feedback is a sibling of the SOP file itself.
        return parent / f"{name}{FEEDBACK_SUFFIX}"

    # --- SOP read/write ---

    def read_sop(self, name: str, version: str | None = None) -> str:
        """Read SOP file content. ``version`` must match the file's version if given."""
        path = self._sop_path(name)
        if path is None:
            raise FileNotFoundError(f"SOP '{name}' not found")

        content = path.read_text(encoding="utf-8")
        if version is not None:
            file_version = SOP.from_content(content).version
            if file_version != version:
                raise FileNotFoundError(
                    f"Version '{version}' not found for '{name}'. Available version: {file_version}"
                )
        return content

    def write_sop(
        self,
        name: str,
        version: str,
        content: str,
        path: str | None = None,
    ) -> Path:
        """Write SOP content and return the absolute path written to.

        By default, an SOP is written into its own enclosing folder named
        after the frontmatter ``name``.  For an SOP named ``onboarding``,
        that means ``{base}/onboarding/onboarding.sop.md``.  The folder
        becomes the home for any sibling attachments the author adds
        (checklists, rubrics, diagrams, …).

        ``path`` is optional and specifies a *parent* for the SOP's folder
        — pass ``path="generated/"`` and the file lands at
        ``{base}/generated/onboarding/onboarding.sop.md``.  When the SOP
        already exists, the write updates the existing file in place
        and ``path`` is treated as informational.

        Raises ``ValueError`` when ``path`` resolves outside ``base_dir``
        or when the SOP already exists at a different path than the one
        given.
        """
        content = set_version_in_content(content, version)

        existing = self._sop_path(name)
        if existing is not None:
            # Update in place — path parameter is informational at best.
            if path is not None:
                requested = self._resolve_subdir(path) / name / f"{name}{SOP_SUFFIX}"
                if requested.resolve() != existing.resolve():
                    raise ValueError(
                        f"SOP '{name}' already exists at "
                        f"'{existing.relative_to(self._base_dir)}'. "
                        "Omit 'path' to update in place, or rename the SOP."
                    )
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text(content, encoding="utf-8")
            self._invalidate_scan()
            return existing

        parent = self._resolve_subdir(path) if path else self._base_dir
        target_dir = parent / name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{name}{SOP_SUFFIX}"
        target.write_text(content, encoding="utf-8")
        self._invalidate_scan()
        return target

    def _resolve_subdir(self, path: str) -> Path:
        """Resolve a user-supplied subdirectory path inside ``base_dir``."""
        candidate = (self._base_dir / path).resolve()
        base_resolved = self._base_dir.resolve()
        try:
            candidate.relative_to(base_resolved)
        except ValueError as exc:
            raise ValueError(f"Path '{path}' resolves outside the storage directory") from exc
        return candidate

    def list_sops(self) -> list[str]:
        """Return a sorted list of SOP names discovered recursively."""
        return sorted(self._scan().keys())

    def get_version(self, name: str) -> str | None:
        """Return the version carried in the file, or ``None`` if missing."""
        path = self._sop_path(name)
        if path is None:
            return None
        try:
            sop = SOP.from_content(path.read_text(encoding="utf-8"))
        except (ValueError, FileNotFoundError):
            return None
        return sop.version

    def sop_exists(self, name: str, version: str | None = None) -> bool:
        path = self._sop_path(name)
        if path is None:
            return False
        if version is None:
            return True
        try:
            sop = SOP.from_content(path.read_text(encoding="utf-8"))
        except (ValueError, FileNotFoundError):
            return False
        return sop.version == version

    def sop_path_for(self, name: str) -> Path | None:
        """Public helper — return the on-disk path of an SOP by name."""
        return self._sop_path(name)

    def attachment_path_for(self, name: str, relative_path: str) -> Path | None:
        """Public helper — return the on-disk path of an attachment, or ``None``."""
        sidecar = self._attachment_dir(name)
        if sidecar is None:
            return None
        candidate = (sidecar / relative_path).resolve()
        try:
            candidate.relative_to(sidecar.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    # --- Sidecar attachments ---

    # Files/directories to never expose as attachments.
    _ATTACHMENT_BLACKLIST: ClassVar[set[str]] = {"__pycache__", ".DS_Store"}

    def _attachment_dir(self, name: str) -> Path | None:
        """Return the folder that hosts attachments for an SOP, or ``None``.

        Two layouts are supported:

        - **Nested** (current default) — the SOP lives at
          ``{…}/{name}/{name}.sop.md`` and its enclosing folder doubles
          as the attachment home.
        - **Flat** (legacy / ad-hoc) — the SOP lives at
          ``{…}/{name}.sop.md`` with an optional sibling folder
          ``{…}/{name}/`` holding the attachments.
        """
        sop_path = self._sop_path(name)
        if sop_path is None:
            return None

        parent = sop_path.parent
        if parent.name == name and parent.is_dir():
            return parent  # nested layout — SOP folder is the sidecar
        candidate = parent / name
        return candidate if candidate.is_dir() else None

    def list_attachments(self, name: str) -> list[str]:
        """Return sorted relative paths of every attachment in the SOP folder.

        Excludes the SOP markdown file itself and any ``*.feedback.jsonl``
        logs — feedback is append-only and not exposed as a readable resource.
        Skips hidden files (``.foo``) and entries in
        ``_ATTACHMENT_BLACKLIST`` so cache dirs and editor metadata don't
        leak into ``resources/list``.
        """
        sidecar = self._attachment_dir(name)
        if sidecar is None:
            return None
        sop_path = self._sop_path(name)

        found: list[str] = []
        sidecar_resolved = sidecar.resolve()
        for path in sorted(sidecar.rglob("*")):
            if not path.is_file():
                continue
            # Skip attachments that resolve outside the sidecar folder
            # (symlinks pointing elsewhere). read_attachment already blocks
            # these on read; excluding them here keeps them out of the
            # advertised resource list too.
            try:
                path.resolve().relative_to(sidecar_resolved)
            except (ValueError, OSError):
                continue
            if sop_path is not None and path.resolve() == sop_path.resolve():
                continue  # the SOP itself isn't an attachment
            if path.name.endswith(FEEDBACK_SUFFIX):
                continue  # feedback is not exposed as a resource
            rel = path.relative_to(sidecar)
            if any(part in self._ATTACHMENT_BLACKLIST or part.startswith(".") for part in rel.parts):
                continue
            found.append(rel.as_posix())
        return found

    def read_attachment(self, name: str, relative_path: str) -> bytes:
        """Read an attachment's raw bytes by SOP name and relative path.

        Rejects any path that targets a ``*.feedback.jsonl`` file.
        """
        if relative_path.endswith(FEEDBACK_SUFFIX):
            raise FileNotFoundError(f"Attachment '{relative_path}' is not available: feedback logs are not exposed.")
        sidecar = self._attachment_dir(name)
        if sidecar is None:
            raise FileNotFoundError(f"No sidecar folder for SOP '{name}'")

        target = (sidecar / relative_path).resolve()
        try:
            target.relative_to(sidecar.resolve())
        except ValueError as exc:
            raise ValueError(f"Attachment path '{relative_path}' escapes the sidecar folder") from exc

        if not target.is_file():
            raise FileNotFoundError(f"Attachment '{relative_path}' not found under SOP '{name}'")
        return target.read_bytes()

    # --- Feedback (JSONL) ---

    def _feedback_path(self, name: str) -> Path:
        """Feedback path for a named SOP — defaults to base_dir when absent."""
        sop_path = self._sop_path(name)
        if sop_path is not None:
            return self._feedback_path_for(sop_path)
        return self._base_dir / f"{name}{FEEDBACK_SUFFIX}"

    def append_feedback(self, name: str, entry: dict) -> None:
        """Append a single JSON object as a line to the feedback file.

        Append-only by design — there is no matching read method on the
        backend because feedback is write-only from the agent's
        perspective.  Inspecting the log is an out-of-band human /
        tooling concern (open the ``.jsonl`` file directly).
        """
        path = self._feedback_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # --- Seeding ---

    def _has_sops(self, directory: Path) -> bool:
        if not directory.is_dir():
            return False
        return any(directory.rglob(f"*{SOP_SUFFIX}"))

    def _seed(self, seed_dir: Path) -> None:
        """Seed bundled SOPs into ``base_dir`` only when it's empty.

        If the user's storage directory already contains any SOP, we
        don't touch it — respecting what they've authored. When it has
        zero SOPs (first run, wiped directory, fresh machine) we copy
        every bundled SOP folder in full so sibling attachments like
        ``sop_creation_guide/sop_template.md`` travel with the SOP and
        the ``sop://{name}/{attachment}`` resources resolve.
        """
        if not self._has_sops(seed_dir):
            return
        if self._has_sops(self._base_dir):
            return

        for folder in sorted(seed_dir.iterdir()):
            if not folder.is_dir():
                continue
            # Folder must host an SOP file to qualify as an SOP folder.
            if not (folder / f"{folder.name}{SOP_SUFFIX}").is_file():
                continue
            dest = self._base_dir / folder.name
            shutil.copytree(folder, dest, dirs_exist_ok=True)


def _validate_storage_path(path_str: str) -> Path:
    """Validate that a storage directory path string is usable."""
    if not path_str:
        raise ValueError("Storage directory path must not be empty")
    if "\x00" in path_str:
        raise ValueError("Storage directory path must not contain null bytes")
    return Path(path_str)
