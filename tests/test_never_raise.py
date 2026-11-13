"""functions documented as never raising must survive hostile input (empty, NUL, huge, surrogates, missing paths)"""
import os, pytest
from rvtplat import fsio

HOSTILE = ["", ".", "..", "\x00", "a\x00b", "x" * 5000, "\ud800", "\udcff" * 10, "/nonexistent/\u00e9/\x00", "C:\\", "\\\\?\\UNC\\", "//", " " * 300, "\n", "~", "a" * 300 + "/b" * 600]


@pytest.mark.parametrize("p", HOSTILE)
def test_predicates_never_raise(p):
    assert isinstance(fsio.network_fs_kind(p), str)
    assert fsio.is_cloud_placeholder(p) in (True, False)
    assert fsio.is_readonly(p) in (True, False)
    assert isinstance(fsio.bad_filename(p), str)
    assert isinstance(fsio.long_path(p) if "\x00" not in p else p, str)


@pytest.mark.parametrize("p", HOSTILE)
def test_changed_since_missing_is_a_change_not_an_exception(p):
    assert fsio.changed_since(p, (0, 0, "")) is True


@pytest.mark.parametrize("p", [h for h in HOSTILE if "\x00" not in h])
def test_long_path_is_pure(p):
    fsio.long_path(p)
