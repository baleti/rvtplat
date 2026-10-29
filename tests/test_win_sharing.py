"""Windows: a reader that opened the target without FILE_SHARE_DELETE (antivirus, indexer, preview pane) blocks os.replace.
atomic_write must succeed once the handle closes inside the retry budget, and fail cleanly (original intact, no temp file) when it never does."""
import os, sys, threading, time
import pytest
from rvtplat import fsio

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows sharing semantics')


def hold(path):
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    h = k.CreateFileW(path, 0x80000000, 0x1 | 0x2, None, 3, 0x80, None)      # GENERIC_READ, share READ|WRITE (no DELETE), OPEN_EXISTING
    assert h not in (None, wintypes.HANDLE(-1).value), ctypes.get_last_error()
    return k, h


def leftovers(d, keep):
    return sorted(set(os.listdir(d)) - set(keep))


def test_replace_waits_for_reader(tmp_path):
    p = str(tmp_path / 'm.dwg')
    with open(p, 'wb') as f: f.write(b'old' * 100)
    k, h = hold(p)
    t = threading.Timer(1.5, lambda: k.CloseHandle(h)); t.start()
    t0 = time.time()
    fsio.atomic_write(p, b'new' * 100)
    dt = time.time() - t0
    t.join()
    assert open(p, 'rb').read() == b'new' * 100
    assert dt >= 1.0, 'replace did not have to wait (sharing mode not effective?)'
    assert leftovers(tmp_path, ['m.dwg']) == []


def test_never_released_fails_cleanly(tmp_path, monkeypatch):
    p = str(tmp_path / 'm.dwg')
    with open(p, 'wb') as f: f.write(b'old' * 100)
    k, h = hold(p)
    real = fsio.replace_retry
    monkeypatch.setattr(fsio, 'replace_retry', lambda s, d, **kw: real(s, d, tries=4, delay=0.01, max_delay=0.05, **{x: y for x, y in kw.items() if x not in ('tries', 'delay', 'max_delay')}))
    try:
        with pytest.raises(OSError):
            fsio.atomic_write(p, b'new' * 100)
    finally:
        k.CloseHandle(h)
    assert open(p, 'rb').read() == b'old' * 100
    assert leftovers(tmp_path, ['m.dwg']) == [], 'temp file left behind after a failed replace'
