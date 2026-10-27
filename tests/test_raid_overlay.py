"""Render-path checks for the overlay; skipped where Tk or a display is unavailable."""
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

import tacticus_raid_advisor as advisor  # noqa: E402
import tacticus_raid_overlay as overlay  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SAMPLE_USER_ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display available: {exc}")
    window.withdraw()
    yield window
    window.destroy()


def label_texts(widget):
    texts = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            texts.append(child.cget("text"))
        texts.extend(label_texts(child))
    return texts


def test_overlay_renders_advice_from_payloads(root):
    payloads = (
        advisor.read_json(EXAMPLES / "sample_guild_raid.json"),
        advisor.read_json(EXAMPLES / "sample_player.json"),
    )
    view = overlay.RaidOverlay(root, lambda: payloads, SAMPLE_USER_ID, refresh_seconds=60)

    view.results.put(("ok", payloads))
    view._collect_result()
    view._update_live()

    texts = label_texts(view.body)
    assert "1. Bomb Legendary Makari (Prime)" in texts
    assert "2. Battle Legendary Ghazghkull (Boss)" in texts
    assert view.title_var.get() == "Guild Raid · Season 109"
    assert view.tokens_var.get().startswith("Raid tokens 3/3 (full)")


def test_overlay_reports_fetch_errors_in_footer(root):
    view = overlay.RaidOverlay(root, lambda: None, None, refresh_seconds=60)

    view.results.put(("error", RuntimeError("HTTP 403 (FORBIDDEN)")))
    view._collect_result()
    view._update_live()

    assert view.footer_var.get() == "Refresh failed: HTTP 403 (FORBIDDEN)"
