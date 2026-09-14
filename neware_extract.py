"""NDAX extraction prototype: NDC v2/type 1, validated against BTSDA R3.

Only Python's standard library is needed by this extraction module.
The record layout and range factors were checked against NewareNDA 2026.6.11;
see THIRD_PARTY_NOTICES.md. Unsupported layouts fail explicitly.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import struct
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET


HEADERS = ["循环号", "充电比容量(mAh/g)", "放电比容量(mAh/g)", "充放电效率(%)",
           "充电能量(Wh)", "放电能量(Wh)", "容量保持率(%)"]
PRECISION = [0, 2, 2, 2, 6, 6, 2]
EXTRACTOR_VERSION = "0.4.5"
CHARGE = {1, 3, 7, 9, 27}
DISCHARGE = {2, 8, 10, 19, 20, 26}
PASSIVE = {4, 5, 13, 21, 22}
# Small current ranges used by this validation profile. Extend only with evidence.
RANGE_FACTORS = {-1: 1e-5, -2: 1e-5, -5: 1e-5,
                 -10: 1e-4, -20: 1e-4, -25: 1e-4, -50: 1e-4,
                 -100: 1e-3, -500: 1e-3}


class ExtractionError(ValueError):
    pass


def read_xml(blob: bytes) -> ET.Element:
    match = re.search(br'encoding=["\']([^"\']+)', blob[:200], re.I)
    encoding = match.group(1).decode("ascii") if match else "utf-8-sig"
    return ET.fromstring(blob.decode(encoding))


def metadata_from_archive(archive: zipfile.ZipFile) -> dict:
    trees = {name: read_xml(archive.read(name)) for name in archive.namelist()
             if name.lower().endswith(".xml")}
    if "TestInfo.xml" not in trees or "Step.xml" not in trees:
        raise ExtractionError("缺少 TestInfo.xml 或 Step.xml。")
    test = trees["TestInfo.xml"].find("config/TestInfo")
    config = trees["Step.xml"].find("config")
    head = trees["Step.xml"].find("config/Head_Info")
    if test is None or config is None or head is None:
        raise ExtractionError("无法识别 XML 元数据结构。")
    return {
        "test_info": dict(test.attrib),
        "step_config": dict(config.attrib),
        "head_info": {node.tag: dict(node.attrib) for node in head},
        "archive_entries": [{"name": i.filename, "size": i.file_size}
                            for i in archive.infolist()],
        "xml_fields": {name: [{"tag": n.tag, "attributes": dict(n.attrib),
                                 "text": (n.text or "").strip()}
                                for n in tree.iter()]
                       for name, tree in trees.items()},
    }


def resolve_name(path: Path, metadata: dict, override: str | None = None) -> dict:
    info, head = metadata["test_info"], metadata["head_info"]
    candidates = {"TestInfo.xml/config/TestInfo/@Barcode": info.get("Barcode", ""),
                  "TestInfo.xml/config/TestInfo/@SN": info.get("SN", ""),
                  "Step.xml/config/Head_Info/PN/@Value": head.get("PN", {}).get("Value", ""),
                  "Step.xml/config/Head_Info/Remark/@Value": head.get("Remark", {}).get("Value", "")}
    if override:
        return {"value": override, "source": "explicit_user_name", "internal_candidates": candidates}
    barcode = info.get("Barcode", "").strip()
    if barcode:
        return {"value": barcode, "source": "TestInfo.xml/config/TestInfo/@Barcode",
                "internal_candidates": candidates}
    # Remove only a FULL suffix proven by this file's own instrument metadata.
    # Do not split at a fixed underscore/hyphen position in the sample name.
    try:
        timestamp = datetime.strptime(info["StartTime"], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d%H%M%S")
        suffix = "_" + "_".join([info["DevID"], info["UnitID"], info["ChlID"], timestamp])
    except (KeyError, ValueError):
        suffix = ""
    if suffix and path.stem.endswith(suffix) and len(path.stem) > len(suffix):
        return {"value": path.stem[:-len(suffix)], "source": "filename_with_metadata_verified_suffix",
                "removed_suffix": suffix, "internal_candidates": candidates,
                "note": "来自外部文件名；内部信息只用于核实设备、通道及时间后缀。"}
    return {"value": path.stem, "source": "full_filename_stem_unconfirmed",
            "internal_candidates": candidates,
            "note": "未能确定样品名，保留完整文件名；可用 --name 明确指定。"}


def mass_from_metadata(metadata: dict, override_mg: float | None) -> tuple[float, str]:
    if override_mg is not None:
        mass_mg, source = override_mg, "explicit_user_mass_mg"
    else:
        # Validated here for the user's BTSDA 8.0 R3 Step File v16.
        # SCQ=896 -> 0.896 mg -> 0.000896 g reproduces all 3010 capacities.
        config, head = metadata["step_config"], metadata["head_info"]
        if config.get("version") != "16" or "BTSDA 8.0" not in config.get("client_version", ""):
            raise ExtractionError("该元数据版本的质量换算尚未验证，请提供 --mass-mg。")
        scq = head.get("SCQ", {})
        if scq.get("Is_Select") != "1" or not scq.get("Value"):
            raise ExtractionError("缺少可用的 SCQ 活性物质质量，请提供 --mass-mg。")
        mass_mg = float(scq["Value"]) / 1000
        source = "Step.xml/config/Head_Info/SCQ/@Value divided by 1000 (mg); validated R3 profile"
    if not math.isfinite(mass_mg) or mass_mg <= 0:
        raise ExtractionError("活性物质质量必须为正数，单位 mg。")
    return mass_mg, source


@dataclass(frozen=True)
class Record:
    index: int
    native_cycle: int
    step: int
    status: int
    time_ms: int
    totals: tuple[float, float, float, float]
    timestamp: str
    range_code: int
    offset: int
    raw_totals: tuple[int, int, int, int] | None = None

    @property
    def direction(self) -> str | None:
        if self.status in CHARGE:
            return "charge"
        if self.status in DISCHARGE:
            return "discharge"
        return None


def read_records(blob: bytes, metadata: dict):
    if len(blob) < 1024 or blob[0] != 1 or blob[2] != 2:
        raise ExtractionError("当前验证版仅支持 NDC version 2 / filetype 1。")
    if len(blob) % 512:
        raise ExtractionError("NDC 数据页不完整，拒绝静默截断。")
    info = metadata["test_info"]
    previous_index = 0
    for page in range(512, len(blob), 512):
        page_type, count, mask = struct.unpack_from("<HHB", blob, page)
        if (page_type, count, mask) == (0, 0, 0):
            if any(blob[page:page + 512]):
                raise ExtractionError(f"未识别的非空数据页：{page}。")
            continue
        if page_type != 2 or not 1 <= count <= 5 or mask != (1 << count) - 1:
            raise ExtractionError(f"未识别的数据页结构：offset={page}, count={count}, mask={mask}。")
        for slot in range(count):
            offset = page + 5 + 94 * slot
            raw = blob[offset:offset + 94]
            unit, channel, test_id = raw[1], raw[2], struct.unpack_from("<I", raw, 4)[0]
            if (raw[0] != 0x55 or unit != int(info["UnitID"]) or channel != int(info["ChlID"])
                    or test_id != int(info["TestID"])):
                raise ExtractionError(f"记录归属与 TestInfo 不一致：offset={offset}。")
            index, native_cycle, step, status = struct.unpack_from("<IIBB", raw, 8)
            if index != previous_index + 1:
                raise ExtractionError(f"记录编号缺失、重复或起点不是 1：{previous_index} -> {index}。")
            if status not in CHARGE | DISCHARGE | PASSIVE:
                raise ExtractionError(f"尚未验证的工步类型 {status}，记录 {index}。")
            previous_index = index
            time_ms = struct.unpack_from("<Q", raw, 23)[0]
            range_code = struct.unpack_from("<i", raw, 82)[0]
            if range_code not in RANGE_FACTORS:
                raise ExtractionError(f"尚未验证的电流量程 {range_code}，记录 {index}。")
            multiplier = RANGE_FACTORS[range_code]
            raw_totals = struct.unpack_from("<qqqq", raw, 43)
            totals = tuple(n * multiplier / 3600 for n in raw_totals)
            if any(v < 0 for v in totals):
                raise ExtractionError(f"记录 {index} 的累计容量/能量为负，需检查格式。")
            stamp = datetime(*struct.unpack_from("<HBBBBB", raw, 75)).isoformat(sep=" ")
            yield Record(index, native_cycle, step, status, time_ms, totals, stamp, range_code, offset, raw_totals)


def aggregate_records(records, mass_mg: float, cycle_mode: str = "auto") -> tuple[list[dict], dict]:
    rows, step_count, count = [], 0, 0
    cycle_totals = [Fraction(0)] * 4
    exact_discharges = []
    mass_g = Fraction(str(mass_mg)) / 1000
    cycle_dirs: set[str] = set()
    first_direction = None if cycle_mode == "auto" else cycle_mode
    last_direction, previous = None, None
    ranges: set[int] = set()
    native_values: set[int] = set()
    first_timestamp = None
    endpoints = []

    def finish_step(rec):
        nonlocal step_count
        step_count += 1
        if rec.direction:
            # Accumulate original integer counters as exact rational numbers.
            # Convert to float only for JSON storage, after all arithmetic.
            if rec.raw_totals is not None:
                factor = Fraction(str(RANGE_FACTORS[rec.range_code])) / 3600
                precise = [n * factor for n in rec.raw_totals]
            else:
                precise = [Fraction(str(n)) for n in rec.totals]
            for k, v in enumerate(precise):
                cycle_totals[k] += v
            cycle_dirs.add(rec.direction)
            endpoints.append({"record_index": rec.index, "byte_offset": rec.offset,
                              "step_index": rec.step, "status": rec.status,
                              "raw_cycle_counter": rec.native_cycle,
                              "capacity_mAh_energy_mWh": list(rec.totals)})

    def finish_cycle():
        nonlocal cycle_totals, cycle_dirs, endpoints
        if not cycle_dirs:
            return
        q_chg, q_dchg, e_chg, e_dchg = cycle_totals
        exact_discharges.append(q_dchg)
        rows.append({"cycle": len(rows) + 1,
                     "charge_specific_capacity_mAh_g": float(q_chg / mass_g),
                     "discharge_specific_capacity_mAh_g": float(q_dchg / mass_g),
                     "efficiency_percent": float(q_chg / q_dchg * 100) if q_dchg else None,
                     "charge_energy_Wh": float(e_chg / 1000),
                     "discharge_energy_Wh": float(e_dchg / 1000),
                     "capacity_retention_percent": None,
                     "charge_capacity_mAh": float(q_chg), "discharge_capacity_mAh": float(q_dchg),
                     "has_both_directions": cycle_dirs == {"charge", "discharge"},
                     "source_step_endpoints": endpoints})
        cycle_totals, cycle_dirs, endpoints = [Fraction(0)] * 4, set(), []

    for rec in records:
        count += 1
        ranges.add(rec.range_code)
        native_values.add(rec.native_cycle)
        if first_timestamp is None:
            first_timestamp = rec.timestamp
        new_step = previous is not None and (rec.step != previous.step or rec.status != previous.status)
        if previous is not None:
            if new_step:
                finish_step(previous)
            else:
                if rec.time_ms < previous.time_ms:
                    raise ExtractionError(f"同一工步时间回退，需核实续测逻辑：记录 {rec.index}。")
                if any(a + 1e-12 < b for a, b in zip(rec.totals, previous.totals)):
                    raise ExtractionError(f"同一工步累计量回退，需核实续测逻辑：记录 {rec.index}。")
        direction = rec.direction
        if direction:
            if first_direction is None:
                first_direction = direction
            if direction == first_direction and last_direction not in (None, first_direction):
                finish_cycle()
            last_direction = direction
        previous = rec
    if previous is None or first_direction is None:
        raise ExtractionError("没有可用的充放电记录。")
    finish_step(previous)
    finish_cycle()
    baseline = exact_discharges[0]
    for row, discharge in zip(rows, exact_discharges):
        row["capacity_retention_percent"] = float(discharge / baseline * 100) if baseline else None
    return rows, {"record_count": count, "step_count": step_count,
                  "cycle_count": len(rows), "cycle_first_direction": first_direction,
                  "cycles_with_both_directions": sum(r["has_both_directions"] for r in rows),
                  "raw_cycle_counter_unique_count": len(native_values),
                  "raw_cycle_counter_min": min(native_values), "raw_cycle_counter_max": max(native_values),
                  "record_range_codes": sorted(ranges),
                  "first_timestamp": first_timestamp, "last_timestamp": previous.timestamp,
                  "last_step_completion": "未从本解析器判定；有双向记录不等同于工步已结束"}


VALUE_KEYS = ["cycle", "charge_specific_capacity_mAh_g", "discharge_specific_capacity_mAh_g",
              "efficiency_percent", "charge_energy_Wh", "discharge_energy_Wh", "capacity_retention_percent"]


def format_value(value, digits: int) -> str:
    """Use decimal half-up, not Python's default ties-to-even formatting."""
    if value is None:
        return ""
    with localcontext() as context:
        context.prec = 40
        rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return f"{rounded:.{digits}f}"


def display_row(row: dict) -> list[str]:
    return [format_value(row[key], digits)
            for key, digits in zip(VALUE_KEYS, PRECISION)]


def verify_reference(rows: list[dict], reference: Path) -> dict:
    parsed = list(csv.reader(io.StringIO(reference.read_text(encoding="utf-8-sig")), delimiter="\t"))
    parsed = [r[:7] for r in parsed if any(x.strip() for x in r)]
    if not parsed or parsed[0] != HEADERS:
        raise ExtractionError("对照表列名/列顺序与本次验证要求不一致。")
    expected = parsed[1:]
    got = {str(row["cycle"]): display_row(row) for row in rows}
    if any(len(r) != 7 for r in expected) or len({r[0] for r in expected}) != len(expected):
        raise ExtractionError("对照表有缺列或重复循环号。")
    by_column = {name: {"matched": 0, "mismatched": 0, "max_abs_unrounded_difference": 0.0}
                 for name in HEADERS[1:]}
    differences = []
    for r in expected:
        cycle = r[0]
        if cycle not in got:
            differences.append({"cycle": cycle, "reason": "missing_extracted_cycle"})
            continue
        actual = got[cycle]
        raw = rows[int(cycle) - 1]
        for i in range(1, 7):
            match = actual[i] == r[i]
            stats = by_column[HEADERS[i]]
            stats["matched" if match else "mismatched"] += 1
            if raw[VALUE_KEYS[i]] is not None:
                stats["max_abs_unrounded_difference"] = max(stats["max_abs_unrounded_difference"],
                    abs(raw[VALUE_KEYS[i]] - float(r[i])))
            if not match:
                differences.append({"cycle": int(cycle), "column": HEADERS[i],
                                    "expected": r[i], "actual": actual[i]})
    expected_ids = {r[0] for r in expected}
    extra = sorted(set(got) - expected_ids, key=int)
    return {"reference_path": str(reference.resolve()),
            "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
            "reference_cycles": len(expected), "extracted_cycles": len(rows),
            "expected_value_count": len(expected) * 6,
            "matched_value_count": sum(v["matched"] for v in by_column.values()),
            "all_match_at_reference_precision": not differences and not extra and len(expected) == len(rows),
            "precision_by_column": dict(zip(HEADERS[1:], PRECISION[1:])),
            "by_column": by_column, "differences": differences, "extra_extracted_cycles": extra,
            "note": "仅比较对照表显示精度；原始未舍入数值另存，不声称与未提供的小数位一致。"}


def extract(path: Path, *, name: str | None = None, mass_mg: float | None = None,
            cycle_mode: str = "auto") -> dict:
    with zipfile.ZipFile(path) as archive:
        metadata = metadata_from_archive(archive)
        resolved = resolve_name(path, metadata, name)
        mass, mass_source = mass_from_metadata(metadata, mass_mg)
        if "data.ndc" not in archive.namelist():
            raise ExtractionError("缺少 data.ndc。")
        blob = archive.read("data.ndc")
        rows, audit = aggregate_records(read_records(blob, metadata), mass, cycle_mode)
        # Search the inferred/user-provided sample name in every decompressed member.
        # A miss rules out these plaintext encodings, not arbitrary unknown encodings.
        search = {entry: {encoding: archive.read(entry).find(resolved["value"].encode(encoding))
                          for encoding in ("utf-8", "utf-16le", "utf-16be", "utf-32le", "utf-32be")}
                  for entry in archive.namelist()}
    return {"schema_version": 2, "extractor_version": EXTRACTOR_VERSION,
            "display_rounding": "decimal ROUND_HALF_UP",
            "source_file": str(path.resolve()),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "sample_name": resolved, "sample_name_plaintext_search_offsets": search,
            "mass_mg": mass, "mass_source": mass_source, "audit": audit,
            "formula": {"specific_capacity": "capacity_mAh / (mass_mg / 1000)",
                        "efficiency": "charge_capacity_mAh / discharge_capacity_mAh * 100",
                        "retention": "discharge_capacity_mAh / first_cycle_discharge_capacity_mAh * 100",
                        "energy": "step_end_energy_mWh / 1000",
                        "aggregation": "sum final recorded cumulative totals of each executed step"},
            "metadata": metadata, "cycles": rows}


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")[:150]
    if not name:
        return "unnamed"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name):
        name = "_" + name
    return name


def main() -> int:
    parser = argparse.ArgumentParser(description="新威 NDAX 循环指标提取与逐值核验（验证版，无 Excel 输出）")
    parser.add_argument("file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--mass-mg", type=float)
    parser.add_argument("--cycle-mode", choices=["auto", "charge", "discharge"], default="auto")
    args = parser.parse_args()
    result = extract(args.file, name=args.name, mass_mg=args.mass_mg, cycle_mode=args.cycle_mode)
    if args.reference:
        result["verification"] = verify_reference(result["cycles"], args.reference)
    args.out.mkdir(parents=True, exist_ok=True)
    stem = safe_filename(result["sample_name"]["value"])
    output = args.out / f"{stem}.extracted.json"
    # Preserve previous runs and avoid overwriting a different test with the same name.
    if output.exists():
        raise ExtractionError(f"结果已存在：{output}。请使用新的 --out 目录。")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    summary = {"output": str(output.resolve()), "sample_name": result["sample_name"],
               "mass_mg": result["mass_mg"], "audit": result["audit"],
               "verification": result.get("verification")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not args.reference or result["verification"]["all_match_at_reference_precision"] else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (ExtractionError, OSError, zipfile.BadZipFile, ET.ParseError, ValueError, KeyError) as exc:
        print(f"提取失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
