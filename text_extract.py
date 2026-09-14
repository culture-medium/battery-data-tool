"""Offline CHI EIS/CV and ordinary delimited-text parsing; no model dependency."""
from __future__ import annotations

import csv
import io
import math
from pathlib import Path
import re


def read_text(path):
    raw = Path(path).read_bytes()
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16'), 'UTF-16'
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            text = raw.decode(encoding)
            if '\x00' in text:
                raise ValueError('文本含空字符，请另存为 UTF-8 或带 BOM 的 UTF-16。')
            return text, encoding
        except UnicodeDecodeError:
            pass
    raise ValueError('无法识别文本编码，请另存为 UTF-8。')


def detect_kind(text):
    start = '\n'.join(text.splitlines()[:30]).lower()
    if 'a.c. impedance' in start: return 'EIS'
    if 'cyclic voltammetry' in start: return 'CV'
    return '通用'


def delimiter_for(text, requested='自动'):
    choices = {'逗号': ',', '制表符': '\t', '分号': ';', '空白': None}
    if requested != '自动': return choices[requested]
    sample = '\n'.join(text.splitlines()[:20])
    counts = {d: sample.count(d) for d in ('\t', ',', ';')}
    return max(counts, key=counts.get) if max(counts.values()) else None


def cells(text, delimiter):
    if delimiter is None:
        return [re.split(r'\s+', line.strip()) for line in text.splitlines() if line.strip()]
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if any(v.strip() for v in row)]


def numeric_or_text(value):
    text = value.strip()
    if not text: return None
    # Identifiers and numbers beyond Excel's 15-digit precision remain literal.
    if re.fullmatch(r'[+-]?\d+', text):
        digits = text.lstrip('+-')
        if len(digits) > 15 or len(digits) > 1 and digits.startswith('0'): return text
        return int(text)
    if re.fullmatch(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?', text):
        significant = re.sub(r'\D', '', re.split('[eE]', text)[0]).lstrip('0')
        number = float(text)
        if math.isfinite(number) and len(significant) <= 15: return number
    return text


def split_cv(rows, metadata):
    try:
        high, low = float(metadata['High E (V)']), float(metadata['Low E (V)'])
        interval = float(metadata.get('Sample Interval (V)', '.001'))
        if not all(math.isfinite(v) for v in (high, low, interval)) or low >= high or interval <= 0:
            raise ValueError()
    except (KeyError, ValueError):
        return [rows], '缺少有效的 CV 电压边界，已保留整段；未推断圈数。'
    tolerance, turns, previous = max(interval * 3, .003), [], 0
    for i in range(1, len(rows)):
        difference = rows[i][0] - rows[i-1][0]
        if previous and difference * previous < 0 and min(abs(rows[i][0]-high), abs(rows[i][0]-low)) < tolerance:
            turns.append(i)
        if difference: previous = difference
    bounds = [0] + turns[1::2] + [len(rows)]
    return [rows[a:b] for a, b in zip(bounds, bounds[1:]) if b > a], '按电压边界每两次反转分一圈；末尾不足一圈的数据也保留。'


def parse_text(path, *, delimiter='自动', header='自动'):
    path = Path(path)
    text, encoding = read_text(path)
    kind, metadata, warnings = detect_kind(text), {}, []
    result = {'source': str(path.resolve()), 'name': path.stem, 'kind': kind, 'encoding': encoding,
              'metadata': metadata, 'warnings': warnings}
    if kind == '通用':
        data = cells(text, delimiter_for(text, delimiter))
        if not data: raise ValueError('文本没有数据。')
        values = [[numeric_or_text(v) for v in row] for row in data]
        first = values[0]
        inferred = sum(isinstance(v, str) for v in first) >= max(1, sum(isinstance(v, (float, int)) for v in first))
        has_header = inferred if header == '自动' else header == '首行为表头'
        result.update(headers=data[0] if has_header else None, rows=values[1:] if has_header else values, cycles=[])
        return result
    lines = text.splitlines()
    start, headers = None, None
    for i, line in enumerate(lines):
        normalized = line.lower().replace(' ', '')
        if (kind == 'EIS' and 'freq/hz' in normalized and 'ohm' in normalized) or (kind == 'CV' and 'potential/v' in normalized and 'current/a' in normalized):
            delim = delimiter_for(line)
            headers = [v.strip() for v in cells(line, delim)[0]]
            start = i + 1
            break
        if '=' in line:
            key, value = line.split('=', 1)
            metadata[key.strip()] = value.strip()
        elif ':' in line:
            key, value = line.split(':', 1)
            if key.strip() in ('File', 'Instrument Model', 'Header', 'Note', 'Data Source'):
                metadata[key.strip()] = value.strip()
    if start is None: raise ValueError(f'{kind} 文件缺少可识别的数据列标题。')
    if len(headers) < (5 if kind == 'EIS' else 2): raise ValueError('仪器数据缺列。')
    rows = []
    for number, line in enumerate(lines[start:], start + 1):
        if not line.strip(): continue
        try:
            parts = cells(line, delim)[0]
            values = [float(v.strip()) for v in parts]
            if len(values) != len(headers) or not all(math.isfinite(v) for v in values): raise ValueError()
        except (ValueError, IndexError):
            raise ValueError(f'{kind} 第 {number} 行不是完整的数值记录；已停止该文件，避免漏行。') from None
        rows.append(values)
    if not rows: raise ValueError('仪器文件没有数值记录。')
    cycles = []
    if kind == 'CV':
        cycles, note = split_cv(rows, metadata)
        warnings.append(note)
    result.update(headers=headers, rows=rows, cycles=cycles)
    return result


def validate_ranges(ranges):
    result = []
    for low, high, mode in ranges:
        low, high = float(low), float(high)
        if not math.isfinite(low) or not math.isfinite(high) or low > high or mode not in ('max', 'min'):
            raise ValueError('峰区间须为有效的下限 ≤ 上限，取值方式为 max 或 min。')
        item = (low, high, mode)
        if item not in result: result.append(item)
    return result


def find_peaks(cycles, ranges):
    output = []
    for low, high, mode in validate_ranges(ranges):
        values = []
        for cycle in cycles:
            candidates = (row for row in cycle if low <= row[0] <= high)
            row = (max if mode == 'max' else min)(candidates, key=lambda r: r[1], default=None)
            values.append(None if row is None else {'potential': row[0], 'current': row[1],
                          'logI': math.log10(abs(row[1])) if row[1] else None})
        output.append({'label': f'{low:g}～{high:g} V / {mode}', 'values': values})
    return output
