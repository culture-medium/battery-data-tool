"""Dispatch by file type, without passing text data through a model."""
from pathlib import Path
from neware_extract import extract as extract_neware, ExtractionError
from land_extract import extract as extract_land

EXTENSIONS = {'.ndax', '.cex'}


def extract(path, *, cycle_mode='auto'):
    path = Path(path)
    if path.suffix.lower() == '.ndax':
        result = extract_neware(path, cycle_mode=cycle_mode)
        result['format'] = 'neware_ndax'
        return result
    if path.suffix.lower() == '.cex':
        return extract_land(path, cycle_mode=cycle_mode)
    raise ExtractionError('请选择新威 .ndax 或蓝电 .cex 文件。')
