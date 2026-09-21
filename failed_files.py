"""Optional copies of failed inputs; original files are never moved or changed."""
from pathlib import Path
import os
import shutil
from tkinter import messagebox

from neware_batch import unique_directory, json_write


def failure_folder(manifest, selected_source=None):
    if not manifest: return None
    failed = [e for e in manifest['entries'] if e['status'] == 'error']
    if not failed: return None
    copied = manifest.get('failed_file_copies', {}).get('directory')
    if copied and Path(copied).is_dir(): return Path(copied).resolve()
    ordered = sorted(failed, key=lambda e: e['source'] != selected_source)
    return next((Path(e['source']).resolve().parent for e in ordered
                 if Path(e['source']).parent.is_dir()), None)


def open_failure_folder(parent, manifest, selected_source=None):
    folder = failure_folder(manifest, selected_source)
    if folder is None:
        messagebox.showerror('无法打开', '未找到失败文件所在文件夹，文件夹可能已移动或删除。', parent=parent)
        return
    try: os.startfile(str(folder))
    except OSError as exc: messagebox.showerror('无法打开', str(exc), parent=parent)


def copy_failed_files(manifest):
    failed = [e for e in manifest['entries'] if e['status'] == 'error']
    if not failed: return None
    directory = unique_directory(Path(manifest['run_directory']), '提取失败文件')
    copied, errors = [], []
    used = {'失败清单.json'}
    for entry in failed:
        source = Path(entry['source'])
        name, number = source.name, 1
        while name.casefold() in used:
            number += 1
            name = f'{source.stem}_{number}{source.suffix}'
        used.add(name.casefold())
        destination = directory / name
        try:
            shutil.copyfile(source, destination)
            copied.append({'source': str(source), 'copy': str(destination), 'error': entry.get('error', '')})
        except OSError as exc:
            destination.unlink(missing_ok=True)
            errors.append({'source': str(source), 'error': str(exc)})
    report = {'directory': str(directory), 'copied': copied, 'copy_errors': errors}
    json_write(directory / '失败清单.json', report)
    return report


def offer_failed_files(parent, manifest):
    count = sum(e['status'] == 'error' for e in manifest['entries'])
    if not count or manifest.get('failed_files_prompted'): return None
    manifest['failed_files_prompted'] = True
    if not messagebox.askyesno('集中失败文件',
            f'有 {count} 个文件提取失败。\n是否将副本放到本批结果中的“提取失败文件”文件夹，方便手动处理？\n原文件保留，同名文件自动编号。', parent=parent):
        return None
    try:
        report = copy_failed_files(manifest)
        manifest['failed_file_copies'] = report
        json_write(Path(manifest['run_directory']) / '批次记录.json', manifest)
        if report['copy_errors']:
            messagebox.showwarning('部分文件未能复制',
                f"已复制 {len(report['copied'])} 个，未能复制 {len(report['copy_errors'])} 个。\n详情见：{report['directory']}", parent=parent)
        return f"已复制 {len(report['copied'])} 个失败文件：{report['directory']}"
    except OSError as exc:
        messagebox.showerror('无法集中失败文件', str(exc), parent=parent)
        return None
