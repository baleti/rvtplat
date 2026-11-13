"""Concurrent safe_save of one file (threads and processes): the target and the .bak are always complete payloads, no stray temp files."""
import os, sys, hashlib, threading, subprocess
from rvtplat import fsio


def payload(i, size=1500000):
    body = hashlib.sha1(str(i).encode()).digest() * (size // 20)
    return b"K%010d" % i + hashlib.sha1(body).digest() + body


def valid(b):
    return len(b) > 31 and b[:1] == b"K" and hashlib.sha1(b[31:]).digest() == b[11:31]


def test_threads(tmp_path):
    p = str(tmp_path / "m.rvt"); fsio.atomic_write(p, payload(0)); errs = []
    def w(k):
        for j in range(25):
            try: fsio.safe_save(p, payload(k * 1000 + j))
            except Exception as e: errs.append(repr(e))
    ts = [threading.Thread(target=w, args=(k,)) for k in range(1, 5)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs, errs[:3]
    assert valid(open(p, "rb").read()) and valid(open(p + ".bak", "rb").read())
    assert sorted(os.listdir(tmp_path)) == ["m.rvt", "m.rvt.bak"]


CHILD = "import sys; sys.path.insert(0, sys.argv[1])\nfrom rvtplat import fsio\nsys.path.insert(0, sys.argv[4])\nfrom test_concurrent_save import payload\nk=int(sys.argv[3])\nfor j in range(25): fsio.safe_save(sys.argv[2], payload(k*1000+j))\n"


def test_processes(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); here = os.path.dirname(os.path.abspath(__file__))
    p = str(tmp_path / "m.rvt"); fsio.atomic_write(p, payload(0))
    ps = [subprocess.Popen([sys.executable, "-c", CHILD, root, p, str(k), here]) for k in range(1, 5)]
    assert [x.wait() for x in ps] == [0, 0, 0, 0]
    assert valid(open(p, "rb").read()) and valid(open(p + ".bak", "rb").read())
    assert sorted(os.listdir(tmp_path)) == ["m.rvt", "m.rvt.bak"]
