"""Column order and selection shared by preview, batch and Excel export."""
from battery_schema import FIELD_LABELS

DEFAULT_COLUMNS = (0, 1, 2, 3)


def selected_columns(columns=None) -> tuple[int, ...]:
    values = tuple(DEFAULT_COLUMNS if columns is None else columns)
    if not values or any(type(i) is not int or i not in range(len(FIELD_LABELS)) for i in values):
        raise ValueError("请至少选择一项有效的提取字段。")
    return tuple(i for i in range(len(FIELD_LABELS)) if i in values)
