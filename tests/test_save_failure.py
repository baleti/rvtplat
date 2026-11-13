import os
import pytest
from rvtplat import fsio


def test_safe_save_unicode_space_dir_keeps_backup(tmp_path):
    d = tmp_path / "Zoë Müller" / "my project"
    d.mkdir(parents=True)
    p = str(d / "Model ä.rvt")
    fsio.atomic_write(p, b"v1")
    fsio.safe_save(p, b"v2")
    assert open(p, "rb").read() == b"v2"
    baks = [f for f in os.listdir(d) if f != "Model ä.rvt"]
    assert any(open(d / f, "rb").read() == b"v1" for f in baks)


def test_failed_replace_leaves_original_and_no_temp(tmp_path, monkeypatch):
    p = str(tmp_path / "a.dwg")
    fsio.atomic_write(p, b"orig")
    def boom(src, dst):
        raise PermissionError(13, "sharing violation")
    monkeypatch.setattr(os, "replace", boom)
    rr = fsio.replace_retry
    monkeypatch.setattr(fsio, "replace_retry", lambda s_, d_, **k: rr(s_, d_, tries=2, delay=0.001, **{x: y for x, y in k.items() if x not in ("tries", "delay")}))
    with pytest.raises(OSError):
        fsio.atomic_write(p, b"new")
    monkeypatch.undo()
    assert open(p, "rb").read() == b"orig"
    assert os.listdir(tmp_path) == ["a.dwg"]
