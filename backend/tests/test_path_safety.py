from pathlib import Path

import pytest
from fastapi import HTTPException

from novel_deconstructor.config import get_settings
from novel_deconstructor.services.path_safety import project_output_dir, safe_relative_file


def test_output_path_stays_inside_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("ALLOW_ABSOLUTE_OUTPUT_PATH", "false")
    get_settings.cache_clear()

    path = project_output_dir("测试项目", "relative")

    assert path.is_relative_to((tmp_path / "outputs").resolve())


def test_output_path_rejects_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("ALLOW_ABSOLUTE_OUTPUT_PATH", "false")
    get_settings.cache_clear()

    with pytest.raises(HTTPException):
        project_output_dir("测试项目", "../escape")


def test_safe_relative_file(tmp_path: Path):
    base = tmp_path / "job"
    base.mkdir()
    target = base / "chapter.md"
    target.write_text("ok", encoding="utf-8")

    assert safe_relative_file(base, "chapter.md") == target.resolve()

    with pytest.raises(HTTPException):
        safe_relative_file(base, "../chapter.md")
