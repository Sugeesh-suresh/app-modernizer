"""
UX design references for the JSP -> React pattern.

The user can attach mockups (images or PDF design exports) at upload time.
They are stored outside the migration workspace, so they never show up in the
code diff, and are attached as inline parts to the model requests of the
agents that shape the UI (the planner and the React frontend generator), so
the generated frontend follows the provided designs.
"""
import json
import logging
import pathlib
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

STATE_KEY = "ux_designs_json"

MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}
MAX_FILES = 10
MAX_FILE_BYTES = 5 * 1024 * 1024
# Gemini caps a whole inline request at 20 MB; leave room for the instruction and tool traffic.
MAX_TOTAL_BYTES = 15 * 1024 * 1024

logger = logging.getLogger(__name__)


class UxDesignError(ValueError):
    """An upload that breaks one of the limits above. The message is shown to the user."""


def _safe_name(name: str) -> str:
    # Drop any client-supplied directories (including Windows-style ones).
    return pathlib.PurePosixPath(name.replace("\\", "/")).name or "design"


def validate(files: list[tuple[str, bytes]]) -> None:
    if len(files) > MAX_FILES:
        raise UxDesignError(f"At most {MAX_FILES} UX design files can be attached.")
    total = 0
    for name, data in files:
        if pathlib.PurePosixPath(_safe_name(name)).suffix.lower() not in MIME_TYPES:
            raise UxDesignError(f"'{name}' is not a supported UX design file (PNG, JPG, WebP, GIF or PDF).")
        if not data:
            raise UxDesignError(f"'{name}' is empty.")
        if len(data) > MAX_FILE_BYTES:
            raise UxDesignError(f"'{name}' is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
        total += len(data)
    if total > MAX_TOTAL_BYTES:
        raise UxDesignError(f"The UX design files add up to more than {MAX_TOTAL_BYTES // (1024 * 1024)} MB.")


def save(files: list[tuple[str, bytes]], dest_dir: pathlib.Path) -> list[dict]:
    """Validates the files, writes them into dest_dir and returns the manifest kept in session state."""
    validate(files)
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (name, data) in enumerate(files, start=1):
        safe = _safe_name(name)
        path = dest_dir / f"{i:02d}-{safe}"
        path.write_bytes(data)
        manifest.append({
            "name": safe,
            "path": str(path),
            "mime_type": MIME_TYPES[path.suffix.lower()],
            "size": len(data),
        })
    return manifest


def _design_parts(manifest: list[dict]) -> list[types.Part]:
    parts: list[types.Part] = []
    for i, design in enumerate(manifest, start=1):
        try:
            data = pathlib.Path(design["path"]).read_bytes()
        except (OSError, KeyError):
            logger.warning("UX design file missing, skipping: %s", design.get("path"))
            continue
        parts.append(types.Part(text=f"UX design {i}: {design['name']}"))
        parts.append(types.Part.from_bytes(data=data, mime_type=design["mime_type"]))
    return parts


def make_ux_design_callback():
    """before_model_callback that attaches the session's UX designs to every model request.

    The designs go into the request's first user message. A new Content replaces it rather than
    the existing one being edited, so the images are never written back into the session's
    stored events. Runs on every call because the agents use include_contents="none"."""

    def _attach(callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]:
        try:
            manifest = json.loads(callback_context.state.get(STATE_KEY) or "[]")
        except (TypeError, ValueError):
            return None
        parts = _design_parts(manifest) if manifest else []
        if not parts:
            return None

        design_parts = [
            types.Part(text=(
                f"## Attached UX designs ({len(parts) // 2})\n"
                "The user supplied these designs for the new React UI. Follow them for layout, "
                "component structure, colours, typography, spacing and visual states. The original "
                "JSP source and the BFF API contract stay the reference for data, fields and behaviour."
            )),
            *parts,
        ]
        for idx, content in enumerate(llm_request.contents):
            if content.role == "user":
                llm_request.contents[idx] = types.Content(
                    role="user", parts=design_parts + list(content.parts or []),
                )
                return None
        llm_request.contents.insert(0, types.Content(role="user", parts=design_parts))
        return None

    return _attach
