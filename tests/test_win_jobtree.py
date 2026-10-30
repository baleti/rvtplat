"""Windows: killing the parent that launched a capped child must also end the child's own children (Job Object KILL_ON_JOB_CLOSE).
This is what makes 'close the app window' leave no orphan server / worker pool / helper python."""
import os, sys, time, subprocess, textwrap
import pytest
from rvtplat import proc

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Job Objects are Windows only')

PARENT = textwrap.dedent('''
    import sys, subprocess, time
    sys.path.insert(0, %r)
    from rvtplat import proc
    child_code = "import subprocess,sys,time; g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); open(sys.argv[1],'w').write(str(g.pid)); time.sleep(120)"
    c = proc.popen_capped([sys.executable, '-c', child_code, sys.argv[1]], mem_gb=2)
    open(sys.argv[2], 'w').write(str(c.pid))
    time.sleep(120)
''')


def _alive(pid):
    return proc.pid_alive(pid)


def test_killing_parent_ends_child_and_grandchild(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gp, cp = str(tmp_path / 'gpid'), str(tmp_path / 'cpid')
    p = subprocess.Popen([sys.executable, '-c', PARENT % root, gp, cp])
    t0 = time.time()
    while time.time() - t0 < 30 and not (os.path.exists(gp) and os.path.exists(cp) and open(gp).read() and open(cp).read()):
        time.sleep(0.1)
    g, c = int(open(gp).read()), int(open(cp).read())
    assert _alive(c) and _alive(g)
    p.kill()                                    # TerminateProcess: no atexit, no cleanup in the parent
    p.wait(10)
    t0 = time.time()
    while time.time() - t0 < 10 and (_alive(c) or _alive(g)):
        time.sleep(0.1)
    assert not _alive(c), 'child survived its parent'
    assert not _alive(g), 'grandchild survived its parent'


SELF = textwrap.dedent('''
    import sys, subprocess, time
    sys.path.insert(0, %r)
    from rvtplat import proc
    ok = proc.adopt_self_kill_on_close()
    c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])      # plain Popen: no popen_capped
    open(sys.argv[1], 'w').write('%%d %%d' %% (c.pid, int(ok)))
    time.sleep(120)
''')


def test_adopt_self_kills_plain_children(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    f = str(tmp_path / 'pids')
    p = subprocess.Popen([sys.executable, '-c', SELF % root, f])
    t0 = time.time()
    while time.time() - t0 < 30 and not (os.path.exists(f) and open(f).read()):
        time.sleep(0.1)
    c, ok = map(int, open(f).read().split())
    assert ok == 1, 'could not adopt (nested job refused?)'
    assert _alive(c)
    p.kill(); p.wait(10)
    t0 = time.time()
    while time.time() - t0 < 10 and _alive(c):
        time.sleep(0.1)
    assert not _alive(c), 'plain child survived the death of the adopting process'
