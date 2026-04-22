"""file_access allowlist."""

from pathlib import Path

from memoryagent.file_access import path_is_allowlisted_for_read


def test_allow_under_data_dir(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    f = data / "a" / "b.txt"
    f.parent.mkdir(parents=True)
    f.write_text("x", encoding="utf-8")
    assert path_is_allowlisted_for_read(f, data_dir=data, watched_roots=[])


def test_allow_under_watched_root(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    watch = tmp_path / "watch"
    watch.mkdir()
    f = watch / "note.md"
    f.write_text("# hi", encoding="utf-8")
    assert path_is_allowlisted_for_read(
        f,
        data_dir=data,
        watched_roots=[str(watch)],
    )


def test_deny_outside(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    f = other / "secret.txt"
    f.write_text("no", encoding="utf-8")
    assert not path_is_allowlisted_for_read(
        f,
        data_dir=data,
        watched_roots=[],
    )
