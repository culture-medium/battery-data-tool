"""Metric meanings stay attached to their source format."""
from neware_extract import HEADERS, PRECISION, VALUE_KEYS, format_value

FIELD_LABELS = ['循环号', '充电比容量(mAh/g)', '放电比容量(mAh/g)', '充放电效率(%)',
                '充电能量 / 比能量', '放电能量 / 比能量', '容量保持率(%)', '能量保持率（蓝电）']
PREVIEW_KEYS = tuple(f'metric{i}' for i in range(8))
NEWARE = {'name': '新威', 'headers': HEADERS, 'precision': PRECISION, 'keys': VALUE_KEYS,
          'retention_note': '容量保持率：本圈放电容量 / 首圈放电容量 × 100%。能量单位 Wh。'}
LAND = {'name': '蓝电',
        'headers': ['循环序号', '充电比容量/mAh/g', '放电比容量/mAh/g', '效率/%',
                    '充电比能量/Wh/kg', '放电比能量/Wh/kg', '容量保持率/%', '能量保持率/%'],
        'precision': [0, 1, 1, 2, 1, 1, 2, 2],
        'keys': list(VALUE_KEYS[:4]) + ['charge_specific_energy_Wh_kg', 'discharge_specific_energy_Wh_kg',
                                      'capacity_retention_percent', 'energy_retention_percent'],
        'retention_note': '保持率：有文件参考值时按其生效位置计算；无参考值时与上一圈充电量相比。比能量单位 Wh/kg。'}
LAND_ABSOLUTE = {**LAND,
        'headers': ['循环序号', '充电容量/mAh', '放电容量/mAh', '效率/%',
                    '充电能量/mWh', '放电能量/mWh', '容量保持率/%', '能量保持率/%'],
        'precision': [0, 4, 4, 2, 3, 3, 2, 2],
        'keys': ['cycle', 'charge_capacity_mAh', 'discharge_capacity_mAh', 'efficiency_percent',
                 'charge_energy_mWh', 'discharge_energy_mWh', 'capacity_retention_percent', 'energy_retention_percent']}


def profile(result):
    if result.get('format') == 'land_cex':
        schema = dict(LAND_ABSOLUTE if result.get('capacity_basis') == 'absolute' else LAND)
        direction = result.get('audit', {}).get('statistics_policy', {}).get('retention_direction', 'charge')
        label = '放电' if direction == 'discharge' else '充电'
        schema['retention_note'] = f'保持率按{label}量统计：有文件参考值时按生效位置计算；无参考值时与上一圈{label}量相比。'
        return schema
    return NEWARE


def display_values(row, schema):
    return [format_value(row[key], precision) for key, precision in zip(schema['keys'], schema['precision'])]


def available_columns(columns, schema):
    return tuple(i for i in columns if i < len(schema['keys']))
