from homebase_camera.streaming import _presentation_html, _status_panel_html, _zone_editor_html


def test_presentation_page_is_read_only_and_masks_invalid_analysis() -> None:
    html = _presentation_html()

    assert "/stream.mjpg" in html
    assert "/api/preflight" in html
    assert "판정 보류" in html
    assert "method: 'POST'" not in html
    assert "/api/baseline" not in html
    assert "refreshRunning" in html
    assert "AbortController" in html


def test_status_panel_uses_binary_person_labels() -> None:
    html = _status_panel_html()

    assert "사람 없음" in html
    assert "사람 있음" in html
    assert "status 2" not in html
    assert "refreshRunning" in html
    assert "AbortController" in html


def test_zone_editor_status_polling_cannot_overlap() -> None:
    html = _zone_editor_html()

    assert "statusLoading" in html
    assert "AbortController" in html
    assert "signal: controller.signal" in html
