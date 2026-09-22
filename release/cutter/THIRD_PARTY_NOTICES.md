# Third-party notices

Skydive Cutter itself (its code and trained model files) is licensed under the GNU General Public License, version 3;
see [LICENSE](LICENSE). The components below are not part of that licence grant: each keeps its own licence.

The Skydive Cutter download contains only Skydive Cutter's own code, its trained model files, the installer and the
documentation. Everything below is **downloaded by setup (the first run of `Skydive Cutter.cmd`) directly from its
official source onto your PC** and stays under its own licence. Each package's licence file is installed alongside it
in `.runtime\<profile>\Lib\site-packages\<package>.dist-info`; FFmpeg's is copied to `third_party\ffmpeg`.

## Model weights

The video model uses the R3D-18 architecture from torchvision (BSD 3-Clause). Its training started from torchvision's
Kinetics-400 pretrained weights, then it was trained further on the author's own skydiving footage. The temporal,
audio and motion models were trained from scratch on that footage. No third-party footage or labels are included.

## Downloaded by setup

| Component | Source | Licence |
| --- | --- | --- |
| Python 3.12 (embeddable) | python.org | Python Software Foundation License |
| pip | pypi.org | MIT |
| PyTorch 2.7.1, torchvision 0.22.1 | download.pytorch.org | BSD 3-Clause. NVIDIA builds include CUDA runtime libraries under NVIDIA's licence terms. |
| NumPy, SciPy | pypi.org | BSD 3-Clause |
| scikit-learn, joblib, threadpoolctl | pypi.org | BSD 3-Clause |
| librosa, audioread, soxr, lazy_loader, pooch | pypi.org | ISC / MIT / LGPL-2.1+ (soxr) |
| soundfile (includes libsndfile) | pypi.org | BSD 3-Clause (libsndfile: LGPL-2.1) |
| numba, llvmlite | pypi.org | BSD 2-Clause (LLVM: Apache 2.0 with LLVM exception) |
| opencv-python | pypi.org | Apache 2.0 (bundled FFmpeg libraries: LGPL-2.1) |
| PySide6 / Qt 6.9 | pypi.org | LGPL-3.0 |
| Pillow, requests, urllib3, certifi, idna, charset-normalizer, and the other dependencies listed in the `requirements-*.txt` lock files | pypi.org | Their respective permissive licences (see each `.dist-info`) |
| FFmpeg 8.1.2 "essentials" build | gyan.dev | GPL-3.0 (includes GPL components such as x264). Used as a separate program, not linked. |

## Person detection (installed by setup)

| Component | Source | Licence |
| --- | --- | --- |
| Ultralytics YOLO 8.4.67 and its dependencies | pypi.org | **AGPL-3.0** |
| yolo11n.pt weights | github.com/ultralytics/assets | AGPL-3.0 |

The add-on is kept out of the main download for licensing reasons; installing it is your choice.
