#!/usr/bin/env python3
"""Compare the vendored copies of rvtplat with this package (exact file hashes) and the partial copies dwgio.py / rvtio.py
(function source of replace_retry and atomic_write must match). usage: check_vendor.py [--ssh HOST]  -> exit 1 on drift.
Vendored locations (remote-host): ~/src/rvt-viewer/rvtballet/_vendor, ~/dwg-viewer/dwgballet/_vendor, ~/src/rvt-sheets/rvtsheets/_vendor."""
import os, sys, hashlib, subprocess, ast

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(HERE, 'rvtplat')
VENDORED = ['~/src/rvt-viewer/rvtballet/_vendor/rvtplat', '~/dwg-viewer/dwgballet/_vendor/rvtplat', '~/src/rvt-sheets/rvtsheets/_vendor/rvtplat']
PARTIAL = ['~/dwg-research/dwgio.py', '~/rvt-research/rvtio.py']
FUNCS = ('replace_retry', 'atomic_write', 'long_path', 'full_fsync')


def sha(b): return hashlib.sha1(b).hexdigest()


def func_src(text, name):
    for n in ast.parse(text).body:
        if isinstance(n, ast.FunctionDef) and n.name == name: return ast.get_source_segment(text, n)
    return None


def read(path, host):
    if host:
        r = subprocess.run(['ssh', host, 'cat ' + path], capture_output=True)
        return r.stdout if r.returncode == 0 else None
    p = os.path.expanduser(path)
    return open(p, 'rb').read() if os.path.exists(p) else None


def main():
    host = sys.argv[sys.argv.index('--ssh') + 1] if '--ssh' in sys.argv else None
    bad = 0
    ref = {f: open(os.path.join(PKG, f), 'rb').read() for f in sorted(os.listdir(PKG)) if f.endswith('.py')}
    for v in VENDORED:
        for f, b in ref.items():
            got = read(v + '/' + f, host)
            if got is None: print('MISSING', v, f); bad += 1
            elif sha(got) != sha(b): print('DRIFT  ', v, f); bad += 1
    fs = ref['fsio.py'].decode('utf8')
    for p in PARTIAL:
        got = read(p, None)                                # these two live on this host (dwg-research / rvt-research)
        if got is None: print('MISSING', p); bad += 1; continue
        t = got.decode('utf8')
        for fn in FUNCS:
            a, b = func_src(fs, fn), func_src(t, fn)
            if b is None: continue                       # the partial copy does not carry this function
            if a != b: print('DRIFT  ', p, fn); bad += 1
    print('vendor check:', 'OK' if not bad else '%d problem(s)' % bad)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
