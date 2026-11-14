from dracoconv import updates


def test_newer_version_is_reported_once_a_day():
    assert updates.newer_version(lambda: {"tag_name": "v9.0.0"}, current="0.2.0") == "9.0.0"
    assert updates.newer_version(lambda: {"tag_name": "v0.2.0"}, current="0.2.0") is None
    assert updates.newer_version(lambda: {"tag_name": "v0.1.9"}, current="0.2.0") is None

    def offline():
        raise OSError("no network")

    assert updates.newer_version(offline, current="0.2.0") is None


def test_check_is_due_daily_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("DRACOCONV_NO_UPDATE_CHECK")
    assert updates.due()  # jamais vérifié
    updates.newer_version(lambda: {"tag_name": "v0.0.1"})
    assert not updates.due()
    assert updates.due(now=__import__("time").time() + updates.INTERVAL_S + 1)
    updates.set_enabled(False)
    assert not updates.enabled() and not updates.due(now=10 ** 12)
