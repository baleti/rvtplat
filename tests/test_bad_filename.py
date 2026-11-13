"""bad_filename (merged from the rvt-viewer vendored copy): names Windows would mangle or treat as devices are flagged on every OS."""
from rvtplat import fsio

F = fsio.bad_filename


def test_bad_names():
    for n in ('CON.rvt', 'con.rvt', 'NUL', 'com1.txt.rvt', 'LPT9.rvt', 'a.rvt.', 'a.rvt ', 'a:b.rvt', 'a?.rvt', 'x*.rvt',
              'a\x01.rvt', 'a|b.rvt', 'é' * 130 + '.rvt', '', '..', 'CONIN$.rvt'):
        assert F(n), n


def test_ok_names():
    for n in ('Plan A.rvt', 'Ünï 日本.rvt', 'console.rvt', 'com10.rvt', 'a.b.c.rvt', 'AUXILIARY.rvt', '.hidden.rvt'):
        assert F(n) == '', n


def test_network_fs_kind_never_raises(tmp_path):
    assert isinstance(fsio.network_fs_kind(str(tmp_path)), str)
    fsio.network_fs_kind('/nonexistent/\x00bad')      # must not raise
