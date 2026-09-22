"""Skydive Cutter V4 engine: jump-phase classification from video, audio and camera motion."""
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent
MODELS_DIR = PACKAGE_DIR / 'models'
ENGINE_REVISION = 'v4-t2-nosnap-audiofreefall30-1'
