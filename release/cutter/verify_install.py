"""Check a fresh install with generated input only: files intact, every model loads and runs, the UI builds, ffmpeg runs.

Called by Setup.ps1 and setup.sh at the end of setup. Safe to run again at any time:
    .runtime\\<profile>\\python.exe -s -B verify_install.py --device cpu|cuda
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from app.system import tool_name

ROOT = Path(__file__).resolve().parent
os.environ.setdefault('NUMBA_CACHE_DIR', str(ROOT / 'cache' / 'numba'))
os.environ.setdefault('TORCH_HOME', str(ROOT / 'cache' / 'torch'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'v3_poc'))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(8 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', choices=['cpu', 'cuda', 'mps'], required=True)
    args = parser.parse_args()
    started = time.monotonic()
    import numpy as np
    import torch

    from cutter_v4 import ENGINE_REVISION, MODELS_DIR
    from cutter_v4.engine import Models, canonical, monotonic
    from cutter_v4.motion import PHASES, load_classifier
    from _audio_features import clip_features

    device = torch.device(args.device)
    if args.device == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('The NVIDIA runtime cannot use your GPU. Update the NVIDIA driver, or run Repair.cmd -Mode CPU from a Command Prompt in this folder.')
    if args.device == 'mps' and not (getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available()):
        raise RuntimeError('The Apple GPU is unavailable. Run setup.sh --cpu to use the processor.')
    package = ROOT / 'PACKAGE_FILES.json'
    if package.exists():
        for name, expected in json.loads(package.read_text(encoding='utf-8'))['sha256'].items():
            assert sha256(ROOT / name) == expected, f'Package file changed or damaged: {name}. Download the package again.'
    manifest = json.loads((MODELS_DIR / 'MODELS.json').read_text(encoding='utf-8'))
    for entry in manifest['models'].values():
        assert sha256(MODELS_DIR / entry['file']) == entry['sha256'], f'Model file damaged: {entry["file"]}'

    models = Models(device)
    with torch.inference_mode():
        clip = torch.zeros((2, 3, 24, 160, 160), device=device)
        embedding = models.trunk(clip)
        assert embedding.shape == (2, 512)
        window_logits = models.head(embedding)
        assert window_logits.shape == (2, len(models.class_names))
        temporal = models.temporal(torch.randn(40, 512))
        assert temporal.shape == (40, len(models.class_names)) and torch.isfinite(temporal).all()
        path = monotonic(canonical(temporal, models.class_names))
        assert len(path) == 40 and path == sorted(path)
        signal = (.1 * np.sin(2 * np.pi * 700 * np.arange(3 * 22050) / 22050)).astype(np.float32)
        features = clip_features(signal)
        assert features.shape == (73,) and np.isfinite(features).all()
        audio = models.audio(torch.from_numpy(np.stack([features] * 3)).to(device))
        assert audio.shape == (3, len(models.audio_classes)) and torch.isfinite(audio).all()
    classifier = load_classifier()
    assert classifier is not None, 'Motion model missing.'
    probabilities = classifier.predict_proba(np.zeros((2, 17 * 4 + 3)) + 9.8)
    assert probabilities.shape[0] == 2 and len(classifier.classes_) <= len(PHASES)

    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401 - the labeller's video player
    application = QApplication([])
    from app.ui.main_window import MainWindow
    window = MainWindow()
    assert window.review_labels_button.text() == 'Review cuts in labeller'
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ['Process', 'Review']
    assert set(window.sections) == {'output', 'processing', 'people'}, 'Advanced sections missing.'
    from app.health import blocking, check_install, people_installed
    from app.settings import Settings
    assert people_installed(Settings()), 'Person detection is missing from this install.'
    stoppers = blocking(check_install(Settings(), cuda_available=args.device != 'cpu'))
    assert not stoppers, 'Install check: ' + '; '.join(f'{c.label}: {c.detail}' for c in stoppers)
    window.close()
    application.quit()

    hidden = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    ffmpeg = subprocess.run([str(ROOT / 'bin' / tool_name('ffmpeg')), '-version'], capture_output=True, text=True,
                            check=True, creationflags=hidden).stdout.splitlines()[0]
    subprocess.run([str(ROOT / 'bin' / tool_name('ffprobe')), '-version'], capture_output=True, check=True,
                   creationflags=hidden)
    report = {'passed': True, 'engine_revision': ENGINE_REVISION, 'device': str(device), 'python': sys.version,
              'ffmpeg': ffmpeg, 'gpu': torch.cuda.get_device_name(0) if args.device == 'cuda' else
              ('Apple GPU' if args.device == 'mps' else None),
              'seconds': round(time.monotonic() - started, 1),
              'versions': {name: importlib.metadata.version(name) for name in
                           ['torch', 'torchvision', 'numpy', 'librosa', 'scikit-learn', 'PySide6', 'opencv-python']},
              'checks': ['package and model checksums', 'video network forward', 'temporal head and ordered decoding',
                         '73 audio features and audio model', 'motion model', 'main window with Process and Review tabs builds',
                         'FFmpeg and FFprobe']}
    (ROOT / 'logs').mkdir(exist_ok=True)
    (ROOT / 'logs' / f'verified-{args.device}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
