"""A second launch hands its request to the running app through the inbox."""

from __future__ import annotations

from swiftdrop import app
from swiftdrop.handoff import read_pending


def test_second_launch_asks_the_running_app_to_show(tmp_path, monkeypatch):
    activated = []
    monkeypatch.setattr(app, "_activate_running_instance", lambda: activated.append(True))
    app._hand_off(tmp_path, [], background=False)
    assert read_pending(tmp_path) == [{"type": "show"}]
    assert activated == [True]
    app._hand_off(tmp_path, [], background=True)  # a background start never pops the window up
    assert read_pending(tmp_path) == []


def test_second_launch_passes_links_on(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "_activate_running_instance", lambda: None)
    links = ["swiftdrop://add?url=https%3A%2F%2Fe.com%2Fa.zip", "swiftdrop://add?url=javascript%3Ax"]
    app._hand_off(tmp_path, links, background=False)
    assert read_pending(tmp_path) == [{"type": "add", "url": "https://e.com/a.zip"}]


def test_scheme_links_are_not_parsed_as_options():
    args = app._parse(["--background", "-psn_0_123"])
    assert args.background is True
