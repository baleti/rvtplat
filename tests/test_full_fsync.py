"""macOS durability: atomic writes must ask the drive to flush (F_FULLFSYNC); other systems use os.fsync."""
import os, sys, types
from rvtplat import fsio


def test_darwin_uses_f_fullfsync(monkeypatch, tmp_path):
    calls = []
    fake = types.SimpleNamespace(F_FULLFSYNC=51, fcntl=lambda fd, cmd, *a: calls.append((cmd,)))
    monkeypatch.setitem(sys.modules, 'fcntl', fake)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    fsio.atomic_write(str(tmp_path / 'a.bin'), b'x' * 10)
    assert calls and all(c == (51,) for c in calls), 'F_FULLFSYNC not requested for the file and the directory'
    assert (tmp_path / 'a.bin').read_bytes() == b'x' * 10


def test_darwin_falls_back_when_refused(monkeypatch, tmp_path):
    def refuse(fd, cmd, *a): raise OSError(25, 'not supported (network volume)')
    monkeypatch.setitem(sys.modules, 'fcntl', types.SimpleNamespace(F_FULLFSYNC=51, fcntl=refuse))
    monkeypatch.setattr(sys, 'platform', 'darwin')
    seen = []
    real = os.fsync
    monkeypatch.setattr(os, 'fsync', lambda fd: (seen.append(fd), real(fd))[1])
    fsio.atomic_write(str(tmp_path / 'b.bin'), b'y')
    assert seen, 'os.fsync fallback not used'
    assert (tmp_path / 'b.bin').read_bytes() == b'y'


def test_other_systems_use_os_fsync(monkeypatch, tmp_path):
    seen = []
    real = os.fsync
    monkeypatch.setattr(os, 'fsync', lambda fd: (seen.append(fd), real(fd))[1])
    fsio.atomic_write(str(tmp_path / 'c.bin'), b'z')
    assert seen
