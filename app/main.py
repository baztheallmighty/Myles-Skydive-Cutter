"""Run with the repository Python: python -s -B -m app.main [--review]."""
import argparse
import os
import sys
from app import PROJECT_ROOT


def configure_application(application):
    from app.ui import theme
    theme.apply(application)


def main():
    parser = argparse.ArgumentParser(description='Skydive Cutter')
    parser.add_argument('--review', action='store_true', help='open on the Review tab')
    args, _qt = parser.parse_known_args()
    # The same folder the launchers and setup use, where setup switched Ultralytics' usage statistics off.
    os.environ.setdefault('YOLO_CONFIG_DIR', str(PROJECT_ROOT / 'cache' / 'ultralytics'))
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    application = QApplication(sys.argv[:1])
    configure_application(application)
    window = MainWindow(open_review=args.review)
    window.show()
    return application.exec()


if __name__ == '__main__':
    sys.exit(main())
