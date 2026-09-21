"""Offline batch service shared by the GUI and the executable command line."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import threading
from typing import Callable

from neware_columns import DEFAULT_COLUMNS, selected_columns
from neware_excel import export_workbook
from neware_extract import EXTRACTOR_VERSION, safe_filename
from battery_extract import extract, EXTENSIONS
from battery_schema import profile, available_columns
from land_statistics import StatisticsChoiceRequired
from batch_statistics import file_statistics


def collect_files(paths: list[Path], recursive: bool = True) -> list[Path]:
    result, seen = [], set()
    for path in paths:
        candidates = sorted(path.rglob("*") if recursive else path.glob("*")) if path.is_dir() else [path]
        for file in candidates:
            if file.is_file() and file.suffix.lower() in EXTENSIONS:
                full = file.resolve()
                key = str(full).casefold()
                if key not in seen:
                    result.append(full)
                    seen.add(key)
    return result


def unique_directory(parent: Path, name: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    for index in range(1, 100000):
        target = parent / (name if index == 1 else f"{name}_{index}")
        try:
            target.mkdir()
            return target
        except FileExistsError:
            continue
    raise OSError("同名结果过多，请更换输出目录。")


def json_write(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def save_result(result: dict, run_directory: Path, columns=None) -> dict:
    columns = selected_columns(columns)
    schema = profile(result)
    columns = available_columns(columns, schema)
    name = safe_filename(result["sample_name"]["value"])
    folder = unique_directory(run_directory / "原始提取记录", name)
    data_path = folder / f"{name}.extracted.json"
    json_write(data_path, result)
    single_direction = [row["cycle"] for row in result["cycles"] if not row["has_both_directions"]]
    policy = result['audit'].get('statistics_policy')
    efficiency = ('效率 = 放电容量 / 充电容量 × 100%。'
                  if policy and policy['mode'] == 'charge' else '效率 = 充电容量 / 放电容量 × 100%。')
    source_names = {"filename_with_metadata_verified_suffix": "外部文件名（已用内部设备、通道和开始时间核实后缀）",
                    "full_filename_stem_unconfirmed": "完整文件名（样品名未确认）",
                    "TestInfo.xml/config/TestInfo/@Barcode": "文件内部条码",
                    "explicit_user_name": "用户指定", "input_filename_stem": "输入测试文件名"}
    notes = [f"样品：{result['sample_name']['value']}", f"原始文件：{result['source_file']}",
             f"名称来源：{source_names.get(result['sample_name']['source'], result['sample_name']['source'])}",
             f"活性质量：{result['mass_mg']} mg" if result['mass_mg'] is not None else "活性质量：未填写，按容量（mAh）导出。",
             f"原始记录：{result['audit']['record_count']}",
             f"循环条目：{result['audit']['cycle_count']}",
             "Excel 输出列：" + "、".join(schema['headers'][i] for i in columns),
             "循环统计：" + ("放电优先" if result['audit']['cycle_first_direction'] == "discharge" else "充电优先"),
             efficiency, schema['retention_note'],
             "完整 JSON 保留未舍入值、统计口径、源文件哈希及来源记录。"]
    if policy:
        notes.append('口径来源：' + ('用户为该文件指定' if policy['source'] == 'explicit_user_choice' else
                                  f"文件内设置（标志 {policy['header_value']:#04x}，已核验格式映射）"))
        notes.append('已检查原始工步顺序、方向和循环边界；每个充放电段仅分配一次。')
        if result['audit'].get('energy_decrease_count'):
            notes.append(f"原始能量有 {result['audit']['energy_decrease_count']} 处下降；按末值导出，未取最大值、归零或重排。示例见 JSON。")
        if result['audit'].get('negative_energy_record_count'):
            notes.append('原始文件含负能量记录，按蓝电原值保留。')
        if result['audit'].get('terminal_current_anomaly_count'):
            notes.append(f"有 {result['audit']['terminal_current_anomaly_count']} 条收尾电流异常，已用后续零电流静置及相同累计值核验；保留原始工步方向，详情见 JSON。")
        if result['audit'].get('resume_checkpoint_count'):
            notes.append(f"有 {result['audit']['resume_checkpoint_count']} 处暂停恢复时的检查点回退；已核对设备、版本和事件顺序，保留原始记录顺序，按工步最终累计值导出。")
        if result['audit'].get('resume_placeholder_count'):
            notes.append(f"跳过 {result['audit']['resume_placeholder_count']} 条紧邻已核验恢复事件的全零占位记录；偏移保存在 JSON。")
    if single_direction:
        notes += ["仅单向记录的循环：" + "、".join(map(str, single_direction)),
                  "这些循环已原样保留；缺少方向的 0 代表尚无该方向记录，不能据此评价完整循环。"]
    notes += ["有双向记录也不等于本工具已证明最后工步结束。",
              "本程序没有联网、模型调用或上传数据的功能。",
              f"提取器版本：{EXTRACTOR_VERSION}"]
    (folder / "提取说明.txt").write_text("\n".join(notes) + "\n", encoding="utf-8-sig")
    return {"sample_name": result["sample_name"]["value"], "name_source": result["sample_name"]["source"],
            "directory": str(folder), "data": str(data_path),
            "records": result["audit"]["record_count"], "cycles": result["audit"]["cycle_count"],
            "mass_mg": result["mass_mg"], "single_direction_cycles": single_direction,
            "capacity_basis": result.get('capacity_basis', 'specific'), "warnings": result.get('warnings', []),
            "format": result.get('format', 'neware_ndax'), "retention_note": schema['retention_note'],
            "statistics_policy": policy,
            "energy_decrease_count": result['audit'].get('energy_decrease_count', 0),
            "negative_energy_record_count": result['audit'].get('negative_energy_record_count', 0),
            "terminal_current_anomaly_count": result['audit'].get('terminal_current_anomaly_count', 0),
            "resume_checkpoint_count": result['audit'].get('resume_checkpoint_count', 0),
            "resume_placeholder_count": result['audit'].get('resume_placeholder_count', 0),
            "source_sha256": result["source_sha256"], "selected_columns": list(columns)}


def run_batch(files: list[Path], output: Path, *, cycle_mode: str = "auto",
              columns=None, land_modes: dict[str, str] | None = None,
              cancel: threading.Event | None = None,
              on_event: Callable[[dict], None] | None = None) -> dict:
    if not files:
        raise ValueError("请先选择包含 .ndax 或 .cex 的文件夹。")
    columns = selected_columns(columns)
    land_modes = {str(Path(path).resolve()).casefold(): mode for path, mode in (land_modes or {}).items()}
    if any(mode not in ('auto', 'charge', 'discharge') for mode in land_modes.values()):
        raise ValueError('无效的蓝电循环统计方向。')
    cancel = cancel or threading.Event()
    emit = on_event or (lambda _: None)
    run_directory = unique_directory(output.resolve(), datetime.now().strftime("提取_%Y%m%d_%H%M%S"))
    manifest = {"extractor_version": EXTRACTOR_VERSION, "created_at": datetime.now().astimezone().isoformat(),
                "run_directory": str(run_directory), "cycle_mode": cycle_mode,
                "land_modes": land_modes,
                "selected_columns": list(columns),
                "workbook": None, "excel_error": None, "excel_sheets": [],
                "total": len(files), "success": 0, "failed": 0, "cancelled": False,
                "entries": []}
    manifest_path = run_directory / "批次记录.json"
    emit({"type": "batch_started", "directory": str(run_directory)})
    for index, path in enumerate(files):
        if cancel.is_set():
            manifest["cancelled"] = True
            break
        emit({"type": "file_started", "index": index, "path": str(path)})
        try:
            mode = land_modes.get(str(path.resolve()).casefold(), cycle_mode) if path.suffix.lower() == '.cex' else cycle_mode
            result = extract(path, cycle_mode=mode)
            item = {"index": index, "source": str(path), "status": "success", **save_result(result, run_directory, columns)}
            manifest["success"] += 1
        except Exception as exc:
            # One bad file must not suppress results for the remaining queue.
            item = {"index": index, "source": str(path), "status": "error",
                    "error": f"{type(exc).__name__}: {exc}"}
            if isinstance(exc, StatisticsChoiceRequired):
                item['error_code'] = 'statistics_choice_required'
            manifest["failed"] += 1
        manifest["entries"].append(item)
        json_write(manifest_path, manifest)
        emit({"type": "file_done", **item})
    if manifest["success"]:
        emit({"type": "workbook_started"})
        workbook_path = run_directory / "循环数据.xlsx"
        try:
            manifest["excel_sheets"] = export_workbook(manifest["entries"], workbook_path, columns)
            manifest["workbook"] = str(workbook_path)
            for mapping in manifest["excel_sheets"]:
                manifest["entries"][mapping["index"]]["sheet_name"] = mapping["sheet_name"]
        except Exception as exc:
            manifest["excel_error"] = f"Excel 保存失败：{type(exc).__name__}: {exc}"
    manifest["skipped"] = len(files) - len(manifest["entries"])
    manifest['statistics'] = file_statistics(manifest['entries'])
    manifest["completed_at"] = datetime.now().astimezone().isoformat()
    json_write(manifest_path, manifest)
    emit({"type": "batch_done", "manifest": manifest})
    return manifest
