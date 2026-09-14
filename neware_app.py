"""Windows desktop entry point. All extraction runs locally without a model."""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from neware_batch import DEFAULT_COLUMNS, collect_files, json_write, run_batch
from neware_excel import export_workbook
from neware_extract import EXTRACTOR_VERSION
from battery_view import build_view
from app_preferences import Preferences
from file_drop import register_drop


CYCLE_MODES = {"自动": "auto", "放电优先": "discharge", "充电优先": "charge"}


def app_directory() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


class ExtractorApp:
    def __init__(self, root: tk.Tk, *, settings_path=None):
        self.root = root
        self.files: list[Path] = []
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.last_manifest = None
        self.last_error = None
        self.last_directory = None
        self.last_workbook = None
        self.entries = {}
        self.land_modes: dict[str, str] = {}
        self.preferences = Preferences(settings_path or app_directory() / '设置.json')
        build_view(self, root, app_directory(), EXTRACTOR_VERSION, CYCLE_MODES)
        self.dnd_enabled = register_drop(self)
        root.after_idle(self.restore_folder)
        root.after(100, self.poll)

    def current_columns(self):
        return tuple(i for i, variable in self.field_vars.items() if variable.get())

    def fields_changed(self):
        columns = self.current_columns()
        self.field_count.set(f"已选 {len(columns)} 项" if columns else "请至少勾选一项字段。")
        has_results = self.last_manifest and self.last_manifest["success"] > 0
        self.actions_menu.entryconfigure('另存所选列', state="normal" if has_results and columns and not self.busy else "disabled")
        extra = sum(self.field_vars[i].get() for i in range(4, 8))
        custom = self.mode.get() != '自动' or not self.recursive.get()
        self.settings_button.configure(text=f'更多设置（+{extra}项）' if extra else '更多设置 · 自定义' if custom else '更多设置')
        self.update_actions()
        if hasattr(self, "start_button") and not self.busy:
            self.start_button.configure(state="normal" if columns else "disabled")

    def update_actions(self):
        self.actions_menu.entryconfigure('清空列表', state='normal' if self.files and not self.busy else 'disabled')
        self.actions_menu.entryconfigure('移除选中', state='normal' if self.tree.selection() and not self.busy else 'disabled')
        selected_land = [self.files[int(i)] for i in self.tree.selection() if self.files[int(i)].suffix.lower() == '.cex']
        self.actions_menu.entryconfigure('蓝电循环口径', state='normal' if selected_land and not self.busy else 'disabled')
        choices = {self.land_modes.get(str(p), 'auto') for p in selected_land}
        self.land_choice.set(choices.pop() if len(choices) == 1 else '')

    def set_land_mode(self, mode):
        if self.busy: return
        selected = self.tree.selection()
        changed = 0
        for iid in selected:
            path = self.files[int(iid)]
            if path.suffix.lower() == '.cex':
                self.land_modes[str(path)] = mode
                changed += 1
        if changed:
            # A changed policy requires extraction again, never reuse old rows.
            self.refresh()
            self.tree.selection_set(selected)
            self.detail.set(f'已设置 {changed} 个蓝电文件的循环口径，点击开始提取生效。')

    def show_actions(self):
        self.update_actions()
        try:
            self.actions_menu.tk_popup(self.more_button.winfo_rootx(), self.more_button.winfo_rooty()+self.more_button.winfo_height())
        finally:
            self.actions_menu.grab_release()

    def toggle_settings(self):
        if self.busy: return
        if self.advanced_window.state() == 'normal': self.advanced_window.withdraw()
        else:
            self.advanced_window.deiconify()
            self.advanced_window.lift()

    def remember_paths(self, **values):
        try: self.preferences.remember(**values)
        except (OSError, ValueError) as exc: self.detail.set(f'无法记住文件夹：{exc}')

    def restore_folder(self):
        folder = self.preferences.get('battery_input')
        if self.files or not folder: return
        try:
            if Path(folder).is_dir(): self.add_paths([folder])
        except OSError as exc:
            self.detail.set(f'无法读取上次的文件夹：{exc}')

    def export_selected(self):
        if not self.last_manifest or not self.last_manifest["success"] or not self.current_columns() or self.busy:
            return
        target = filedialog.asksaveasfilename(parent=self.root, title="另存本批所有已完成文件（当前勾选列）",
            initialdir=str(self.last_directory), initialfile="循环数据_所选列.xlsx",
            defaultextension=".xlsx", filetypes=[("Excel 工作簿", "*.xlsx")])
        if not target:
            return
        try:
            self.save_workbook(Path(target))
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)

    def save_workbook(self, path):
        mappings = export_workbook(self.last_manifest["entries"], path, self.current_columns())
        self.last_workbook = Path(path)
        self.open_button.configure(state="normal")
        self.detail.set(f"已保存 {len(mappings)} 个工作表：{path}")
        return mappings

    def add_paths(self, paths):
        if self.busy:
            return
        self.files = collect_files(self.files + [Path(p) for p in paths], self.recursive.get())
        self.refresh()

    def refresh(self):
        self.last_manifest = None
        self.last_workbook = None
        self.open_button.configure(state='disabled')
        self.tree.delete(*self.tree.get_children())
        self.entries.clear()
        current_paths = {str(p) for p in self.files}
        self.land_modes = {p: mode for p, mode in self.land_modes.items() if p in current_paths}
        self.fields_changed()
        self.empty_hint.place_forget()
        if not self.files: self.empty_hint.place(relx=.5, rely=.5, anchor="center")
        for i, path in enumerate(self.files):
            mode = self.land_modes.get(str(path), 'auto')
            status = '等待 · ' + ('先充后放' if mode == 'charge' else '先放后充') if mode != 'auto' else '等待提取'
            self.tree.insert("", "end", iid=str(i), values=(path.name, status, "", ""), tags=("alternate",) if i % 2 else ())
        self.count_text.set(f"{len(self.files)} 个文件")
        self.detail.set('')

    def choose_folder(self):
        selected = filedialog.askdirectory(parent=self.root, title="选择包含 NDAX / CEX 的文件夹",
                                          initialdir=self.preferences.initial_directory('battery_input', app_directory()))
        if selected:
            try:
                self.add_paths([selected])
                self.remember_paths(battery_input=selected)
            except OSError as exc:
                messagebox.showerror("无法读取文件夹", str(exc), parent=self.root)

    def remove_selected(self):
        if self.busy: return
        remove = {int(i) for i in self.tree.selection()}
        self.files = [p for i, p in enumerate(self.files) if i not in remove]
        self.refresh()

    def clear(self):
        if self.busy: return
        self.files.clear()
        self.refresh()

    def choose_output(self):
        selected = filedialog.askdirectory(parent=self.root, title="选择结果保存目录", initialdir=self.output.get())
        if selected:
            self.output.set(selected)
            self.remember_paths(battery_output=selected)

    def set_busy(self, value):
        self.busy = value
        for button in self.edit_buttons + self.field_buttons + [self.browse_button, self.start_button, self.recursive_box, self.output_entry, self.settings_button, self.more_button]:
            button.configure(state="disabled" if value else "normal")
        self.mode_box.configure(state="disabled" if value else "readonly")
        self.stop_button.configure(state="normal" if value else "disabled")
        if value:
            self.advanced_window.withdraw()
            self.stop_button.pack(side='right', padx=(10, 0), after=self.start_button)
        else: self.stop_button.pack_forget()
        self.fields_changed()

    def start(self):
        if self.busy:
            return
        if not self.current_columns():
            messagebox.showinfo("选择字段", "请至少勾选一项提取字段。", parent=self.root)
            return
        if not self.files:
            messagebox.showinfo("添加测试文件", "请先选择包含 NDAX 或 CEX 的文件夹。", parent=self.root)
            return
        output = self.output.get().strip()
        if not output:
            messagebox.showinfo("选择保存目录", "请指定提取结果的保存目录。", parent=self.root)
            return
        self.remember_paths(battery_output=output)
        self.refresh()
        self.cancel.clear()
        self.last_manifest, self.last_error = None, None
        self.last_directory = None
        self.last_workbook = None
        self.open_button.configure(state="disabled")
        self.progress.configure(maximum=len(self.files), value=0)
        self.set_busy(True)
        self.status.set("正在读取…")
        files, mode, columns = list(self.files), CYCLE_MODES[self.mode.get()], self.current_columns()
        land_modes = {str(p): self.land_modes.get(str(p), 'auto') for p in files if p.suffix.lower() == '.cex'}

        def work():
            try:
                run_batch(files, Path(output), cycle_mode=mode, land_modes=land_modes,
                          columns=columns, cancel=self.cancel, on_event=self.events.put)
            except Exception as exc:
                self.events.put({"type": "fatal", "error": f"{type(exc).__name__}: {exc}"})
        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        self.cancel.set()
        self.stop_button.configure(state="disabled")
        self.status.set("当前文件完成后停止，已提取结果会保留。")

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event["type"]
                if kind == "batch_started":
                    self.last_directory = Path(event["directory"])
                elif kind == "file_started":
                    iid = str(event["index"])
                    self.tree.set(iid, "status", "正在提取…")
                    self.tree.see(iid)
                elif kind == "file_done":
                    i = event["index"]
                    self.entries[i] = event
                    if event["status"] == "success":
                        one_way = event["single_direction_cycles"]
                        status = f"完成 · {len(one_way)} 圈单向" if one_way else "完成"
                        missing_mass = event['mass_mg'] is None
                        if missing_mass: status = '完成 · 容量 mAh'
                        mass = '未填写' if missing_mass else f"{event['mass_mg']:.6g}"
                        self.tree.item(str(i), values=(self.files[i].name, status, event["cycles"], mass), tags=("warning" if one_way or missing_mass else "success",) + (("alternate",) if i % 2 else ()))
                        if not self.tree.selection():
                            self.tree.selection_set(str(i))
                            self.tree.focus(str(i))
                        if str(i) in self.tree.selection():
                            self.show_selection()
                    else:
                        self.tree.set(str(i), "status", "需确认口径" if event.get('error_code') == 'statistics_choice_required' else "提取失败")
                        self.tree.item(str(i), tags=("error",))
                    self.progress.configure(value=len(self.entries))
                    self.status.set(f"已处理 {len(self.entries)} / {len(self.files)} 个文件")
                elif kind == "workbook_started":
                    self.status.set("正在将已完成文件合并到 Excel…")
                elif kind == "batch_done":
                    self.last_manifest = event["manifest"]
                    manifest = self.last_manifest
                    self.entries = {entry["index"]: entry for entry in manifest["entries"]}
                    self.last_workbook = Path(manifest["workbook"]) if manifest["workbook"] else None
                    self.open_button.configure(state="normal" if self.last_workbook else "disabled")
                    self.set_busy(False)
                    self.status.set(f"{'已停止' if manifest['cancelled'] else '处理完成'} · 成功 {manifest['success']}，失败 {manifest['failed']}，未处理 {manifest['skipped']}")
                    self.show_selection()
                    if manifest["excel_error"]:
                        self.last_error = manifest["excel_error"]
                        self.status.set("提取完成，但 Excel 保存失败")
                        self.detail.set(manifest["excel_error"] + "；可点击“另存所选列”重试。")
                    for i in range(len(manifest["entries"]), len(self.files)):
                        self.tree.set(str(i), "status", "未处理")
                elif kind == "fatal":
                    self.last_error = event["error"]
                    self.set_busy(False)
                    self.status.set("处理停止")
                    self.detail.set(event["error"])
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def show_selection(self, _event=None):
        self.update_actions()
        selected = self.tree.selection()
        if not selected:
            return
        i = int(selected[0])
        entry = self.entries.get(i)
        if entry and entry["status"] == "error":
            self.detail.set(entry["error"])
        elif entry:
            count = len(entry['single_direction_cycles'])
            suffix = f" · 含 {count} 圈单向记录，详见提取说明" if count else ""
            if entry.get('capacity_basis') == 'absolute': suffix += ' · 无活性质量，容量单位 mAh'
            if entry.get('statistics_policy'):
                suffix += ' · ' + ('先充后放' if entry['statistics_policy']['mode'] == 'charge' else '先放后充')
            self.detail.set(f"样品：{entry['sample_name']} · {entry['cycles']} 圈{suffix}")
        else:
            self.detail.set(str(self.files[i]))

    def open_path(self, path: Path):
        try:
            os.startfile(str(path))
        except OSError as exc:
            messagebox.showerror("无法打开", str(exc), parent=self.root)

    def open_results(self):
        if self.last_workbook:
            self.open_path(self.last_workbook)

    def close(self):
        if self.busy or self.text_panel.busy:
            self.detail.set("请先停止后续文件，等待当前文件完成后再关闭。")
            self.text_panel.detail.set("请先停止后续文件，等待当前文件完成后再关闭。")
            return
        self.remember_paths(battery_output=self.output.get())
        self.text_panel.remember_paths()
        self.root.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="电池数据处理工具")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--batch", nargs="+", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--cycle-mode", choices=["auto", "charge", "discharge"], default="auto")
    parser.add_argument("--all-columns", action="store_true", help="输出该文件支持的全部字段")
    parser.add_argument("--text-folder", type=Path)
    parser.add_argument("--gui-smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.batch and not args.gui_smoke_test:
        if args.out is None: parser.error("--batch 需要 --out")
        manifest = run_batch(collect_files(args.batch), args.out, cycle_mode=args.cycle_mode,
                             columns=tuple(range(8)) if args.all_columns else None)
        if sys.stdout is not None: print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0 if manifest["failed"] == 0 and not manifest["excel_error"] else 2
    if args.text_folder and not args.gui_smoke_test:
        from text_batch import run_text_batch
        if args.out is None: parser.error("--text-folder 需要 --out")
        manifest = run_text_batch(args.text_folder, args.out)
        if sys.stdout is not None: print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0 if manifest['failed'] == 0 and not manifest['excel_errors'] else 2
    from tkinterdnd2 import TkinterDnD
    root = TkinterDnD.Tk()
    if args.gui_smoke_test: root.withdraw()
    app = ExtractorApp(root, settings_path=(args.out / '设置.json') if args.gui_smoke_test and args.out else None)
    if args.all_columns:
        for variable in app.field_vars.values(): variable.set(True)
        app.fields_changed()
    if args.out: app.output.set(str(args.out))
    if args.files: app.add_paths(args.files)
    if args.gui_smoke_test:
        from app_selftest import run_selftest
        try:
            return run_selftest(app, args)
        except Exception:
            import traceback
            if args.out:
                args.out.mkdir(parents=True, exist_ok=True)
                (args.out / 'gui_error.txt').write_text(traceback.format_exc(), encoding='utf-8')
            return 3
        finally:
            root.destroy()
    root.mainloop()
    return 0


if __name__ == "__main__":
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
