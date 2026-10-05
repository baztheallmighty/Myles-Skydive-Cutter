"""Motion data from Insta360 .insv files, which keep it in a trailer after the MP4 boxes rather than in a track.

The files here are stand-ins: a little filler where the video would be, then a trailer laid out as the X5 writes it.
"""
import math
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'v4_survey'))

import telemetry_scan as ts  # noqa: E402

FIRST_FRAME = 6_000_000   # microseconds on the camera's clock


def imu(seconds, start=5_000_000, accel=(0, -1024, 0), gyro=(1000, 0, 0)):
    """One sample a millisecond: the camera at rest under 1 g, turning steadily about one axis."""
    words = [v + 32768 for v in (*accel, *gyro)]
    return b''.join(struct.pack('<Q6H', start + i * 1000, *words) for i in range(seconds * 1000))


def insv(tmp_path, records, indexed=True, name='VID_test_00_001.insv'):
    """Filler, then the records. With an index they are padded apart, as on the X5; without, each is followed by
    its own id and length and they can only be found by walking back from the end."""
    body, entries = b'', []
    for kind, data in records:
        entries.append((kind, len(data), len(body)))
        body += data + (b'\0' * 64 if indexed else struct.pack('<HI', kind, len(data)))
    if indexed:
        index = b'\0' * 10 + b''.join(struct.pack('<BBII', kind >> 8, kind & 255, length, offset)
                                      for kind, length, offset in entries)
        body += index + struct.pack('<HI', 0, len(index))
    trailer_length = len(body) + 72
    path = tmp_path / name
    path.write_bytes(b'\0' * 4096 + body + b'\0' * 32 + struct.pack('<II', trailer_length, 3) + ts.INSTA360_MAGIC)
    return path


def frames(first=FIRST_FRAME, count=30):
    return b''.join(struct.pack('<Qd', first + i * 33_367, 0.004) for i in range(count))


@pytest.mark.parametrize('indexed', [True, False])
def test_motion_is_read_on_the_videos_clock(tmp_path, indexed):
    path = insv(tmp_path, [(0x101, b'Insta360 X5'), (0x300, imu(40)), (0x400, frames())], indexed)
    row, seconds = ts.scan(tmp_path, path.name)
    assert row['status'] == 'ok' and row['metadata_tracks'] == 'insta360'
    assert row['accel_hz'] == pytest.approx(ts.INSTA360_RATE_HZ, rel=0.01)
    # Recording started a second before the first frame; that second is not part of the video.
    assert [s['t_sec'] for s in seconds] == list(range(39))
    assert all(s['accel_mean'] == pytest.approx(ts.STANDARD_GRAVITY, abs=0.01) for s in seconds)
    assert all(s['accel_std'] == 0 for s in seconds)
    assert seconds[10]['gyro_mean'] == pytest.approx(math.radians(2000 / 32768 * 1000), abs=0.001)


def test_vectors_keep_their_axes(tmp_path):
    path = insv(tmp_path, [(0x300, imu(2, start=FIRST_FRAME)), (0x400, frames())])
    with path.open('rb') as handle:
        accel, gyro = ts.insta360_motion(handle, path.stat().st_size)
    t, vector = accel[0]
    assert 0 <= t < 0.01
    assert vector == pytest.approx((0, -ts.STANDARD_GRAVITY, 0))
    assert gyro[0][1][1:] == (0, 0) and gyro[0][1][0] > 1


def test_without_frame_times_the_first_sample_is_zero(tmp_path):
    path = insv(tmp_path, [(0x300, imu(35))])
    _, seconds = ts.scan(tmp_path, path.name)
    assert [s['t_sec'] for s in seconds] == list(range(35))


def test_an_unknown_sample_layout_is_no_motion_not_an_error(tmp_path):
    older = b''.join(struct.pack('<Q6d', i, 0, -1, 0, 0, 0, 0) for i in range(1001))   # 56-byte samples
    path = insv(tmp_path, [(0x300, older)])
    row, seconds = ts.scan(tmp_path, path.name)
    assert row['status'] == 'ok' and row['metadata_tracks'] == '' and seconds == []


def test_a_file_without_the_trailer_is_no_motion(tmp_path):
    path = tmp_path / 'plain.insv'
    path.write_bytes(b'\0' * 5000)
    row, seconds = ts.scan(tmp_path, path.name)
    assert row['status'] == 'ok' and row['metadata_tracks'] == '' and seconds == []
