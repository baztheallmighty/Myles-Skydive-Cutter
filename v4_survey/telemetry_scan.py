"""Read-only telemetry scan: which videos carry motion or GPS metadata, and what it says second by second.

Parses the MP4/MOV box structure directly and reads only the index (moov) plus the small metadata samples it points
to - never the video frames. Decodes GoPro GPMF ('gpmd': ACCL, GYRO, GPS5, GPSF), CAMM ('camm' accelerometer) and DJI
'djmd' (Osmo Action 4 layout: an acceleration vector in g at protobuf field 3.2.10, one per frame, read about ten times
a second), and records other metadata tracks (DJI 'dbgi', Apple 'mebx', timecode) by presence and sample count.
Writes two CSVs outside the corpus: one row per file, and one row per second of motion data (mean, max and spread of
acceleration magnitude in m/s^2, gyro magnitude, and GPS altitude/speed when there is a fix).
Standard library only, so it runs on the worker's system Python.
"""
from __future__ import annotations

import argparse
import csv
import math
import struct
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ISOBMFF = {'.mp4', '.mov', '.360', '.m4v', '.3gp'}
DECODED = {'gpmd', 'camm', 'djmd'}
COUNTED = {'dbgi', 'mebx', 'tmcd', 'fdsc', 'rtmd'}
MAX_MOOV_BYTES = 256 * 1024 * 1024
DJI_RATE_HZ = 10
STANDARD_GRAVITY = 9.80665
NUMERIC = {ord('b'): 'b', ord('B'): 'B', ord('s'): 'h', ord('S'): 'H', ord('l'): 'i', ord('L'): 'I',
           ord('f'): 'f', ord('d'): 'd', ord('j'): 'q', ord('J'): 'Q'}
FILE_FIELDS = ['rel_path', 'extension', 'status', 'metadata_tracks', 'gpmd_samples', 'accel_samples', 'accel_hz',
               'accel_seconds', 'gyro_samples', 'gps_payloads', 'gps_fix_max', 'gps_fix_seconds', 'camm_accel_samples',
               'djmd_samples', 'dji_accel_samples', 'dbgi_samples', 'djmd_first_bytes', 'mebx_samples', 'error']
SECOND_FIELDS = ['rel_path', 't_sec', 'accel_mean', 'accel_max', 'accel_std', 'gyro_mean', 'gps_alt_m',
                 'gps_speed3d_ms', 'gps_fix']


def log(message):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {message}', flush=True)


def key(path):
    return Path(path).resolve().as_posix().casefold()


def iter_boxes(buf, start=0, end=None):
    end = len(buf) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from('>I4s', buf, pos)
        head = 8
        if size == 1:
            if pos + 16 > end:
                return
            size, head = struct.unpack_from('>Q', buf, pos + 8)[0], 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            return
        yield kind.decode('latin-1'), pos + head, pos + size
        pos += size


def child(buf, span, name):
    for kind, start, end in iter_boxes(buf, *span):
        if kind == name:
            return start, end
    return None


def find_top_box(handle, file_size, name):
    wanted = name.encode('latin-1')
    offset = 0
    while offset + 8 <= file_size:
        handle.seek(offset)
        header = handle.read(16)
        if len(header) < 8:
            return None
        size, kind = struct.unpack('>I4s', header[:8])
        head = 8
        if size == 1:
            size, head = struct.unpack('>Q', header[8:16])[0], 16
        elif size == 0:
            size = file_size - offset
        if size < head:
            return None
        if kind == wanted:
            return offset + head, offset + size
        offset += size
    return None


def table(buf, span, fmt, header=8):
    """Entry count at span start + 4, entries after the header."""
    count = struct.unpack_from('>I', buf, span[0] + 4)[0]
    width = struct.calcsize('>' + fmt)
    return [struct.unpack_from('>' + fmt, buf, span[0] + header + i * width) for i in range(count)]


def parse_track(buf, span):
    mdia = child(buf, span, 'mdia')
    if not mdia:
        return None
    mdhd, minf = child(buf, mdia, 'mdhd'), child(buf, mdia, 'minf')
    stbl = child(buf, minf, 'stbl') if minf else None
    stsd = child(buf, stbl, 'stsd') if stbl else None
    if not (mdhd and stsd):
        return None
    timescale = struct.unpack_from('>I', buf, mdhd[0] + (20 if buf[mdhd[0]] == 1 else 12))[0]
    fmt = buf[stsd[0] + 12:stsd[0] + 16].decode('latin-1')
    track = {'format': fmt, 'timescale': timescale}
    if fmt not in DECODED | COUNTED:
        return track
    stsz = child(buf, stbl, 'stsz')
    uniform, count = struct.unpack_from('>II', buf, stsz[0] + 4)
    sizes = [uniform] * count if uniform else list(struct.unpack_from(f'>{count}I', buf, stsz[0] + 12))
    track['samples'] = count
    if fmt not in DECODED and fmt != 'dbgi':
        return track
    stco, co64 = child(buf, stbl, 'stco'), child(buf, stbl, 'co64')
    chunk_offsets = [v[0] for v in (table(buf, stco, 'I') if stco else table(buf, co64, 'Q'))]
    runs = [tuple(v) for v in table(buf, child(buf, stbl, 'stsc'), 'III')] + [(len(chunk_offsets) + 1, 0, 0)]
    offsets, sample = [], 0
    for (first, per_chunk, _), (next_first, _, _) in zip(runs, runs[1:]):
        for chunk in range(first, min(next_first, len(chunk_offsets) + 1)):
            position = chunk_offsets[chunk - 1]
            for _ in range(per_chunk):
                if sample >= count:
                    break
                offsets.append(position)
                position += sizes[sample]
                sample += 1
    times, clock = [], 0
    for sample_count, delta in table(buf, child(buf, stbl, 'stts'), 'II'):
        for _ in range(sample_count):
            times.append(clock / timescale)
            clock += delta
    times.append(clock / timescale)
    track.update(sizes=sizes[:len(offsets)], offsets=offsets, times=times)
    return track


def gpmf_items(data, start, end):
    pos = start
    while pos + 8 <= end:
        item_key, item_type, size = data[pos:pos + 4], data[pos + 4], data[pos + 5]
        repeat = struct.unpack_from('>H', data, pos + 6)[0]
        length = size * repeat
        body = pos + 8
        if body + length > end:
            return
        yield item_key, item_type, size, repeat, body
        pos = body + ((length + 3) & ~3)


def gpmf_streams(data):
    streams = []

    def recurse(start, end, current):
        for item_key, item_type, size, repeat, body in gpmf_items(data, start, end):
            if item_type == 0:
                if item_key == b'STRM':
                    stream = {}
                    recurse(body, body + size * repeat, stream)
                    streams.append(stream)
                else:
                    recurse(body, body + size * repeat, current)
            elif current is not None:
                current.setdefault(item_key, (item_type, size, repeat, body))
    recurse(0, len(data), None)
    return streams


def decode(data, item):
    item_type, size, repeat, body = item
    code = NUMERIC.get(item_type)
    if code is None:
        return []
    width = struct.calcsize('>' + code)
    per = size // width
    if per == 0:
        return []
    flat = struct.unpack_from('>' + code * (per * repeat), data, body)
    return [flat[i:i + per] for i in range(0, per * repeat, per)]


def scaled(rows, scale_rows):
    factors = [r[0] for r in scale_rows] or [1]
    out = []
    for row in rows:
        if len(factors) == 1:
            out.append(tuple(v / (factors[0] or 1) for v in row))
        else:
            out.append(tuple(v / ((factors[i] if i < len(factors) else 1) or 1) for i, v in enumerate(row)))
    return out


def spread(values, start, end):
    """Place n samples evenly inside a payload's time span."""
    step = (end - start) / max(1, len(values))
    return [(start + (i + 0.5) * step, v) for i, v in enumerate(values)]


def varint(buf, pos):
    shift = value = 0
    while pos < len(buf):
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7f) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
    raise ValueError('truncated varint')


def protobuf_fields(buf):
    pos = 0
    while pos < len(buf):
        tag, pos = varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value, pos = varint(buf, pos)
        elif wire == 1:
            value, pos = buf[pos:pos + 8], pos + 8
        elif wire == 5:
            value, pos = buf[pos:pos + 4], pos + 4
        elif wire == 2:
            length, pos = varint(buf, pos)
            value, pos = buf[pos:pos + length], pos + length
        else:
            return
        yield field, wire, value


def dji_acceleration(payload):
    """Magnitude in m/s^2 of the Osmo Action 4 acceleration vector (field 3.2.10, floats 2-4 in g), or None."""
    try:
        message = payload
        for step in (3, 2, 10):
            message = next((v for f, w, v in protobuf_fields(message) if f == step and w == 2), None)
            if message is None:
                return None
        axes = {f: struct.unpack('<f', v)[0] for f, w, v in protobuf_fields(message) if w == 5 and len(v) == 4}
    except (ValueError, struct.error):
        return None
    if not any(k in axes for k in (2, 3, 4)):
        return None
    return math.sqrt(sum(axes.get(k, 0.) ** 2 for k in (2, 3, 4))) * STANDARD_GRAVITY


def scan(root, rel):
    path = root.joinpath(*rel.split('/'))
    row = {'rel_path': rel, 'extension': path.suffix.lower()}
    if row['extension'] not in ISOBMFF:
        return {**row, 'status': 'not_mp4_container'}, []
    accel, gyro, gps = [], [], []
    try:
        with path.open('rb') as handle:  # read-only
            size = path.stat().st_size
            moov = find_top_box(handle, size, 'moov')
            if not moov:
                return {**row, 'status': 'no_index'}, []
            if moov[1] - moov[0] > MAX_MOOV_BYTES:
                return {**row, 'status': 'index_too_large'}, []
            handle.seek(moov[0])
            buf = handle.read(moov[1] - moov[0])
            tracks = [t for t in (parse_track(buf, (s, e)) for kind, s, e in iter_boxes(buf) if kind == 'trak') if t]
            formats = sorted({t['format'] for t in tracks if t['format'] in DECODED | COUNTED})
            row.update(status='ok', metadata_tracks='|'.join(formats))
            counts = defaultdict(int)
            for track in tracks:
                counts[track['format']] += track.get('samples', 0)
                if track['format'] not in DECODED or not track.get('offsets'):
                    continue
                if track['format'] == 'djmd':
                    handle.seek(track['offsets'][0])
                    row['djmd_first_bytes'] = handle.read(min(48, track['sizes'][0])).hex()
                    duration = track['times'][-1] or 1
                    stride = max(1, round(len(track['offsets']) / duration / DJI_RATE_HZ))
                    for index in range(0, len(track['offsets']), stride):
                        handle.seek(track['offsets'][index])
                        value = dji_acceleration(handle.read(track['sizes'][index]))
                        if value is not None:
                            accel.append((track['times'][index], value))
                            counts['dji_accel'] += 1
                    continue
                for index, (offset, length) in enumerate(zip(track['offsets'], track['sizes'])):
                    handle.seek(offset)
                    payload = handle.read(length)
                    start, end = track['times'][index], track['times'][index + 1]
                    if track['format'] == 'camm':
                        if len(payload) >= 16 and struct.unpack_from('<H', payload, 2)[0] == 3:
                            x, y, z = struct.unpack_from('<3f', payload, 4)
                            accel.append((start, math.sqrt(x * x + y * y + z * z)))
                            counts['camm_accel'] += 1
                        continue
                    for stream in gpmf_streams(payload):
                        scale = decode(payload, stream[b'SCAL']) if b'SCAL' in stream else []
                        if b'ACCL' in stream:
                            values = scaled(decode(payload, stream[b'ACCL']), scale)
                            accel += spread([math.sqrt(sum(v * v for v in s[:3])) for s in values], start, end)
                        if b'GYRO' in stream:
                            values = scaled(decode(payload, stream[b'GYRO']), scale)
                            gyro += spread([math.sqrt(sum(v * v for v in s[:3])) for s in values], start, end)
                        if b'GPS5' in stream:
                            fix = decode(payload, stream[b'GPSF'])[0][0] if b'GPSF' in stream else 0
                            values = scaled(decode(payload, stream[b'GPS5']), scale)
                            if values:
                                counts['gps_payloads'] += 1
                                row['gps_fix_max'] = max(int(row.get('gps_fix_max') or 0), int(fix))
                                if fix >= 2:
                                    gps += [(t, v[2], v[4], fix) for t, v in spread(values, start, end)]
            row.update(gpmd_samples=counts['gpmd'] or '', accel_samples=len(accel) or '', gyro_samples=len(gyro) or '',
                       gps_payloads=counts['gps_payloads'] or '', camm_accel_samples=counts['camm_accel'] or '',
                       djmd_samples=counts['djmd'] or '', dji_accel_samples=counts['dji_accel'] or '',
                       dbgi_samples=counts['dbgi'] or '', mebx_samples=counts['mebx'] or '')
    except Exception as exc:
        return {**row, 'status': 'error', 'error': f'{type(exc).__name__}: {exc}'[:200]}, []

    seconds = defaultdict(lambda: {'accel': [], 'gyro': [], 'gps': []})
    for t, v in accel:
        seconds[int(t)]['accel'].append(v)
    for t, v in gyro:
        seconds[int(t)]['gyro'].append(v)
    for t, alt, speed, fix in gps:
        seconds[int(t)]['gps'].append((alt, speed, fix))
    per_second = []
    for second in sorted(seconds):
        bucket = seconds[second]
        out = {'rel_path': rel, 't_sec': second}
        if bucket['accel']:
            values = bucket['accel']
            mean = sum(values) / len(values)
            out.update(accel_mean=round(mean, 3), accel_max=round(max(values), 3),
                       accel_std=round(math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)), 3))
        if bucket['gyro']:
            out['gyro_mean'] = round(sum(bucket['gyro']) / len(bucket['gyro']), 4)
        if bucket['gps']:
            n = len(bucket['gps'])
            out.update(gps_alt_m=round(sum(g[0] for g in bucket['gps']) / n, 1),
                       gps_speed3d_ms=round(sum(g[1] for g in bucket['gps']) / n, 2),
                       gps_fix=max(g[2] for g in bucket['gps']))
        per_second.append(out)
    if accel:
        span = max(t for t, _ in accel) - min(t for t, _ in accel)
        row.update(accel_hz=round(len(accel) / span, 1) if span else '',
                   accel_seconds=sum(1 for s in per_second if 'accel_mean' in s))
    row['gps_fix_seconds'] = sum(1 for s in per_second if s.get('gps_fix')) or ''
    return row, per_second


def main():
    parser = argparse.ArgumentParser(description='Read-only scan of video metadata tracks for motion and GPS data.')
    parser.add_argument('--root', required=True)
    parser.add_argument('--inventory', required=True, help='CSV with a rel_path column; every row is scanned.')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--only', action='append', default=[], help='Scan just these rel_paths (testing).')
    args = parser.parse_args()

    root, out = Path(args.root), Path(args.output_dir)
    if key(out).startswith(key(root).rstrip('/') + '/'):
        raise SystemExit('Refusing to run: --output-dir is inside the read-only --root.')
    with open(args.inventory, encoding='utf-8-sig', newline='') as handle:
        paths = [r['rel_path'] for r in csv.DictReader(handle)]
    if args.only:
        paths = [p for p in paths if p in set(args.only)]
    out.mkdir(parents=True, exist_ok=True)
    log(f'scanning {len(paths)} files with {args.workers} workers')
    status = defaultdict(int)
    with open(out / 'telemetry_files.csv', 'w', encoding='utf-8', newline='') as files_handle, \
            open(out / 'telemetry_seconds.csv', 'w', encoding='utf-8', newline='') as seconds_handle:
        files_writer = csv.DictWriter(files_handle, fieldnames=FILE_FIELDS, extrasaction='ignore')
        seconds_writer = csv.DictWriter(seconds_handle, fieldnames=SECOND_FIELDS, extrasaction='ignore')
        files_writer.writeheader()
        seconds_writer.writeheader()
        with ThreadPoolExecutor(args.workers) as pool:
            futures = [pool.submit(scan, root, rel) for rel in paths]
            for done, future in enumerate(as_completed(futures), 1):
                row, per_second = future.result()
                files_writer.writerow(row)
                seconds_writer.writerows(per_second)
                status['with_accel' if row.get('accel_samples') else row['status']] += 1
                if done % 500 == 0 or done == len(futures):
                    files_handle.flush()
                    seconds_handle.flush()
                    log(f'  {done}/{len(futures)} {dict(status)}')
    log(f'done: {dict(status)}')


if __name__ == '__main__':
    main()
