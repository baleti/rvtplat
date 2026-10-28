import os, sys, subprocess
from rvtplat import proc


def test_pid_alive_self_and_child():
    assert proc.pid_alive(os.getpid())
    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        assert proc.pid_alive(p.pid)
    finally:
        p.kill(); p.wait()
    assert not proc.pid_alive(p.pid)
    assert not proc.pid_alive(0)
