# rvtplat changelog (fsio / proc), newest first

## Unreleased (2026-11-13, c3x-crossplat)
Behaviour changes callers must know (all in `fsio`):
- `safe_save(path, data)` now REFUSES a read-only target with `PermissionError` unless `allow_readonly=True` (then the flag/mode is kept). Before it silently overwrote the file and left it writable. Same policy as savegate.
- `safe_save` never creates missing parent folders (`makedirs=False`): a vanished folder (unplugged drive, moved folder) raises instead of being re-created with a stray copy. `atomic_write` / `atomic_write_stream` keep `makedirs=True` (caches).
- `atomic_write*` and `safe_save` follow a symlink and replace the TARGET; before, the link itself was replaced by a regular file and the real file stayed stale.
- `safe_save` writes the `.bak` aside (`.bak.<pid>.<thread>.<rand>.tmp`) and renames it, so a crash mid-copy cannot leave a torn previous-generation backup (measured: 13 of 60 SIGKILLs before). The `.bak` is always writable.
- `replace_retry`: a Windows access-denied (winerror 5) caused by a read-only TARGET raises at once; sharing violations (32/33) still retry (30 tries, jitter, ~12 s).
- `is_readonly` and `changed_since` never raise on NUL / unencodable paths (`changed_since` answers "changed").
- `bad_filename` never raises on lone surrogates; counts Linux escaped bytes as 1 byte; refuses `COM¹²³` / `LPT¹²³`.
Added: `network_fs_kind`, `bad_filename`, macOS dataless check in `is_cloud_placeholder` (merged from the rvt-viewer vendored copy), `full_fsync` (F_FULLFSYNC), `fingerprint` / `changed_since` (sampled hash above 64 MB: caches and hints only, NOT a save guard), `proc.adopt_self_kill_on_close`.
Tests: 96+ (SIGKILL, concurrency, symlink, read-only, ENOSPC, sharing violations, never-raise fuzz, mocked Windows/macOS branches). Real Windows/macOS runs: none yet for the changes above.
Vendored copies on remote-host drift from this package (tools/check_vendor.py --ssh remote-host): rvt-viewer, dwg-viewer and rvt-sheets `_vendor/rvtplat/fsio.py`, and the `replace_retry` / `atomic_write` copies in dwgio.py and rvtio.py. Sync with tools/sync_vendor.sh by the lane owners.
