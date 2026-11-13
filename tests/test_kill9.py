"""SIGKILL a process in the middle of atomic_write loops: the target must always be a complete old or new payload, never torn."""
import os, sys, time, random, signal, hashlib, subprocess
import pytest

CHILD = r'''
import sys, os, hashlib
sys.path.insert(0, sys.argv[1])
from rvtplat import fsio
p, size = sys.argv[2], int(sys.argv[3]); i = 0
while True:
    i += 1
    body = hashlib.sha1(str(i).encode()).digest() * (size // 20)
    fsio.safe_save(p, b'K%010d' % i + hashlib.sha1(body).digest() + body)
'''


def valid(b):
    if len(b) < 31 or b[:1] != b'K':
        return False
    body = b[31:]
    return hashlib.sha1(body).digest() == b[11:31]


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="POSIX kill")
def test_sigkill_never_leaves_torn_target(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = str(tmp_path / "m.rvt")
    body = hashlib.sha1(b"0").digest() * 5000
    open(p, "wb").write(b"K%010d" % 0 + hashlib.sha1(body).digest() + body)
    rnd = random.Random(7)
    for _ in range(30):
        c = subprocess.Popen([sys.executable, "-I", "-c", CHILD, root, p, "3000000"])
        time.sleep(rnd.uniform(0.05, 0.4))
        c.send_signal(signal.SIGKILL); c.wait()
        assert valid(open(p, "rb").read()), "torn target after SIGKILL"
        if os.path.exists(p + ".bak"):
            assert valid(open(p + ".bak", "rb").read()), "torn .bak after SIGKILL"
    left = [f for f in os.listdir(tmp_path) if f not in ("m.rvt", "m.rvt.bak") and not f.endswith(".tmp")]
    assert left == []
