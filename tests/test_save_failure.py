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


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks")
def test_save_through_symlink_updates_target(tmp_path):
    real = tmp_path / "real.dwg"; link = tmp_path / "link.dwg"
    real.write_bytes(b"old")
    try:
        os.symlink(real, link)
    except OSError:
        pytest.skip("no symlink privilege")
    fsio.safe_save(str(link), b"new")
    assert os.path.islink(link) and real.read_bytes() == b"new"
    assert (tmp_path / "real.dwg.bak").read_bytes() == b"old"


def test_enospc_during_write_keeps_original_and_cleans_temp(tmp_path):
    import errno
    p = str(tmp_path / "m.rvt")
    fsio.atomic_write(p, b"orig")
    def writer(f):
        f.write(b"partial")
        raise OSError(errno.ENOSPC, "No space left on device")
    with pytest.raises(OSError):
        fsio.atomic_write_stream(p, writer)
    assert open(p, "rb").read() == b"orig"
    assert os.listdir(tmp_path) == ["m.rvt"]


def test_transient_sharing_violation_then_success(tmp_path, monkeypatch):
    p = str(tmp_path / "m.dwg")
    fsio.atomic_write(p, b"orig")
    real = os.replace
    n = {"c": 0}
    def flaky(s, d):
        n["c"] += 1
        if n["c"] <= 3:
            raise PermissionError(13, "in use")
        return real(s, d)
    monkeypatch.setattr(os, "replace", flaky)
    fsio.atomic_write(p, b"new")
    monkeypatch.undo()
    assert n["c"] == 4 and open(p, "rb").read() == b"new" and os.listdir(tmp_path) == ["m.dwg"]


def test_cloud_placeholder_flags(tmp_path, monkeypatch):
    p = tmp_path / "x.rvt"; p.write_bytes(b"1")
    monkeypatch.setattr(fsio, "_WIN", True)
    class St:  # stand-in stat result
        def __init__(s, a): s.st_file_attributes = a
    for attrs, want in ((0x400000, True), (0x1000, True), (0x20, False)):
        monkeypatch.setattr(os, "stat", lambda q, a=attrs: St(a))
        assert fsio.is_cloud_placeholder(str(p)) is want


def test_non_busy_replace_error_fails_fast(tmp_path, monkeypatch):
    """a non-sharing error (e.g. EXDEV, ENOENT) must not burn the 12 s retry budget"""
    import errno, time
    p = str(tmp_path / "a.rvt")
    fsio.atomic_write(p, b"orig")
    def boom(s, d):
        raise OSError(errno.EXDEV, "cross-device")
    monkeypatch.setattr(os, "replace", boom)
    t = time.time()
    with pytest.raises(OSError):
        fsio.atomic_write(p, b"new")
    monkeypatch.undo()
    assert time.time() - t < 1 and open(p, "rb").read() == b"orig" and os.listdir(tmp_path) == ["a.rvt"]


def test_readonly_target_on_windows_fails_fast_but_sharing_retries(tmp_path, monkeypatch):
    import time
    p = tmp_path / "ro.dwg"; p.write_bytes(b"orig"); os.chmod(p, 0o444)
    monkeypatch.setattr(fsio, "_WIN", True)
    def denied(s, d):
        e = PermissionError(13, "denied"); e.winerror = 5; raise e
    monkeypatch.setattr(os, "replace", denied)
    t = time.time()
    with pytest.raises(PermissionError):
        fsio.replace_retry(str(tmp_path / "x"), str(p))
    assert time.time() - t < 1
    # sharing violation (32) on a writable target still retries
    os.chmod(p, 0o644); n = {"c": 0}
    def share(s, d):
        n["c"] += 1; e = PermissionError(13, "in use"); e.winerror = 32; raise e
    monkeypatch.setattr(os, "replace", share)
    with pytest.raises(PermissionError):
        fsio.replace_retry(str(tmp_path / "x"), str(p), tries=4, delay=0.001)
    assert n["c"] == 4


def test_mode_kept_and_readonly_refused_unless_allowed(tmp_path):
    import stat
    a = tmp_path / "a.rvt"; a.write_bytes(b"1"); os.chmod(a, 0o640)
    fsio.safe_save(str(a), b"2")
    assert stat.S_IMODE(os.stat(a).st_mode) == 0o640 and a.read_bytes() == b"2"
    b = tmp_path / "b.dwg"; b.write_bytes(b"1"); os.chmod(b, 0o444)
    if os.access(b, os.W_OK):
        pytest.skip("running as a user that ignores read-only (root)")
    with pytest.raises(PermissionError):
        fsio.safe_save(str(b), b"2")
    assert b.read_bytes() == b"1" and not (tmp_path / "b.dwg.bak").exists()
    fsio.safe_save(str(b), b"2", allow_readonly=True)
    assert b.read_bytes() == b"2" and stat.S_IMODE(os.stat(b).st_mode) == 0o444


def test_safe_save_does_not_recreate_a_vanished_folder(tmp_path):
    p = str(tmp_path / "usb" / "plan.dwg")
    with pytest.raises(OSError):
        fsio.safe_save(p, b"x")
    assert os.listdir(tmp_path) == []
    fsio.atomic_write(p, b"cache")          # caches still create their folder
    assert open(p, "rb").read() == b"cache"


def test_readonly_directory_fails_cleanly(tmp_path):
    d = tmp_path / "ro"; d.mkdir(); p = str(d / "a.rvt")
    fsio.atomic_write(p, b"orig"); os.chmod(d, 0o555)
    try:
        if os.access(d, os.W_OK):
            pytest.skip("root ignores directory modes")
        with pytest.raises(OSError):
            fsio.safe_save(p, b"new")
        assert open(p, "rb").read() == b"orig" and os.listdir(d) == ["a.rvt"]
    finally:
        os.chmod(d, 0o755)
