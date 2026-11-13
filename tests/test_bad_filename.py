"""bad_filename (merged from the rvt-viewer vendored copy): names Windows would mangle or treat as devices are flagged on every OS."""
from rvtplat import fsio

F = fsio.bad_filename


def test_bad_names():
    for n in ('CON.rvt', 'con.rvt', 'NUL', 'com1.txt.rvt', 'LPT9.rvt', 'a.rvt.', 'a.rvt ', 'a:b.rvt', 'a?.rvt', 'x*.rvt',
              'a\x01.rvt', 'a|b.rvt', 'é' * 130 + '.rvt', '', '..', 'CONIN$.rvt'):
        assert F(n), n


def test_ok_names():
    for n in ('Plan A.rvt', 'Ünï 日本.rvt', 'console.rvt', 'com10.rvt', 'a.b.c.rvt', 'AUXILIARY.rvt', '.hidden.rvt'):
        assert F(n) == '', n


def test_network_fs_kind_never_raises(tmp_path):
    assert isinstance(fsio.network_fs_kind(str(tmp_path)), str)
    fsio.network_fs_kind('/nonexistent/\x00bad')      # must not raise


def test_network_fs_kind_linux_mountinfo(monkeypatch, tmp_path):
    import io, sys, builtins
    if not sys.platform.startswith("linux"):
        import pytest; pytest.skip("parses /proc/self/mountinfo")
    mi = ("20 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
          "31 20 0:27 / /mnt/share rw - cifs //srv/s rw\n"
          "32 20 0:28 / /mnt/my\\040nas rw - nfs4 srv:/x rw\n"
          "33 31 8:2 / /mnt/share/local rw - ext4 /dev/sdb1 rw\n")
    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda p, *a, **k: io.StringIO(mi) if p == "/proc/self/mountinfo" else real_open(p, *a, **k))
    monkeypatch.setattr(fsio.os.path, "realpath", lambda p: p)
    assert fsio.network_fs_kind("/mnt/share/doc/a.rvt") == "cifs"
    assert fsio.network_fs_kind("/mnt/my nas/a.rvt") == "nfs4"
    assert fsio.network_fs_kind("/mnt/share/local/a.rvt") == ""      # a local disk mounted INSIDE a share: longest mount point wins
    assert fsio.network_fs_kind("/home/u/a.rvt") == ""
