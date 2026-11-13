"""Fail every os-level call of one safe_save in turn (the Nth call raises OSError): the target must stay exactly the old or exactly the new bytes,
no temp file may remain, and the next save must work."""
import os, shutil, errno, pytest
from rvtplat import fsio

NAMES = ("open", "fsync", "replace", "chmod", "mkstemp", "remove", "stat", "fdopen")
OLD, NEW = b"OLD" * 5000, b"NEW" * 5000


def _count_calls(tmp_path):
    n = {"c": 0}
    import tempfile
    patches = []
    def wrap(mod, name):
        real = getattr(mod, name)
        def f(*a, **k):
            n["c"] += 1
            return real(*a, **k)
        return mod, name, real, f
    for mod, name in ((os, "open"), (os, "fsync"), (os, "replace"), (os, "chmod"), (tempfile, "mkstemp"), (os, "remove"), (shutil, "copy2")):
        patches.append(wrap(mod, name))
    for mod, name, real, f in patches: setattr(mod, name, f)
    try:
        p = tmp_path / "count.rvt"; p.write_bytes(OLD); fsio.safe_save(str(p), NEW)
    finally:
        for mod, name, real, f in patches: setattr(mod, name, real)
    return n["c"]


def test_failure_at_every_call_never_tears_the_file(tmp_path, monkeypatch):
    import tempfile
    total = _count_calls(tmp_path)
    raised = 0
    assert total >= 6
    for k in range(1, total + 1):
        d = tmp_path / ("k%d" % k); d.mkdir()
        p = d / "m.rvt"; p.write_bytes(OLD)
        state = {"c": 0}
        def make(mod, name):
            real = getattr(mod, name)
            def f(*a, **kw):
                state["c"] += 1
                if state["c"] == k:
                    raise OSError(errno.EIO, "injected failure at call %d (%s)" % (k, name))
                return real(*a, **kw)
            return real, f
        saved = []
        for mod, name in ((os, "open"), (os, "fsync"), (os, "replace"), (os, "chmod"), (tempfile, "mkstemp"), (os, "remove"), (shutil, "copy2")):
            real, f = make(mod, name); saved.append((mod, name, real)); setattr(mod, name, f)
        try:
            try:
                fsio.safe_save(str(p), NEW)
            except OSError:
                raised += 1
        finally:
            for mod, name, real in saved: setattr(mod, name, real)
        cur = p.read_bytes()
        assert cur in (OLD, NEW), "torn target when call %d failed" % k
        left = [f for f in os.listdir(d) if f not in ("m.rvt", "m.rvt.bak")]
        assert left == [], "temp files left when call %d failed: %s" % (k, left)
        bak = d / "m.rvt.bak"
        if bak.exists():
            assert bak.read_bytes() == OLD, "bad .bak when call %d failed" % k
        fsio.safe_save(str(p), b"again" * 10)           # the next save works
        assert p.read_bytes() == b"again" * 10
    assert raised >= 3, 'the injection must really make saves fail (else the test proves nothing)'
