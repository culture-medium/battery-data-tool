"""Local CEX reader for the two validated 16-byte LAND layouts.

No reference answers, filename-dependent numbers, network or vendor application.
Unknown layouts are rejected rather than interpreted as plausible measurements.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import struct

from neware_extract import EXTRACTOR_VERSION, ExtractionError
from land_statistics import select_statistics, assign_cycles, CHARGE, DISCHARGE

MAGIC = b'\x10\x11\x09\x88'
PROFILES = {b'\x02\x01\x01\x00': 'counter16', b'\x07\x00\x04\x00': 'float16',
            b'\x01\x00\x04\x00': 'float16'}
VERIFIED_RANGES = {b'\x02\x01\x01\x00': {(5, 5)},
                   b'\x07\x00\x04\x00': {(0xe005, 0xc005), (0xe005, 0xc014)},
                   b'\x01\x00\x04\x00': {(5, 5)}}


def percentage(numerator, denominator):
    if not denominator: return None
    value = numerator / denominator * 100
    value = struct.unpack('<f', struct.pack('<f', value))[0]
    # LAND's own local reader applies this display limit; verified with
    # independent values on both sides of 999%, not a sample/cycle exception.
    return value if value <= 999 else 0.0


def read_cex(blob, *, metadata=None):
    metadata = metadata if metadata is not None else {}
    metadata.update(empty_start_rest_steps=[], rest_resume_time_adjustments=[], retention_settings=[])
    if len(blob) < 80 or blob[:4] != MAGIC or len(blob) % 16:
        raise ExtractionError('CEX 文件头无法识别或数据被截断。')
    layout = PROFILES.get(blob[4:8])
    if layout is None:
        raise ExtractionError('此 CEX 版本尚未核验，请提供该文件及官方导出数据。')
    ranges = struct.unpack_from('<HH', blob, 24)
    if ranges not in VERIFIED_RANGES[blob[4:8]]:
        raise ExtractionError(f'此 CEX 量程/存储标志尚未核验：{ranges}。')
    mass_g = struct.unpack_from('<f', blob, 28)[0]
    if not math.isfinite(mass_g) or mass_g < 0:
        raise ExtractionError('CEX 文件内的活性物质质量无效。')
    voltage_scale = current_scale_mA = 5 / 16128
    offset, records, blocks = 64, 0, 0
    steps, references = [], []
    step, cycle_marker = None, None
    pending_status = []
    while offset < len(blob):
        raw = blob[offset:offset + 16]
        signature, word1, word2, word3 = struct.unpack('<4I', raw)
        if signature == 0xffffaaaa:
            end = offset + 16 + (word1 >> 16)
            if end % 16 or end + 16 > len(blob) or blob[end:end+4] != b'\xbb\xbb\xff\xff' or blob[end+4:end+16] != raw[4:]:
                raise ExtractionError(f'CEX 配置数据块不完整：偏移 {offset}。')
            if word1 & 65535 == 0x13:
                plan = blob[offset+16:end]
                if len(plan) < 64 or plan[:4] != b'\x22\x11\x09\x88' or struct.unpack_from('<H', plan, 4)[0] not in (0x32, 0x37):
                    raise ExtractionError('CEX 工步配置版本尚未核验。')
                flags = struct.unpack_from('<H', plan, 46)[0]
                if flags not in (0, 0x8200):
                    raise ExtractionError(f'CEX 保持率参考设置尚未核验：{flags:#x}。')
                metadata['retention_settings'].append({'offset': offset, 'flags': flags})
            blocks += 1
            offset = end + 16
            continue
        if signature in (0xffffcccc, 0xffffcccd):
            kind = word1 & 65535
            if kind == 0x44:
                cycle_marker = {'offset': offset, 'direction_flag': word2, 'native_cycle': word3 >> 16}
            elif kind == 0x22:
                if step is not None:
                    steps.append(step)
                source_mode = word2 & 255
                # The float layout also stores discharge/charge as 02/03.
                # Keep the original code for audit, and still validate both
                # the cycle marker and every signed current record below.
                mode = {0x02: 0x75, 0x03: 0x76}.get(source_mode, source_mode) if layout == 'float16' else source_mode
                if mode not in (0x70, 0x75, 0x76):
                    raise ExtractionError(f'未核验的 CEX 工步类型 {mode:#x}，偏移 {offset}。')
                step = {'offset': offset, 'mode': mode, 'source_mode': source_mode, 'cycle_marker': cycle_marker,
                        'records': 0, 'step_code': word1 >> 16, 'timestamp': word3}
                pending_status = []
            elif kind == 0x33:
                pending_status.append({'offset': offset, 'code': word2, 'value': word3})
            elif kind in (0xb1, 0xb2):
                value = struct.unpack_from('<f', raw, 8)[0]
                if not math.isfinite(value) or value <= 0:
                    raise ExtractionError(f'无效的 CEX 保持率参考值，偏移 {offset}。')
                references.append({'offset': offset, 'kind': kind, 'value': value, 'flags': word3})
            elif kind not in ({0x33, 0x88, 0x91, 0x92} if layout == 'counter16' else {0x33, 0x88, 0x23}):
                raise ExtractionError(f'未核验的 CEX 控制记录 {kind:#x}，偏移 {offset}。')
        else:
            if step is None or signature >> 16 == 0xffff:
                raise ExtractionError(f'CEX 记录结构无法识别，偏移 {offset}。')
            time_raw, voltage, current = struct.unpack_from('<Ihh', raw)
            if layout == 'counter16':
                raw_capacity, raw_energy = struct.unpack_from('<If', raw, 8)
                capacity = raw_capacity * current_scale_mA / 3600 / 1000
                energy = raw_energy * current_scale_mA * voltage_scale / 3600 / 1000
            else:
                capacity, energy = struct.unpack_from('<ff', raw, 8)
                raw_capacity, raw_energy = capacity, energy
            if not all(math.isfinite(v) and v >= 0 for v in (capacity, energy)):
                raise ExtractionError(f'CEX 累计容量/能量无效，偏移 {offset}。')
            if (step['mode'] == 0x75 and current >= 0) or (step['mode'] == 0x76 and current <= 0):
                raise ExtractionError(f'CEX 充放电方向与记录电流不一致，偏移 {offset}。')
            point = {'offset': offset, 'time_raw': time_raw, 'capacity_Ah': capacity, 'energy_Wh': energy,
                     'raw_capacity': raw_capacity, 'raw_energy': raw_energy}
            if step['records']:
                previous = step['last']
                decreasing_quantity = any(point[k] < previous[k] for k in ('capacity_Ah', 'energy_Wh'))
                decreasing_time = point['time_raw'] < previous['time_raw']
                # A verified counter-format pause/resume can rewind the rest
                # timer by one tick while both accumulated quantities stay fixed.
                # Preserve that raw tick and source order; never sort or change it.
                codes = [event['code'] for event in pending_status]
                resume_tick = (layout == 'counter16' and step['mode'] == 0x70 and current == 0
                    and previous['time_raw'] - time_raw == 1
                    and all(point[k] == previous[k] for k in ('capacity_Ah', 'energy_Wh'))
                    and codes == [0x803, 0x203, 0x1008, 0x7f408001, 0xff808001]
                    and pending_status[1]['value'] >= pending_status[0]['value'])
                if decreasing_quantity or (decreasing_time and not resume_tick):
                    raise ExtractionError(f'CEX 工步内累计量回退或时间倒退，偏移 {offset}。')
                if resume_tick:
                    metadata['rest_resume_time_adjustments'].append({'offset': offset,
                        'previous_offset': previous['offset'], 'previous_time_raw': previous['time_raw'],
                        'time_raw': time_raw, 'status_events': list(pending_status)})
            else:
                step['first'] = point
            step['last'] = point
            step['records'] += 1
            records += 1
            pending_status = []
        offset += 16
    if step is not None:
        steps.append(step)
    # Some counter-format files start with an empty rest before the actual rest.
    # It contains no measurement and does not represent a charge/discharge cycle.
    if (len(steps) >= 2 and not steps[0]['records'] and layout == 'counter16'
            and steps[0]['mode'] == steps[1]['mode'] == 0x70 and steps[1]['records']
            and steps[0]['cycle_marker'] == steps[1]['cycle_marker']
            and steps[0]['timestamp'] <= steps[1]['timestamp']):
        metadata['empty_start_rest_steps'].append(steps[0]['offset'])
        steps = steps[1:]
    if not steps or any(not step['records'] for step in steps):
        raise ExtractionError('CEX 文件无数据或包含空工步，请等待文件写入完成。')
    return layout, mass_g, steps, references, records, blocks


def extract(path: Path, *, cycle_mode='auto'):
    path = Path(path)
    blob = path.read_bytes()
    metadata = {}
    layout, mass_g, steps, references, record_count, blocks = read_cex(blob, metadata=metadata)
    groups = []
    for step in steps:
        if step['mode'] == 0x70:
            continue
        marker = step['cycle_marker']
        if marker is None or marker['direction_flag'] != (1 if step['mode'] == 0x75 else 0):
            raise ExtractionError(f'CEX 缺少匹配的循环标记，偏移 {step["offset"]}。')
        if groups and groups[-1][0]['cycle_marker']['offset'] == marker['offset']:
            previous = groups[-1][-1]
            if (step['timestamp'] < previous['timestamp'] or step['mode'] != previous['mode']
                    or any(step['first'][k] < previous['last'][k] for k in ('time_raw', 'capacity_Ah', 'energy_Wh'))):
                raise ExtractionError('CEX 工步恢复时累计量不连续，无法安全合并。')
            groups[-1].append(step)
        else:
            if step['first']['capacity_Ah'] or step['first']['energy_Wh']:
                raise ExtractionError('CEX 首条充放电记录累计量非零，可能缺少前段数据。')
            groups.append([step])
    if not groups:
        raise ExtractionError('CEX 中没有充放电数据。')
    policy = select_statistics(blob, cycle_mode)
    first_mode = policy['first_mode']
    settings = {setting['flags'] for setting in metadata['retention_settings']}
    if len(settings) > 1:
        raise ExtractionError('测试中修改了保持率参考设置，此组合尚未核验。')
    first_charge_reference = settings == {0x8200}
    if first_charge_reference and (first_mode != DISCHARGE or references):
        raise ExtractionError('首圈充电参考与所选循环口径/参考事件组合尚未核验。')
    cycles, assignment = assign_cycles(groups, layout, first_mode)
    # Only charge-based stored reference flags have independent answers.
    if references and (first_mode != DISCHARGE or any(r['flags'] != 0x8200 for r in references)):
        raise ExtractionError('此蓝电参考值的方向/标志尚未核验，无法确认保持率。')
    rows, previous_capacity, previous_energy = [], None, None
    first_capacity, first_energy = None, None
    reference_index, qref, eref = 0, None, None
    has_qref = any(r['kind'] == 0xb1 for r in references)
    has_eref = any(r['kind'] == 0xb2 for r in references)
    for index, cycle in enumerate(cycles, 1):
        charge = [g for g in cycle if g[0]['mode'] == 0x76]
        discharge = [g for g in cycle if g[0]['mode'] == 0x75]
        qch = sum(g[-1]['last']['capacity_Ah'] for g in charge)
        qdis = sum(g[-1]['last']['capacity_Ah'] for g in discharge)
        ech = sum(g[-1]['last']['energy_Wh'] for g in charge)
        edis = sum(g[-1]['last']['energy_Wh'] for g in discharge)
        retained = discharge if first_mode == CHARGE else charge
        qret, eret = (qdis, edis) if first_mode == CHARGE else (qch, ech)
        end = (retained[-1] if retained else cycle[-1])[-1]['last']['offset']
        while reference_index < len(references) and references[reference_index]['offset'] <= end:
            reference = references[reference_index]
            if reference['kind'] == 0xb1: qref = reference
            else: eref = reference
            reference_index += 1
        if retained and first_capacity is None:
            first_capacity, first_energy = qret, eret
        capacity_base = first_capacity if first_charge_reference else previous_capacity
        energy_base = first_energy if first_charge_reference else previous_energy
        retention = (percentage(qret, qref['value']) if qref else 100.0) if has_qref else (percentage(qret, capacity_base) if capacity_base else 100.0)
        energy_retention = (percentage(eret, eref['value']) if eref else 100.0) if has_eref else (percentage(eret, energy_base) if energy_base else 100.0)
        if not retained:
            retention = energy_retention = 0.0
        efficiency = percentage(qdis, qch) if first_mode == CHARGE else percentage(qch, qdis)
        if not (charge and discharge): efficiency = 0.0
        rows.append({'cycle': index, 'charge_specific_capacity_mAh_g': qch * 1000 / mass_g if mass_g else None,
                     'discharge_specific_capacity_mAh_g': qdis * 1000 / mass_g if mass_g else None,
                     'charge_capacity_mAh': qch * 1000, 'discharge_capacity_mAh': qdis * 1000,
                     'efficiency_percent': efficiency,
                     'charge_specific_energy_Wh_kg': ech * 1000 / mass_g if mass_g else None,
                     'discharge_specific_energy_Wh_kg': edis * 1000 / mass_g if mass_g else None,
                     'capacity_retention_percent': retention, 'energy_retention_percent': energy_retention,
                     'charge_energy_Wh': ech, 'discharge_energy_Wh': edis,
                     'charge_energy_mWh': ech * 1000, 'discharge_energy_mWh': edis * 1000,
                     'has_both_directions': bool(charge and discharge),
                     'capacity_reference': qref, 'energy_reference': eref,
                     'source_step_endpoints': [{'mode': g[0]['mode'], 'native_cycle': g[0]['cycle_marker']['native_cycle'],
                                                'cycle_marker_offset': g[0]['cycle_marker']['offset'], 'source_modes': [s['source_mode'] for s in g], 'segments': [s['offset'] for s in g],
                                                'last': g[-1]['last']} for g in cycle]})
        previous_capacity, previous_energy = qret, eret
    return {'extractor_version': EXTRACTOR_VERSION, 'format': 'land_cex', 'source_file': str(path.resolve()),
            'source_sha256': hashlib.sha256(blob).hexdigest(),
            'sample_name': {'value': path.stem, 'source': 'input_filename_stem'},
            'mass_mg': mass_g * 1000 if mass_g else None, 'mass_source': 'CEX offset 28: float32 grams',
            'capacity_basis': 'specific' if mass_g else 'absolute',
            'warnings': [] if mass_g else ['文件未填写活性质量，导出容量（mAh）和能量（mWh）。'],
            'audit': {'layout': layout, 'record_count': record_count, 'step_count': len(steps), **metadata,
                      'statistics_policy': policy, 'cycle_assignment': assignment,
                      'storage_flags': list(struct.unpack_from('<HH', blob, 24)),
                      'source_step_modes': sorted({s['source_mode'] for s in steps}),
                      'cycle_count': len(rows), 'cycle_first_direction': 'charge' if first_mode == 0x76 else 'discharge',
                      'embedded_blocks_skipped': blocks, 'reference_events': references,
                      'percentage_display_limit': 999.0,
                      'continued_steps': sum(len(g) > 1 for g in groups),
                      'capacity_retention_mode': 'first_charge' if first_charge_reference else 'file_reference' if has_qref else 'previous_' + policy['retention_direction'],
                      'energy_retention_mode': 'first_charge' if first_charge_reference else 'file_reference' if has_eref else 'previous_' + policy['retention_direction']},
            'cycles': rows}
