"""CEX statistics policy and checked cycle assignment, separate from raw decoding."""
from neware_extract import ExtractionError

CHARGE, DISCHARGE = 0x76, 0x75


class StatisticsChoiceRequired(ExtractionError):
    """Decodable data whose statistics setting has not been verified."""


def select_statistics(blob, cycle_mode):
    if cycle_mode not in ('auto', 'charge', 'discharge'):
        raise ExtractionError('无效的循环统计方向。')
    flag = blob[32]
    if cycle_mode == 'auto':
        # Empirical mapping verified against four independent user reference
        # tables in the two supported layouts. This is not a public CEX spec.
        # Neither mass, filename, range nor first observed direction selects it.
        mode = {0: 'charge', 1: 'discharge'}.get(flag)
        if mode is None:
            raise StatisticsChoiceRequired(
                f'蓝电循环口径需确认（文件标志 {flag:#04x}）。选中文件，在“更多操作 → 蓝电循环口径”选择与蓝电软件一致的口径后重试。')
        source = 'file_header_byte_32_verified_mapping'
    else:
        mode, source = cycle_mode, 'explicit_user_choice'
    return {'mode': mode, 'source': source, 'header_offset': 32, 'header_value': flag,
            'first_mode': CHARGE if mode == 'charge' else DISCHARGE,
            'retention_direction': 'discharge' if mode == 'charge' else 'charge',
            'efficiency_formula': 'discharge/charge*100' if mode == 'charge' else 'charge/discharge*100'}


def assign_cycles(groups, layout, first_mode):
    """Keep source order; native counters verify boundaries in float16 files."""
    if not groups:
        raise ExtractionError('CEX 中没有充放电数据。')
    for before, after in zip(groups, groups[1:]):
        if before[-1]['last']['offset'] >= after[0]['offset']:
            raise ExtractionError('CEX 工步顺序重叠，无法确认循环边界。')
        if before[-1]['timestamp'] > after[0]['timestamp']:
            raise ExtractionError('CEX 工步起始时间倒退，无法确认记录顺序。')
        if before[0]['mode'] == after[0]['mode']:
            raise ExtractionError('CEX 出现不同循环标记下的连续同方向工步，需核对是否缺少中间记录。')
    cycles, native_keys = [], []
    if layout == 'float16':
        first = groups[0][0]
        expected_start = 1 if first['mode'] == CHARGE else 0
        if first['cycle_marker']['native_cycle'] != expected_start:
            raise ExtractionError('CEX 原生循环计数未从起点开始，可能缺少前段工步。')
        previous = None
        for group in groups:
            step = group[0]
            native = step['cycle_marker']['native_cycle']
            if previous is not None:
                expected = previous['cycle_marker']['native_cycle'] + int(step['mode'] == CHARGE)
                if native != expected:
                    raise ExtractionError(f'CEX 原生循环计数跳号或回退，偏移 {step["offset"]}。')
            key = native + int(first_mode == DISCHARGE and step['mode'] == DISCHARGE)
            if not native_keys or key != native_keys[-1]:
                if native_keys and key != native_keys[-1] + 1:
                    raise ExtractionError('CEX 循环边界不连续，无法安全归圈。')
                cycles.append([]); native_keys.append(key)
            cycles[-1].append(group)
            previous = step
    else:
        # In the validated counter16 layout the high cycle word is always zero.
        # The explicit file/user policy controls boundaries; never sort by value.
        if any(g[0]['cycle_marker']['native_cycle'] != 0 for g in groups):
            raise ExtractionError('此 CEX 计数布局的循环标记尚未核验。')
        current = []
        for group in groups:
            if current and group[0]['mode'] == first_mode:
                cycles.append(current); current = []
            current.append(group)
        if current: cycles.append(current)
    for index, cycle in enumerate(cycles):
        modes = [g[0]['mode'] for g in cycle]
        if len(modes) > 2 or len(set(modes)) != len(modes):
            raise ExtractionError('CEX 同一循环重复分配充放电工步。')
        if len(modes) == 2 and modes[0] != first_mode:
            raise ExtractionError('CEX 循环配对与选定统计口径冲突。')
        if len(modes) == 1 and index not in (0, len(cycles)-1):
            raise ExtractionError('CEX 中间循环缺少充电或放电工步。')
    expected = [s['offset'] for g in groups for s in g]
    assigned = [s['offset'] for c in cycles for g in c for s in g]
    if assigned != expected or len(set(assigned)) != len(assigned):
        raise ExtractionError('CEX 工步分配检查失败：存在遗漏、重复或顺序变化。')
    return cycles, {'all_active_segments_assigned_once': True, 'source_order_preserved': True,
                    'native_cycle_boundaries_checked': layout == 'float16',
                    'assigned_segments': len(assigned), 'active_groups': len(groups),
                    'single_direction_cycles': [i+1 for i, c in enumerate(cycles) if len(c) == 1]}
