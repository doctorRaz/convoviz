"""Tests for conversation ID detection in existing Markdown files."""

from pathlib import Path

from convoviz.io.writers import _get_conversation_id_from_file



def test_get_conversation_id_from_yaml_without_html_marker(tmp_path: Path) -> None:
    """Detect conversation_id from YAML when the HTML marker is absent."""
    conversation_id = "6a8f26c6-2ae0-83eb-a048-57f9270485a8"
    filepath = tmp_path / "conversation.md"
    filepath.write_text(
        "---\n"
        'title: "GPT_Archivist. Conversation_id"\n'
        'chat_link: "https://chatgpt.com/c/6a8f26c6-2ae0-83eb-a048-57f9270485a8"\n'
        'create_time: "2026-08-26T17:48:24.742073+00:00"\n'
        'update_time: "2026-08-26T19:25:59.767687+00:00"\n'
        'model: "gpt-5-6"\n'
        "used_plugins: []\n"
        "message_count: 20\n"
        'conversation_id: "6a8f26c6-2ae0-83eb-a048-57f9270485a8"\n'
        "---\n",
        encoding="utf-8",
    )

    assert _get_conversation_id_from_file(filepath) == conversation_id
