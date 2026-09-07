"""Tests for conversation ID detection in existing markdown files."""

from pathlib import Path

from convoviz.io.writers import _get_conversation_id_from_file


def test_yaml_conversation_id_takes_precedence_over_marker(tmp_path: Path) -> None:
    """Use YAML conversation_id even when the body contains another marker."""
    path = tmp_path / "conversation.md"
    path.write_text(
        "---\n"
        'conversation_id: "yaml-id"\n'
        'chat_link: "https://chatgpt.com/c/yaml-id"\n'
        "---\n"
        "# Conversation\n\n"
        "Some quoted content:\n\n"
        "<!-- conversation_id=body-id -->\n",
        encoding="utf-8",
    )

    assert _get_conversation_id_from_file(path) == "yaml-id"
