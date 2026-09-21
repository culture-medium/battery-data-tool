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


def note_energy_decrease(metadata, previous, point, *, step_offset, boundary=False):
    """Energy is a signed measured integral, not a sequence/integrity counter."""
    if point['energy_Wh'] >= previous['energy_Wh']:
        return
    metadata['energy_decrease_count'] += 1
    # Keep bounded examples; endpoints always retain their original values.
    if len(metadata['energy_decrease_examples']) < 32:
        metadata['energy_decrease_examples'].append({'step_offset': step_offset,
            'segment_boundary': boundary, 'previous': dict(previous), 'current': dict(point)})


def verified_float_resume(blob, events, before_offset, after_offset):
    """A contiguous, header-bound pause/resume handshake in float profile 7."""
    if blob[4:8] != b'\x07\x00\x04\x00' or len(events) != 5:
        return False
    channel_code = (blob[8] << 24) | (blob[9] << 16) | 0x100e
    return (after_offset == before_offset + 96
        and [e['offset'] for e in events] == list(range(before_offset+16, after_offset, 16))
        and [e['code'] for e in events] == [0x803, 0x203, 0x1008, 0x11012, channel_code]
        and events[1]['value'] >= events[0]['value']
        and events[2]['value'] == struct.unpack_from('<I', blob, 4)[0]
        and events[3]['value'] == struct.unpack_from('<I', blob, 40)[0]
        and events[4]['value'] == events[1]['value'])


def is_resume_placeholder(blob, offset, step):
    """Only skip one zero slot immediately before a verified resume handshake."""
    if not step or step['mode'] not in (0x75, 0x76) or not step['records']:
        return False
    if blob[offset:offset+16] != bytes(16) or offset+112 > len(blob):
        return False
    events = []
    for pos in range(offset+16, offset+96, 16):
        sig, kind, code, value = struct.unpack_from('<4I', blob, pos)
        if sig != 0xffffcccc or kind != 0x33: return False
        events.append({'offset': pos, 'code': code, 'value': value})
    if not verified_float_resume(blob, events, offset, offset+96): return False
    time, _, current, capacity, energy = struct.unpack_from('<Ihhff', blob, offset+96)
    previous = step['last']
    return (time >> 16 != 0xffff and time >= previous['time_raw']
            and math.isfinite(capacity) and capacity >= previous['capacity_Ah'] > 0
            and math.isfinite(energy) and (current < 0 if step['mode'] == 0x75 else current > 0))


def read_cex(blob, *, metadata=None):
    metadata = metadata if metadata is not None else {}
    metadata.update(empty_start_rest_steps=[], rest_resume_time_adjustments=[], retention_settings=[],
                    energy_decrease_count=0, energy_decrease_examples=[], negative_energy_record_count=0,
                    terminal_current_anomaly_count=0, terminal_current_anomalies=[],
                    resume_checkpoint_count=0, resume_checkpoints=[],
                    resume_placeholder_count=0, resume_placeholders=[])
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
                # Keep the original code for audit; direction comes from this
                # code and its cycle marker, with current as an integrity check.
                mode = {0x02: 0x75, 0x03: 0x76}.get(source_mode, source_mode) if layout == 'float16' else source_mode
                if mode not in (0x70, 0x75, 0x76):
                    raise ExtractionError(f'未核验的 CEX 工步类型 {mode:#x}，偏移 {offset}。')
                step = {'offset': offset, 'mode': mode, 'source_mode': source_mode, 'cycle_marker': cycle_marker,
                        'records': 0, 'step_code': word1 >> 16, 'timestamp': word3,
                        'header_signature': signature, 'steady_rest': mode == 0x70}
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
            if raw == bytes(16) and is_resume_placeholder(blob, offset, step):
                metadata['resume_placeholder_count'] += 1
                if len(metadata['resume_placeholders']) < 32:
                    metadata['resume_placeholders'].append({'offset': offset, 'step_offset': step['offset'],
                        'previous_offset': step['last']['offset'], 'next_data_offset': offset+96,
                        'reason': 'zero_slot_before_verified_pause_resume_handshake'})
                offset += 16
                continue
            time_raw, voltage, current = struct.unpack_from('<Ihh', raw)
            if layout == 'counter16':
                raw_capacity, raw_energy = struct.unpack_from('<If', raw, 8)
                capacity = raw_capacity * current_scale_mA / 3600 / 1000
                energy = raw_energy * current_scale_mA * voltage_scale / 3600 / 1000
            else:
                capacity, energy = struct.unpack_from('<ff', raw, 8)
                raw_capacity, raw_energy = capacity, energy
            if not math.isfinite(capacity) or capacity < 0 or not math.isfinite(energy):
                raise ExtractionError(f'CEX 累计容量/能量无效，偏移 {offset}。')
            if energy < 0:
                metadata['negative_energy_record_count'] += 1
            if step.get('terminal_current_mismatch'):
                # An interior mismatch is never a terminal switching sample.
                raise ExtractionError(f'CEX 充放电方向与记录电流不一致，偏移 {step["terminal_current_mismatch"]["offset"]}。')
            point = {'offset': offset, 'time_raw': time_raw, 'capacity_Ah': capacity, 'energy_Wh': energy,
                     'raw_capacity': raw_capacity, 'raw_energy': raw_energy,
                     'voltage_raw': voltage, 'current_raw': current}
            if (step['mode'] == 0x75 and current >= 0) or (step['mode'] == 0x76 and current <= 0):
                step['terminal_current_mismatch'] = point
            if step['mode'] == 0x70:
                step['steady_rest'] = (step['steady_rest'] and current == 0 and
                    (not step['records'] or all(point[k] == step['first'][k] for k in ('capacity_Ah', 'energy_Wh'))))
            if step['records']:
                previous = step['last']
                decreasing_capacity = capacity < previous['capacity_Ah']
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
                checkpoint = (step['mode'] in (0x75, 0x76) and decreasing_time and decreasing_capacity
                    and verified_float_resume(blob, pending_status, previous['offset'], offset)
                    and time_raw >= step['first']['time_raw'] and capacity >= step['first']['capacity_Ah'])
                if (decreasing_capacity or (decreasing_time and not resume_tick)) and not checkpoint:
                    raise ExtractionError(f'CEX 工步内累计容量回退或时间倒退，偏移 {offset}。')
                if checkpoint:
                    # A file cut during recovery has ambiguous native endpoint
                    # behavior. Require later data in this step to reach the
                    # pre-pause time AND capacity before accepting the step.
                    pending = step.get('_resume_pending', previous)
                    step['_resume_pending'] = {
                        'time_raw': max(pending['time_raw'], previous['time_raw']),
                        'capacity_Ah': max(pending['capacity_Ah'], previous['capacity_Ah']),
                        'offset': offset}
                    metadata['resume_checkpoint_count'] += 1
                    if len(metadata['resume_checkpoints']) < 32:
                        metadata['resume_checkpoints'].append({'step_offset': step['offset'],
                            'previous': dict(previous), 'restored': dict(point),
                            'status_events': list(pending_status), 'reason': 'verified_pause_resume_checkpoint'})
                # Native LAND also retains decreasing/negative energy. Near
                # zero voltage it need not increase with charge throughput.
                note_energy_decrease(metadata, previous, point, step_offset=step['offset'])
                if resume_tick:
                    metadata['rest_resume_time_adjustments'].append({'offset': offset,
                        'previous_offset': previous['offset'], 'previous_time_raw': previous['time_raw'],
                        'time_raw': time_raw, 'status_events': list(pending_status)})
            else:
                step['first'] = point
            recovery = step.get('_resume_pending')
            if recovery and time_raw >= recovery['time_raw'] and capacity >= recovery['capacity_Ah']:
                step.pop('_resume_pending')
                for event in metadata['resume_checkpoints']:
                    if event['step_offset'] == step['offset'] and 'recovered_at_offset' not in event:
                        event['recovered_at_offset'] = offset
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
    for index, active in enumerate(steps):
        if active.get('_resume_pending'):
            raise ExtractionError(f'CEX 暂停恢复后的续测数据不足，无法确认工步末值，偏移 {active["_resume_pending"]["offset"]}。请提供续测完成后的文件或用蓝电软件导出。')
        point = active.get('terminal_current_mismatch')
        if point is None: continue
        rest = steps[index+1] if index+1 < len(steps) else None
        marker = active['cycle_marker']
        # Verified terminal outlier: earlier active records have the correct
        # sign, and a following zero-current rest holds the exact same Q/E.
        # Never reinterpret direction from a single instantaneous current.
        coherent_end = (active['records'] >= 2 and marker is not None
            and marker['direction_flag'] == int(active['mode'] == 0x75)
            and rest is not None and rest['mode'] == 0x70 and rest['steady_rest']
            and rest['cycle_marker'] == marker and rest['timestamp'] >= active['timestamp']
            and rest['first']['time_raw'] >= point['time_raw']
            and all(rest['first'][k] == point[k] for k in ('capacity_Ah', 'energy_Wh')))
        if not coherent_end:
            raise ExtractionError(f'CEX 充放电方向与记录电流不一致，且未通过收尾静置核验，偏移 {point["offset"]}。')
        metadata['terminal_current_anomaly_count'] += 1
        if len(metadata['terminal_current_anomalies']) < 32:
            metadata['terminal_current_anomalies'].append({'step_offset': active['offset'],
                'mode': active['mode'], 'cycle_marker': marker, 'record': dict(point),
                'following_rest_offset': rest['offset'], 'transition_signature': rest['header_signature'],
                'reason': 'terminal_record_followed_by_zero_current_rest_holding_same_capacity_and_energy'})
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
                    or any(step['first'][k] < previous['last'][k] for k in ('time_raw', 'capacity_Ah'))):
                raise ExtractionError('CEX 工步恢复时累计量不连续，无法安全合并。')
            note_energy_decrease(metadata, previous['last'], step['first'], step_offset=step['offset'], boundary=True)
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
    # Stored B1/B2 baselines work with either verified statistics direction.
    if any(r['flags'] != 0x8200 for r in references):
        raise ExtractionError('此蓝电参考值的标志尚未核验，无法确认保持率。')
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
        # A reference set during the following rest belongs to this cycle.
        # Use the next cycle's marker as the boundary, not the active endpoint.
        end = cycles[index][0][0]['cycle_marker']['offset'] - 1 if index < len(cycles) else len(blob) - 1
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
