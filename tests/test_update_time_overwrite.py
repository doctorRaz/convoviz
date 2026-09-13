"""Tests for update_time-aware conversation overwrite behavior."""

from datetime import UTC, datetime
from pathlib import Path

from convoviz.config import AuthorHeaders, ConversationConfig
from convoviz.io.writers import save_conversation
from convoviz.models import Conversation


def create_conversation(
    title: str, update_time: datetime, conversation_id: str
) -> Conversation:
    """Create a minimal conversation for overwrite tests."""
    return Conversation(
        title=title,
        create_time=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        update_time=update_time,
        mapping={
            "root": {
                "id": "root",
                "message": None,
                "parent": None,
                "children": ["user_node"],
            },
            "user_node": {
                "id": "user_node",
                "message": {
                    "id": "user_node",
                    "author": {"role": "user", "metadata": {}},
                    "create_time": update_time.timestamp(),
                    "update_time": update_time.timestamp(),
                    "content": {"content_type": "text", "parts": [title]},
                    "status": "finished_successfully",
                    "end_turn": True,
                    "weight": 1.0,
                    "metadata": {},
                    "recipient": "all",
                },
                "parent": "root",
                "children": [],
            },
        },
        current_node="user_node",
        conversation_id=conversation_id,
    )


def save(conv: Conversation, path: Path) -> Path:
    """Save a conversation using the default rendering configuration."""
    return save_conversation(conv, path, ConversationConfig(), AuthorHeaders())


def test_newer_update_time_overwrites_same_conversation(tmp_path: Path) -> None:
    """A newer version replaces an existing file with the same conversation ID."""
    path = tmp_path / "Test.md"
    old = create_conversation("Old", datetime(2024, 1, 1, 11, tzinfo=UTC), "id1")
    new = create_conversation("New", datetime(2024, 1, 1, 12, tzinfo=UTC), "id1")

    save(old, path)
    result = save(new, path)

    assert result == path
    assert "New" in path.read_text(encoding="utf-8")


def test_equal_update_time_skips_overwrite(tmp_path: Path) -> None:
    """An equal version is not rewritten and its filesystem timestamp is preserved."""
    path = tmp_path / "Test.md"
    first = create_conversation("First", datetime(2024, 1, 1, 12, tzinfo=UTC), "id1")
    equal = create_conversation("Equal", datetime(2024, 1, 1, 12, tzinfo=UTC), "id1")

    save(first, path)
    original = path.read_text(encoding="utf-8")
    original_mtime = path.stat().st_mtime

    save(equal, path)

    assert path.read_text(encoding="utf-8") == original
    assert path.stat().st_mtime == original_mtime


def test_older_update_time_skips_overwrite(tmp_path: Path) -> None:
    """An older version does not replace a newer existing file."""
    path = tmp_path / "Test.md"
    newer = create_conversation("Newer", datetime(2024, 1, 1, 12, tzinfo=UTC), "id1")
    older = create_conversation("Older", datetime(2024, 1, 1, 11, tzinfo=UTC), "id1")

    save(newer, path)
    original = path.read_text(encoding="utf-8")

    save(older, path)

    assert path.read_text(encoding="utf-8") == original


def test_missing_existing_update_time_keeps_legacy_overwrite(tmp_path: Path) -> None:
    """A matching ID without update_time keeps the legacy overwrite behavior."""
    path = tmp_path / "Test.md"
    path.write_text('---\nconversation_id: "id1"\n---\n\nLegacy\n', encoding="utf-8")
    new = create_conversation("New", datetime(2024, 1, 1, 12, tzinfo=UTC), "id1")

    save(new, path)

    assert "New" in path.read_text(encoding="utf-8")


def test_different_conversation_id_still_creates_incremented_file(
    tmp_path: Path,
) -> None:
    """A different conversation ID keeps the existing suffix-based conflict behavior."""
    path = tmp_path / "Test.md"
    first = create_conversation("First", datetime(2024, 1, 1, 12, tzinfo=UTC), "id1")
    other = create_conversation("Other", datetime(2024, 1, 1, 13, tzinfo=UTC), "id2")

    save(first, path)
    result = save(other, path)

    assert result == tmp_path / "Test (1).md"
    assert path.exists()
    assert result.exists()
