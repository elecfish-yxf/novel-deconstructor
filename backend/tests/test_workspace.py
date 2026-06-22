from novel_deconstructor.api.workspace import normalize_workspace_id


def test_normalize_workspace_id_strips_unsafe_chars():
    assert normalize_workspace_id(" ws_abc-123 ../ ") == "ws_abc-123"


def test_normalize_workspace_id_uses_fallback():
    assert normalize_workspace_id("../") == "anonymous"
