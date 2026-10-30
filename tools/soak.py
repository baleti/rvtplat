"""Soak: N atomic overwrites of one file while a second process reads it continuously.
Every payload is self-describing (header with length + sha1 of the body), so a reader can tell a torn/corrupt file at once.
usage: python tools/soak.py [N=500] [SIZE_KB=256] [DIR]    -> prints SOAK OK / SOAK FAILED with counts. Synthetic data only."""
import os, sys, hashlib, time, tempfile, multiprocessing as mp
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from rvtplat import fsio


def payload(i, size):
    body = hashlib.sha1(str(i).encode()).digest() * (size // 20)
    return b'SOAK%08d%08d' % (i, len(body)) + hashlib.sha1(body).digest() + body


def check(b):
    if len(b) < 40 or b[:4] != b'SOAK': return False
    n = int(b[12:20]); body = b[40:]
    return len(body) == n and hashlib.sha1(body).digest() == b[20:40]


def reader(path, stop, out):
    ok = bad = miss = 0
    while not stop.is_set():
        try:
            b = fsio.read_retry(path)
        except FileNotFoundError:
            miss += 1; continue
        except OSError:
            miss += 1; continue
        if check(b): ok += 1
        else: bad += 1
    out.put((ok, bad, miss))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    kb = int(sys.argv[2]) if len(sys.argv) > 2 else 256
    d = sys.argv[3] if len(sys.argv) > 3 else tempfile.mkdtemp(prefix='soak_')
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'doc.bin'); fsio.atomic_write(p, payload(0, kb * 1024))
    stop = mp.Event(); q = mp.Queue()
    r = mp.Process(target=reader, args=(p, stop, q)); r.start()
    t0 = time.time(); werr = 0
    for i in range(1, n + 1):
        try:
            fsio.safe_save(p, payload(i, kb * 1024), keep_backup=(i % 10 == 0))
        except OSError as e:
            werr += 1; print('write error', i, e)
    stop.set(); ok, bad, miss = q.get(timeout=60); r.join()
    final = check(open(p, 'rb').read())
    left = sorted(f for f in os.listdir(d) if f not in ('doc.bin', 'doc.bin.bak'))
    res = dict(n=n, kb=kb, secs=round(time.time() - t0, 1), reads_ok=ok, reads_corrupt=bad, reads_missing=miss, write_errors=werr, final_ok=final, leftovers=left)
    print('SOAK OK' if (bad == 0 and miss == 0 and werr == 0 and final and not left) else 'SOAK FAILED', res)
    return 0 if bad == 0 and werr == 0 and final and not left else 1


if __name__ == '__main__':
    sys.exit(main())
