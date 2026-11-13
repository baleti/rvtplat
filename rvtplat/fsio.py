"""Safe file writes that behave the same on Windows, macOS and Linux.

Windows specifics handled here:
  * os.replace fails with PermissionError/OSError(WinError 5/32/33) while another process (antivirus,
    indexer, backup, a second viewer) holds the destination open: retry with exponential backoff.
  * read-only attribute on the destination (os.replace refuses): cleared when `clear_readonly`.
  * long paths (>259 chars): extended-length prefix via long_path().
  * unicode paths: all functions take str; no ANSI APIs.
  * OneDrive/Dropbox placeholders: the destination is replaced, never opened for in-place update.
Data is flushed and fsync'ed before the rename, and the directory is fsync'ed on POSIX, so a crash or
power loss leaves either the old or the new file, never a torn one."""
import os, sys, random, time, stat, tempfile, errno, threading

_WIN = sys.platform == 'win32'
# Windows sharing/permission errors that mean "somebody else has it open right now"
_WIN_BUSY = {5, 32, 33, 1224}


def long_path(p):
    """extended-length form on Windows for paths that would exceed MAX_PATH; identity elsewhere"""
    if not _WIN:
        return p
    p = os.path.abspath(p)
    if p.startswith('\\\\?\\'):
        return p
    if p.startswith('\\\\'):
        return '\\\\?\\UNC\\' + p[2:]
    return '\\\\?\\' + p if len(p) >= 248 else p


def _busy(e):
    if isinstance(e, PermissionError):
        return True
    w = getattr(e, 'winerror', None)
    return (w in _WIN_BUSY) or (e.errno in (errno.EACCES, errno.EBUSY, errno.EPERM) and _WIN)


def _dst_readonly_attr(p):
    try:
        return not (os.stat(p).st_mode & stat.S_IWRITE)
    except OSError:
        return False


def replace_retry(src, dst, tries=30, delay=0.02, max_delay=0.5, clear_readonly=False, _sleep=time.sleep):
    """os.replace with jittered backoff on Windows-style sharing violations (about 12 s total at the defaults; 12 tries / 3 s was exhausted by 8 concurrent writers on a slow Windows VM)"""
    src, dst = long_path(src), long_path(dst)
    d = delay
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            if not _busy(e) or i == tries - 1:
                raise
            if _WIN and not clear_readonly and getattr(e, 'winerror', None) == 5 and _dst_readonly_attr(dst):
                raise      # access denied because the TARGET is read-only: waiting cannot help (a sharing violation is 32/33, retried)
            if clear_readonly:
                try:
                    os.chmod(dst, os.stat(dst).st_mode | stat.S_IWRITE)
                except OSError:
                    pass
            _sleep(d * (0.5 + random.random()))
            d = min(d * 2, max_delay)


def full_fsync(fd):
    """fsync that really reaches the disk: on macOS os.fsync only hands the data to the drive, whose cache can still lose it on power
    failure; F_FULLFSYNC asks the drive to flush. Falls back to os.fsync where it is unavailable (network file systems refuse it)."""
    if sys.platform == 'darwin':
        try:
            import fcntl
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
            return
        except (ImportError, AttributeError, OSError):
            pass
    os.fsync(fd)


def _fsync_dir(path):
    if _WIN:
        return
    try:
        fd = os.open(path or '.', os.O_RDONLY)
        try:
            full_fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _follow_link(path):
    """a symlinked document is saved THROUGH the link: os.replace on the link itself would swap the link for a regular file and leave the real file stale"""
    try:
        if os.path.islink(path):
            return os.path.realpath(path)
    except OSError:
        pass
    return path


def atomic_write(path, data, mode=None, encoding='utf-8', newline=None, clear_readonly=False, fsync=True, makedirs=True):
    """Write `data` (bytes, or str encoded with `encoding`) to `path` atomically; returns path.
    The temporary file lives in the destination directory (same volume, so the rename is atomic).
    str is written with newline translation disabled unless `newline` is given."""
    path = _follow_link(os.fspath(path))
    d = os.path.dirname(os.path.abspath(path))
    if makedirs:
        os.makedirs(long_path(d), exist_ok=True)
    if isinstance(data, str):
        data = data.encode(encoding)
        if newline not in (None, '', '\n'):
            data = data.replace(b'\n', newline.encode(encoding))
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path)[:40] + '.', suffix='.tmp', dir=long_path(d))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            if fsync:
                full_fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        elif os.path.exists(long_path(path)):
            try:
                os.chmod(tmp, stat.S_IMODE(os.stat(long_path(path)).st_mode) | stat.S_IWRITE)
            except OSError:
                pass
        replace_retry(tmp, path, clear_readonly=clear_readonly)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    if fsync:
        _fsync_dir(d)
    return path


def atomic_write_with(path, writer, **kw):
    """writer(fileobj) fills a binary temp file (for pickle.dump / large streams); then the same replace"""
    import io
    buf = io.BytesIO()
    writer(buf)
    return atomic_write(path, buf.getvalue(), **kw)


def atomic_write_stream(path, writer, clear_readonly=False, fsync=True, makedirs=True):
    """like atomic_write_with but streams straight to the temp file (no copy in RAM, for big caches)"""
    path = _follow_link(os.fspath(path))
    d = os.path.dirname(os.path.abspath(path))
    if makedirs:
        os.makedirs(long_path(d), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path)[:40] + '.', suffix='.tmp', dir=long_path(d))
    try:
        with os.fdopen(fd, 'wb') as f:
            writer(f)
            f.flush()
            if fsync:
                full_fsync(f.fileno())
        replace_retry(tmp, path, clear_readonly=clear_readonly)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    if fsync:
        _fsync_dir(d)
    return path


def safe_save(path, data, keep_backup=True, allow_readonly=False, **kw):
    """overwrite a USER document (.rvt/.dwg): atomic_write, plus a one-generation `.bak` copy of the old
    file next to it (copy, not rename, so the original is never absent). Backup failures never block the save."""
    import shutil
    path = _follow_link(os.fspath(path))
    ro_mode = None
    if os.path.exists(long_path(path)) and is_readonly(path):
        if not allow_readonly:        # same policy as savegate: a file the user marked read-only is not silently overwritten (and made writable)
            raise PermissionError(errno.EACCES, 'target is read-only: clear the flag, save elsewhere, or pass allow_readonly=True', path)
        ro_mode = stat.S_IMODE(os.stat(long_path(path)).st_mode)      # overwritten on request, flag kept
    if keep_backup and os.path.isfile(long_path(path)):
        bt = path + '.bak.%d.%x.%s.tmp' % (os.getpid(), threading.get_ident(), os.urandom(3).hex())      # copy aside then rename: a crash mid-copy must not leave a torn .bak (the previous generation)
        try:
            shutil.copy2(long_path(path), long_path(bt))
            os.chmod(long_path(bt), os.stat(long_path(bt)).st_mode | stat.S_IWRITE)      # copy2 keeps a read-only flag; a read-only .bak could not be replaced on Windows
            replace_retry(bt, path + '.bak')
        except OSError:
            try:
                os.remove(long_path(bt))
            except OSError:
                pass
    if ro_mode is not None:
        kw.setdefault('mode', ro_mode)
    kw.setdefault('makedirs', False)      # a USER document's folder that vanished (unplugged drive, moved folder) must fail, not be re-created with a stray copy
    return atomic_write(path, data, clear_readonly=allow_readonly, **kw)


def read_retry(path, mode='rb', tries=8, delay=0.02, **kw):
    """open+read whole file, retrying while a scanner/indexer holds an exclusive lock (Windows)"""
    d = delay
    for i in range(tries):
        try:
            with open(long_path(path), mode, **kw) as f:
                return f.read()
        except OSError as e:
            if not _busy(e) or i == tries - 1:
                raise
            time.sleep(d)
            d = min(d * 2, 0.5)


def is_cloud_placeholder(path):
    """True for a OneDrive/Dropbox 'online-only' file whose content is not on disk yet (Windows reparse /
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS 0x400000, OFFLINE 0x1000). Reading it triggers a download."""
    if sys.platform == 'darwin':          # iCloud Drive / File Provider 'Optimise storage': an evicted file has SF_DATALESS (0x40000000) set; reading it downloads it
        try: return bool(os.stat(path).st_flags & 0x40000000)
        except (OSError, AttributeError): return False
    if not _WIN:
        return False
    try:
        a = os.stat(long_path(path)).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(a & (0x400000 | 0x1000 | 0x40000))


def is_readonly(path):
    try:
        return not os.access(long_path(path), os.W_OK)
    except OSError:
        return False


def fingerprint(path, hash_limit=64 << 20):
    """(size, mtime_ns, sha1) of a file. mtime alone is not enough: FAT/exFAT keeps 2 s, SMB and some
    sync tools round, and an external edit within the same tick keeps the same mtime. The hash decides
    whenever size and mtime agree (files above hash_limit hash only head+tail 1 MiB + size); above that limit a same-size edit in the middle of the file with an unchanged mtime goes unseen, so use this for caches and change hints only: a save guard for a user document must hash the whole file, as savegate.guard does)."""
    import hashlib
    p = long_path(path)
    st = os.stat(p)
    h = hashlib.sha1()
    with open(p, 'rb') as f:
        if st.st_size <= hash_limit:
            for blk in iter(lambda: f.read(1 << 20), b''):
                h.update(blk)
        else:
            h.update(f.read(1 << 20))
            f.seek(-(1 << 20), 2)
            h.update(f.read(1 << 20))
    return (st.st_size, st.st_mtime_ns, h.hexdigest())


def changed_since(path, fp):
    """True when the file differs from fingerprint `fp` (taken earlier). Size or content hash differing
    is a change even if mtime is equal (coarse timestamps); mtime differing alone is NOT a change when the
    content hash is equal (touch, copy, sync tool rewrote the stamp)."""
    try:
        now = fingerprint(path)
    except OSError:
        return True
    return now[0] != fp[0] or now[2] != fp[2]


def network_fs_kind(path):
    """'' for a local file system; a short label when the path is on a network share (Windows: UNC or a drive whose type is
    DRIVE_REMOTE; macOS: smbfs/nfs/afpfs/webdav/fuse mounts from `mount`; Linux: /proc/self/mountinfo). Never raises."""
    try:
        rp = os.path.abspath(path)
        if _WIN:
            if rp.startswith('\\\\') and not rp.startswith('\\\\?\\'):
                return 'unc'
            if rp.startswith('\\\\?\\UNC\\'):
                return 'unc'
            import ctypes
            drv = os.path.splitdrive(rp.replace('\\\\?\\', ''))[0]
            if len(drv) == 2 and drv[1] == ':':
                t = ctypes.windll.kernel32.GetDriveTypeW(drv + '\\')
                return 'remote-drive' if t == 4 else ''
            return ''
        rp = os.path.realpath(path)
        net = ('nfs', 'nfs4', 'cifs', 'smb3', 'smbfs', '9p', 'davfs', 'afs', 'afpfs', 'webdav', 'ncpfs', 'ceph', 'glusterfs', 'lustre')
        best = ('', '')
        if sys.platform == 'darwin':
            import subprocess, re
            out = subprocess.run(['/sbin/mount'], capture_output=True, text=True, timeout=5).stdout
            for ln in out.splitlines():
                m = re.match(r'.* on (.+) \(([^,)]+)', ln)
                if m and (rp == m.group(1) or rp.startswith(m.group(1).rstrip('/') + '/')) and len(m.group(1)) >= len(best[0]):
                    best = (m.group(1), m.group(2))
        else:
            for ln in open('/proc/self/mountinfo'):
                f = ln.split(' ')
                i = f.index('-')
                mp = f[4].replace('\\040', ' ')
                if (rp == mp or rp.startswith(mp.rstrip('/') + '/')) and len(mp) >= len(best[0]):
                    best = (mp, f[i + 1])
        ty = best[1]
        return ty if ty.startswith('fuse') or ty in net or ty in ('osxfuse', 'macfuse') else ''
    except Exception:
        return ''


_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {'COM%d' % i for i in range(1, 10)} | {'LPT%d' % i for i in range(1, 10)} | {p + c for p in ('COM', 'LPT') for c in '\u00b9\u00b2\u00b3'}


def bad_filename(name):
    """'' when `name` (a single path component) is safe on Windows, macOS and Linux; else the reason. Applied on every OS so a
    file saved on Linux can be opened on Windows: device names (CON.dwg opens the console), trailing dot/space (silently
    stripped, so a different file is written), characters Windows forbids, control characters, over-long names."""
    if not name or name in ('.', '..'):
        return 'empty file name'
    if any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name):
        return 'the file name contains a character that is not allowed on Windows (< > : " / \\ | ? * or a control character)'
    if name[-1] in '. ':
        return 'the file name may not end with a dot or a space (Windows would drop it and write a different file)'
    if name.split('.')[0].rstrip(' ').upper() in _RESERVED:
        return 'the file name is a reserved Windows device name (%s)' % name.split('.')[0].upper()
    try:
        nbytes = len(name.encode('utf-8', 'surrogateescape'))      # non-UTF-8 bytes of a Linux name arrive as U+DC80..DCFF: 1 byte each
    except UnicodeEncodeError:
        nbytes = len(name.encode('utf-8', 'surrogatepass'))        # an unpaired UTF-16 unit (NTFS allows them): counted, never raises
    if nbytes > 255:
        return 'the file name is longer than 255 bytes'
    return ''
