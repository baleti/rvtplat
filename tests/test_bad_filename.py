"""bad_filename (merged from the rvt-viewer vendored copy): names Windows would mangle or treat as devices are flagged on every OS."""
from rvtplat import fsio

F = fsio.bad_filename


def test_bad_names():
    for n in ('CON.rvt', 'con.rvt', 'NUL', 'com1.txt.rvt', 'LPT9.rvt', 'a.rvt.', 'a.rvt ', 'a:b.rvt', 'a?.rvt', 'x*.rvt',
              'a\x01.rvt', 'a|b.rvt', 'é' * 130 + '.rvt', '', '..', 'CONIN$.rvt', 'COM\u00b9.rvt', 'lpt\u00b2', 'COM\u00b3.dwg'):
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


def test_network_fs_kind_windows_branch(monkeypatch):
    import ntpath, types, ctypes
    monkeypatch.setattr(fsio, "_WIN", True)
    monkeypatch.setattr(fsio.os.path, "abspath", lambda p: p)
    monkeypatch.setattr(fsio.os.path, "splitdrive", ntpath.splitdrive)
    types_by_drive = {"Z:\\": 4, "C:\\": 3}
    fake = types.SimpleNamespace(kernel32=types.SimpleNamespace(GetDriveTypeW=lambda d: types_by_drive.get(d, 1)))
    monkeypatch.setattr(ctypes, "windll", fake, raising=False)
    assert fsio.network_fs_kind("\\\\srv\\share\\a.rvt") == "unc"
    assert fsio.network_fs_kind("\\\\?\\UNC\\srv\\share\\a.rvt") == "unc"
    assert fsio.network_fs_kind("Z:\\proj\\a.rvt") == "remote-drive"
    assert fsio.network_fs_kind("C:\\proj\\a.rvt") == ""
    assert fsio.network_fs_kind("\\\\?\\C:\\proj\\a.rvt") == ""


def test_network_fs_kind_darwin_branch(monkeypatch):
    import subprocess, types
    out = ("/dev/disk3s1 on / (apfs, local, journaled)\n"
           "//user@nas.local/share on /Volumes/share (smbfs, nodev, nosuid, mounted by user)\n"
           "/dev/disk4s1 on /Volumes/share/inner (apfs, local)\n"
           "macfuse@0 on /Volumes/fuse (macfuse, nodev)\n")
    monkeypatch.setattr(fsio.sys, "platform", "darwin")
    monkeypatch.setattr(fsio.os.path, "realpath", lambda p: p)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=out))
    assert fsio.network_fs_kind("/Volumes/share/a.rvt") == "smbfs"
    assert fsio.network_fs_kind("/Volumes/share/inner/a.rvt") == ""
    assert fsio.network_fs_kind("/Volumes/fuse/a.rvt") == "macfuse"
    assert fsio.network_fs_kind("/Users/u/a.rvt") == ""


def test_bad_filename_never_raises_on_lone_surrogates():
    assert F("a\ud800b.rvt") == ""                       # unpaired UTF-16 unit (valid on NTFS)
    assert F("a\udc80b.rvt") == ""                       # an escaped raw byte of a Linux name
    assert F("\udcff" * 200 + ".rvt") == ""              # 200 raw bytes: below 255, must not be over-counted
    assert F("\udcff" * 300 + ".rvt")                    # 300 raw bytes: too long
    assert F("\ud800" * 100)                             # 100 lone units = 300 bytes in UTF-8
