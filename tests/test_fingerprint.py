import os
from rvtplat import fsio

def test_same_second_edit_detected(tmp_path):
    p = str(tmp_path / 'a.bin'); open(p, 'wb').write(b'A' * 100)
    fp = fsio.fingerprint(p)
    open(p, 'wb').write(b'B' * 100)            # same size
    os.utime(p, ns=(fp[1], fp[1]))              # same (coarse) mtime
    assert fsio.changed_since(p, fp)

def test_touch_only_is_not_change(tmp_path):
    p = str(tmp_path / 'a.bin'); open(p, 'wb').write(b'A' * 100)
    fp = fsio.fingerprint(p)
    os.utime(p, ns=(fp[1] + 4_000_000_000, fp[1] + 4_000_000_000))
    assert not fsio.changed_since(p, fp)

def test_size_change_and_missing(tmp_path):
    p = str(tmp_path / 'a.bin'); open(p, 'wb').write(b'A')
    fp = fsio.fingerprint(p)
    open(p, 'ab').write(b'x')
    assert fsio.changed_since(p, fp)
    os.remove(p)
    assert fsio.changed_since(p, fp)

def test_2s_rounding(tmp_path):
    p = str(tmp_path / 'a.bin'); open(p, 'wb').write(b'A' * 10)
    fp = fsio.fingerprint(p)
    open(p, 'wb').write(b'Z' * 10)
    r = (fp[1] // 2_000_000_000) * 2_000_000_000   # FAT-style rounding
    os.utime(p, ns=(r, r))
    assert fsio.changed_since(p, fp)
