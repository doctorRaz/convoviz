"""Writing functions for conversations and collections."""

import contextlib
import logging
import re
from datetime import datetime
from os import utime as os_utime
from pathlib import Path
from urllib.parse import quote

from orjson import OPT_INDENT_2, dumps
from tqdm import tqdm

from convoviz.config import AuthorHeaders, ConversationConfig, FolderOrganization
from convoviz.io.assets import (
    AssetIndex,
    build_asset_index,
    copy_asset,
    resolve_asset_path,
)
from convoviz.models import Conversation, ConversationCollection
from convoviz.renderers import render_conversation
from convoviz.utils import sanitize

logger = logging.getLogger(__name__)

# Month names for folder naming
_MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def get_date_folder_path(conversation: Conversation) -> Path:
    """Get the date-based folder path for a conversation."""
    create_time = conversation.create_time
    month_name = _MONTH_NAMES[create_time.month - 1]
    return Path(str(create_time.year)) / f"{create_time.month:02d}-{month_name}"


_ID_SCAN_LIMIT = 128 * 1024


def _get_conversation_metadata_from_file(
    filepath: Path,
) -> tuple[str | None, datetime | None]:
    """Extract conversation_id and update_time from an existing Markdown file.

    Scans a bounded prefix of the file to avoid loading huge files.
    """
    try:
        with filepath.open("r", encoding="utf-8") as f:
            content = f.read(_ID_SCAN_LIMIT)

        conversation_id: str | None = None
        marker = re.search(
            r"<!--\s*conversation_id=([^>\s]+)\s*-->",
            content,
            re.IGNORECASE,
        )
        if marker:
            conversation_id = marker.group(1)
        else:
            match = re.search(
                r'^conversation_id:\s*"([^"]+)"',
                content,
                re.MULTILINE,
            )
            if match:
                conversation_id = match.group(1)
            else:
                match = re.search(
                    r'^chat_link:\s*"https://(?:chatgpt\.com|chat\.openai\.com)/c/([^"]+)"',
                    content,
                    re.MULTILINE,
                )
                if match:
                    conversation_id = match.group(1)

        update_time: datetime | None = None
        match = re.search(
            r'^update_time:\s*"([^"]+)"',
            content,
            re.MULTILINE,
        )
        if match:
            with contextlib.suppress(ValueError):
                update_time = datetime.fromisoformat(match.group(1))
    except Exception:
        return None, None
    else:
        return conversation_id, update_time


def _get_conversation_id_from_file(filepath: Path) -> str | None:
    """Extract conversation_id from an existing markdown file's YAML frontmatter."""
    conversation_id, _ = _get_conversation_metadata_from_file(filepath)
    return conversation_id


def _build_markdown_filename(
    title: str,
    *,
    prepend_timestamp: bool,
    create_time: datetime,
    suffix: str = ".md",
    max_length: int = 255,
) -> str:
    sanitized_title = sanitize(title, preserve_unicode=True)
    prefix = (
        f"{create_time.strftime('%Y-%m-%d_%H-%M-%S')} - "
        if prepend_timestamp
        else ""
    )
    available = max_length - len(prefix) - len(suffix)
    truncated = "untitled" if available < 1 else sanitized_title[:available]
    return f"{prefix}{truncated}{suffix}"


def save_conversation(
    conversation: Conversation,
    filepath: Path,
    config: ConversationConfig,
    headers: AuthorHeaders,
    source_paths: list[Path] | None = None,
    asset_indexes: dict[Path, AssetIndex] | None = None,
) -> Path:
    """Save a conversation to a markdown file.

    Same conversation IDs identify the same conversation. For an existing file
    with that ID, a newer incoming update_time replaces it; an equal or older
    incoming update_time is skipped. If the existing update_time is missing,
    the legacy overwrite behavior is preserved. Different IDs still use suffixes.
    """
    base_name = sanitize(filepath.stem, preserve_unicode=True)
    final_path = filepath
    counter = 0

    while final_path.exists():
        existing_id, existing_update_time = _get_conversation_metadata_from_file(
            final_path
        )
        if existing_id == conversation.conversation_id:
            if (
                existing_update_time is not None
                and conversation.update_time <= existing_update_time
            ):
                logger.debug(
                    f"Skipping {final_path.name}: existing update_time "
                    f"{existing_update_time.isoformat()} is newer or equal."
                )
                return final_path
            logger.debug(f"Identity match for {final_path.name}, overwriting.")
            break

        counter += 1
        final_path = filepath.with_name(
            f"{base_name} ({counter}){filepath.suffix}"
        )

    if asset_indexes is None:
        asset_indexes = {}
        if source_paths:
            asset_indexes = {
                path: build_asset_index(path) for path in source_paths
            }

    def asset_resolver(asset_id: str, target_name: str | None = None) -> str | None:
        if not source_paths:
            return None
        for source_path in source_paths:
            src_file = resolve_asset_path(
                source_path,
                asset_id,
                index=asset_indexes.get(source_path),
            )
            if src_file:
                return copy_asset(src_file, final_path.parent, target_name)
        return None

    markdown = render_conversation(
        conversation,
        config,
        headers,
        asset_resolver=asset_resolver,
    )
    with final_path.open("w", encoding="utf-8") as f:
        f.write(markdown)
    logger.debug(f"Saved conversation: {final_path}")

    timestamp = conversation.update_time.timestamp()
    os_utime(final_path, (timestamp, timestamp))
    return final_path


def _generate_year_index(year_dir: Path, year: str) -> None:
    """Generate a _index.md file for a year folder.

    Args:
        year_dir: Path to the year directory
        year: The year string (e.g., "2024")

    """
    months = sorted(
        [d.name for d in year_dir.iterdir() if d.is_dir()],
        key=lambda m: int(m.split("-")[0]),
    )
    lines = [f"# {year}", "", "## Months", ""]
    for month in months:
        month_name = month.split("-", 1)[1] if "-" in month else month
        lines.append(f"- [{month_name}]({month}/_index.md)")
    index_path = year_dir / "_index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.debug(f"Generated year index: {index_path}")


def _generate_root_index(root_dir: Path) -> None:
    """Generate a top-level _index.md that links to year indexes."""
    years = sorted(
        [d.name for d in root_dir.iterdir() if d.is_dir() and d.name.isdigit()]
    )
    if not years:
        return
    lines = ["# ChatGPT Conversations", "", "## Years", ""]
    for year in years:
        encoded = quote(f"{year}/_index.md")
        lines.append(f"- [{year}]({encoded})")
    index_path = root_dir / "_index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.debug(f"Generated root index: {index_path}")


def _generate_month_index(
    month_dir: Path,
    year: str,
    month: str,
    filename_to_title: dict[str, str] | None = None,
) -> None:
    """Generate a _index.md file for a month folder."""
    month_name = month.split("-", 1)[1] if "-" in month else month
    files = sorted(
        [f.name for f in month_dir.glob("*.md") if f.name != "_index.md"]
    )
    lines = [f"# {month_name} {year}", "", "## Conversations", ""]
    for file in files:
        title = file[:-3]
        if filename_to_title and file in filename_to_title:
            title = filename_to_title[file]
        lines.append(f"- [{title}]({quote(file)})")
    index_path = month_dir / "_index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.debug(f"Generated month index: {index_path}")


def save_collection(
    collection: ConversationCollection,
    directory: Path,
    config: ConversationConfig,
    headers: AuthorHeaders,
    *,
    folder_organization: FolderOrganization = FolderOrganization.FLAT,
    prepend_timestamp: bool = False,
    progress_bar: bool = False,
) -> None:
    """Save all conversations in a collection to markdown files."""
    directory.mkdir(parents=True, exist_ok=True)
    asset_indexes: dict[Path, AssetIndex] | None = None
    if collection.source_paths:
        asset_indexes = {
            path: build_asset_index(path) for path in collection.source_paths
        }
    filename_to_title: dict[str, str] = {}

    for conv in tqdm(
        collection.conversations,
        desc="Writing Markdown 📄 files",
        disable=not progress_bar,
    ):
        if folder_organization == FolderOrganization.DATE:
            date_folder = get_date_folder_path(conv)
            target_dir = directory / date_folder
            target_dir.mkdir(parents=True, exist_ok=True)
        else:
            target_dir = directory
        filename = _build_markdown_filename(
            conv.title,
            prepend_timestamp=prepend_timestamp,
            create_time=conv.create_time,
        )
        filepath = target_dir / filename
        saved_path = save_conversation(
            conv,
            filepath,
            config,
            headers,
            source_paths=collection.source_paths,
            asset_indexes=asset_indexes,
        )
        rel_path = saved_path.relative_to(directory)
        filename_to_title[str(rel_path)] = conv.title

    if folder_organization == FolderOrganization.DATE:
        for year_dir in directory.iterdir():
            if year_dir.is_dir() and year_dir.name.isdigit():
                for month_dir in year_dir.iterdir():
                    if month_dir.is_dir():
                        month_rel = month_dir.relative_to(directory)
                        month_mapping = {
                            Path(p).name: t
                            for p, t in filename_to_title.items()
                            if p.startswith(str(month_rel))
                        }
                        _generate_month_index(
                            month_dir,
                            year_dir.name,
                            month_dir.name,
                            filename_to_title=month_mapping,
                        )
                _generate_year_index(year_dir, year_dir.name)
        _generate_root_index(directory)


def save_custom_instructions(
    collection: ConversationCollection,
    filepath: Path,
) -> None:
    """Save all custom instructions from a collection to a JSON file."""
    instructions = collection.custom_instructions
    with filepath.open("w", encoding="utf-8") as f:
        f.write(dumps(instructions, option=OPT_INDENT_2).decode())
