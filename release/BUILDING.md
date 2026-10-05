# Building a release

Everything published is built by two scripts from the same list of files (`FILES` in `build_cutter_package.py`), so
the ZIP and the installer always carry the same thing.

## Each release

1. Set `VERSION` in `release/build_cutter_package.py`, add the section to `release/cutter/CHANGELOG.md`, and update
   the file names in `release/cutter/README.md`.
2. Run the tests: `Run-Tests.cmd`.
3. Build the ZIP:

   ```bat
   python release\build_cutter_package.py
   ```

4. Build the installer:

   ```bat
   python release\build_installer.py
   ```

   The first time on a PC, add `--fetch-tools` (see below).
5. Test the installer (next section).

Both land in `release\dist`, each with a `.sha256` beside it:

- `Skydive-Cutter-<version>-windows.zip`
- `Skydive-Cutter-<version>-Setup.exe`

Both builds stop, and publish nothing, if a private string is found in any packaged file or if any child process
could open a console window.

## The installer's compiler

The installer is made with [Inno Setup](https://jrsoftware.org/isinfo.php) (free, open source).
`python release\build_installer.py --fetch-tools` downloads the version pinned by checksum in
`release/build-tools.json` and unpacks it into `build\tools\innosetup` in portable mode: nothing is installed on the
PC. An Inno Setup you installed yourself is used too; set the `ISCC` environment variable to `ISCC.exe` to choose
one. To move to a newer Inno Setup, change the version, address and checksum in `build-tools.json`.

The installer script is written to `build\installer\skydive-cutter.iss` on every build. It is generated: change
`build_installer.py`, not the `.iss`.

## Testing the installer

```bat
python release\build_installer.py --test-build
powershell -NoProfile -ExecutionPolicy Bypass -File release\tests\installer_test.ps1
```

The test build installs under its own name ("Skydive Cutter (test build)") and identifier, so it never touches a
real install on the same PC. The test installs it silently into a temporary folder, checks every file against
`PACKAGE_FILES.json`, the Start-menu shortcut and the entry under installed apps, then uninstalls it and checks that
only the settings are left. It takes under a minute because it skips the downloads.

Add `-Full` to run the package's setup as well (2 to 5 GB of downloads) and confirm the launcher then finds
everything in place.

Useful switches on the installer itself: `/VERYSILENT /SUPPRESSMSGBOXES` (no questions), `/DIR="..."` (where),
`/NORUNTIME=1` (copy the files but leave the downloads for the first start), `/LOG="file"`.

## Things that must not change

- `APP_ID` in `build_installer.py`. Windows recognises an upgrade by it; change it and the next version installs as
  a second copy.
- `RUNNING_MARK`, the same in `build_installer.py` and `app/main.py`. It is how the installer knows the app is open.

## The icon

`release/cutter/skydive-cutter.ico` is drawn by `python release\make_icon.py`. Run that only to change the picture.

## Code signing

The installer is not signed, so Windows SmartScreen warns that the publisher is unknown. Signing needs a paid
certificate; if the project ever has one, sign `Setup.exe` after the build and before writing the checksum.
