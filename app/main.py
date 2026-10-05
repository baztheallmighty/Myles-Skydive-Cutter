"""Run with the repository Python: python -s -B -m app.main [--review]."""
import argparse
import os
import sys
from app import PROJECT_ROOT


RUNNING_MARK = 'SkydiveCutterRunning'   # the installer and the uninstaller look for this before touching the files
ICON = 'skydive-cutter.ico'


def mark_running():
    """Hold a named Windows mutex for as long as the app is open. Returns the handle, which must be kept alive.

    The installer names the same mutex, so upgrading or uninstalling while the app is open asks for it to be closed
    first instead of replacing files under it.
    """
    if os.name != 'nt':
        return None
    import ctypes
    return ctypes.windll.kernel32.CreateMutexW(None, False, RUNNING_MARK)


def app_icon():
    """The icon file: at the top of an installed package, under release/cutter in a development checkout."""
    for folder in (PROJECT_ROOT, PROJECT_ROOT / 'release' / 'cutter'):
        if (folder / ICON).is_file():
            return folder / ICON
    return None


def configure_application(application):
    from app.ui import theme
    theme.apply(application)
    icon = app_icon()
    if icon is not None:
        from PySide6.QtGui import QIcon
        application.setWindowIcon(QIcon(str(icon)))


def main():
    parser = argparse.ArgumentParser(description='Skydive Cutter')
    parser.add_argument('--review', action='store_true', help='open on the Review tab')
    args, _qt = parser.parse_known_args()
    # The same folder the launchers and setup use, where setup switched Ultralytics' usage statistics off.
    os.environ.setdefault('YOLO_CONFIG_DIR', str(PROJECT_ROOT / 'cache' / 'ultralytics'))
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    running = mark_running()   # noqa: F841 - held until the process ends
    application = QApplication(sys.argv[:1])
    configure_application(application)
    window = MainWindow(open_review=args.review)
    window.show()
    return application.exec()


if __name__ == '__main__':
    sys.exit(main())
