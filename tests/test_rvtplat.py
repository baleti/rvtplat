import os, sys, stat, threading, time, subprocess, pickle
import pytest
from rvtplat import dirs, fsio, mem, browser, proc


def test_dirs_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv('RVTPLAT_CACHE', str(tmp_path))
    assert dirs.cache_dir('rvt-viewer') == str(tmp_path / 'rvt-viewer')
    monkeypatch.setenv('RVTPLAT_RVT_VIEWER_CACHE', str(tmp_path / 'x'))
    assert dirs.cache_dir('rvt-viewer', make=True) == str(tmp_path / 'x') and (tmp_path / 'x').is_dir()


def test_dirs_defaults_absolute():
    for f in (dirs.cache_dir, dirs.config_dir, dirs.data_dir):
        assert os.path.isabs(f('app'))


def test_atomic_write_bytes_and_str(tmp_path):
    p = tmp_path / 'sub' / 'a.txt'
    fsio.atomic_write(p, 'héllo 日本\n')
    assert p.read_bytes() == 'héllo 日本\n'.encode('utf-8')
    fsio.atomic_write(p, b'\x00\x01')
    assert p.read_bytes() == b'\x00\x01'
    assert [x.name for x in p.parent.iterdir()] == ['a.txt']          # no temp leftovers


def test_atomic_write_newline(tmp_path):
    p = tmp_path / 'a.txt'
    fsio.atomic_write(p, 'a\nb\n', newline='\r\n')
    assert p.read_bytes() == b'a\r\nb\r\n'


def test_unicode_and_long_path(tmp_path):
    d = tmp_path
    for i in range(6):
        d = d / ('där_%d_' % i + 'x' * 40)
    p = d / 'münchen.rvt'
    fsio.atomic_write(p, b'abc')
    assert fsio.read_retry(str(p)) == b'abc'


def test_readonly_destination(tmp_path):
    p = tmp_path / 'ro.bin'
    p.write_bytes(b'old')
    os.chmod(p, stat.S_IREAD)
    try:
        fsio.atomic_write(p, b'new', clear_readonly=True)
        assert p.read_bytes() == b'new'
    finally:
        try: os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
        except OSError: pass


def test_replace_retries_on_busy(tmp_path, monkeypatch):
    src, dst = tmp_path / 's', tmp_path / 'd'
    src.write_bytes(b'1')
    calls = []
    real = os.replace

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 4:
            raise PermissionError(13, 'sharing violation')
        return real(a, b)
    monkeypatch.setattr(os, 'replace', flaky)
    fsio.replace_retry(str(src), str(dst), _sleep=lambda s: None)
    assert len(calls) == 4 and dst.read_bytes() == b'1'


def test_replace_gives_up(tmp_path, monkeypatch):
    src = tmp_path / 's'; src.write_bytes(b'1')
    monkeypatch.setattr(os, 'replace', lambda a, b: (_ for _ in ()).throw(PermissionError(13, 'x')))
    with pytest.raises(PermissionError):
        fsio.replace_retry(str(src), str(tmp_path / 'd'), tries=3, _sleep=lambda s: None)


def test_failed_write_keeps_old_and_cleans(tmp_path):
    p = tmp_path / 'f'
    fsio.atomic_write(p, b'old')

    def boom(f):
        f.write(b'partial'); raise RuntimeError('x')
    with pytest.raises(RuntimeError):
        fsio.atomic_write_stream(p, boom)
    assert p.read_bytes() == b'old' and len(list(tmp_path.iterdir())) == 1


def test_pickle_stream(tmp_path):
    p = tmp_path / 'c.pkl'
    fsio.atomic_write_stream(p, lambda f: pickle.dump({'a': [1, 2]}, f, protocol=5))
    assert pickle.loads(p.read_bytes()) == {'a': [1, 2]}


def test_safe_save_backup(tmp_path):
    p = tmp_path / 'm.rvt'
    fsio.atomic_write(p, b'v1')
    fsio.safe_save(p, b'v2')
    assert p.read_bytes() == b'v2' and (tmp_path / 'm.rvt.bak').read_bytes() == b'v1'


def test_concurrent_writers_never_torn(tmp_path):
    p = tmp_path / 'c'
    payloads = [bytes([i]) * 50000 for i in range(4)]
    stop = []
    bad = []

    def w(b):
        for _ in range(40):
            fsio.atomic_write(p, b, fsync=False)

    def r():
        while not stop:
            try:
                d = fsio.read_retry(str(p))
            except FileNotFoundError:
                continue
            if d not in payloads:
                bad.append(len(d))
    fsio.atomic_write(p, payloads[0])
    rt = threading.Thread(target=r); rt.start()
    ts = [threading.Thread(target=w, args=(b,)) for b in payloads]
    [t.start() for t in ts]; [t.join() for t in ts]; stop.append(1); rt.join()
    assert not bad


def test_placeholder_false_for_plain(tmp_path):
    p = tmp_path / 'a'; p.write_bytes(b'1')
    assert fsio.is_cloud_placeholder(str(p)) is False


def test_mem():
    assert mem.rss_bytes() > 1_000_000
    assert mem.total_ram_bytes() > 100_000_000
    assert mem.limit_gb() > 0


def test_mem_env(monkeypatch):
    monkeypatch.setenv('RVTPLAT_MEM_GB', '1.5')
    assert mem.limit_gb() == 1.5


def test_browser_env(monkeypatch):
    monkeypatch.setenv('RVT_BROWSER', sys.executable)
    assert browser.find() == sys.executable
    c = browser.app_command('http://127.0.0.1:1/', profile_dir='p')
    assert c[0] == sys.executable and '--app=http://127.0.0.1:1/' in c and '--user-data-dir=p' in c


def test_run_capped_roundtrip():
    r = proc.run_capped([sys.executable, '-c', 'print(40+2)'], mem_gb=2, capture_output=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == b'42'


def test_timeout_helper():
    assert proc.call_with_timeout(lambda x: x + 1, 2, 1) == 2
    with pytest.raises(TimeoutError):
        proc.call_with_timeout(time.sleep, 0.2, 5)


def test_paths_env_and_siblings(tmp_path, monkeypatch):
    from rvtplat import paths
    rd = tmp_path / 'rd'; rd.mkdir(); (rd / 'rvt_geometry.py').write_text('')
    monkeypatch.setenv('RVT_READER_DIR', str(rd))
    assert paths.reader_dir() == str(rd)
    monkeypatch.delenv('RVT_READER_DIR')
    (tmp_path / 'rvt-research').mkdir(); (tmp_path / 'rvt-research' / 'rvt_geometry.py').write_text('')
    (tmp_path / 'app').mkdir()
    assert paths.reader_dir(str(tmp_path / 'app')) == str(tmp_path / 'rvt-research')
    s = tmp_path / 'rvt-sheets' / 'rvtsheets'; s.mkdir(parents=True); (s / '__init__.py').write_text('')
    monkeypatch.delenv('RVTSHEETS', raising=False)
    assert paths.sheets_dir(str(tmp_path / 'app')) == str(tmp_path / 'rvt-sheets')


def test_python_exe(monkeypatch):
    from rvtplat import paths
    monkeypatch.delenv('RVT_SHEETS_PY', raising=False)
    assert paths.python_exe() == sys.executable
    assert paths.add_to_path('/nonexistent-dir-xyz') == []


def test_fonts_find_or_none(tmp_path, monkeypatch):
    from rvtplat import fonts
    d = tmp_path / 'f'; d.mkdir(); (d / 'arial.ttf').write_bytes(b'x'); (d / 'arialbd.ttf').write_bytes(b'x')
    monkeypatch.setenv('RVT_FONT_DIRS', str(d))
    monkeypatch.setattr(fonts, '_fc', lambda n, b: None)
    fonts._INDEX.clear()
    assert fonts.find('Arial')[0] == str(d / 'arial.ttf')
    assert fonts.find('Arial', True)[0] == str(d / 'arialbd.ttf')
    assert fonts.find('Nonexistent Font Zzz', False) is None or fonts.find('Nonexistent Font Zzz')[1] != 'Nonexistent Font Zzz'
    fonts._INDEX.clear()
