"""Categorized text conversion controls; background workers never access Tk."""
from pathlib import Path
import os
import queue
import threading
import tkinter as tk
from batch_statistics import file_statistics, rate_text, summary_text
from failed_files import offer_failed_files, open_failure_folder
from tkinter import ttk, filedialog, messagebox

from text_batch import MERGE_MODES, collect_text_files, run_text_batch, text_source_root, text_identity
from text_extract import validate_ranges
from ui_common import card, inner, file_table, wrap_label


class TextPanel(ttk.Frame):
    def __init__(self, parent, directory, preferences):
        super().__init__(parent)
        self.busy, self.manifest = False, None
        self.events, self.cancel = queue.Queue(), threading.Event()
        self.entries, self.ranges, self.controls = {}, [], []
        self.files, self.dropped_files = [], None
        self.preferences = preferences
        self.input = tk.StringVar(value='')
        self.output = tk.StringVar(value=preferences.get('text_output'))
        self.recursive = tk.BooleanVar(value=True)
        from text_view import build_text_view
        build_text_view(self)
        self.after(100, self.poll)

    def remember_paths(self):
        values = {'text_output': self.output.get()}
        if self.dropped_files is None: values['text_input'] = self.input.get()
        try: self.preferences.remember(**values)
        except (OSError, ValueError) as exc: self.detail.set(f'无法记住文件夹：{exc}')

    def choose_files(self):
        if self.busy: return
        files = filedialog.askopenfilenames(parent=self, title='添加文本文件',
            initialdir=self.preferences.initial_directory('text_input'),
            filetypes=[('文本数据', '*.txt *.csv *.tsv')])
        if files: self.add_paths(files)

    def show_actions(self):
        self.actions_menu.entryconfigure('清空列表',state='normal' if self.files and not self.busy else 'disabled')
        try: self.actions_menu.tk_popup(self.more_button.winfo_rootx(),self.more_button.winfo_rooty()+self.more_button.winfo_height())
        finally: self.actions_menu.grab_release()

    def toggle_settings(self):
        if self.advanced_window.state() == 'normal':
            self.advanced_window.withdraw()
        else:
            self.advanced_window.deiconify()
            self.advanced_window.lift()

    def scan_folder(self):
        if self.busy: return
        folder = self.input.get().strip()
        if self.dropped_files is not None and folder == self._drop_display: return
        if not folder: return
        key = (folder, self.recursive.get())
        if getattr(self, '_scanned', None) == key: return
        try:
            files = collect_text_files(folder, self.recursive.get())
        except (ValueError, OSError) as exc:
            self.detail.set(str(exc)); return
        self._scanned = key
        self.dropped_files = None
        self.populate_files(files, Path(folder).resolve())
        self.remember_paths()

    def populate_files(self, files, base):
        self.files = files
        self.entries, self.manifest = {}, None
        self.failed_folder_button.configure(state='disabled')
        self.remove_button.configure(state='disabled')
        self.tree.delete(*self.tree.get_children())
        for i, file in enumerate(files):
            self.tree.insert('', 'end', iid=str(i), values=(text_identity(file, base), '待识别', '等待转换', ''), tags=('alternate',) if i % 2 else ())
        self.count_text.set(f'{len(files)} 个文件')
        self.empty_hint.place_forget()
        if not files: self.empty_hint.place(relx=.5, rely=.5, anchor='center')
        self.open_button.configure(state='disabled')
        self.detail.set('' if files else '没有匹配的文本文件')
        self.status.set(f'共 {len(files)} 个文件 · 提取成功率 —')

    def add_paths(self, paths):
        if self.busy: return
        files = collect_text_files(self.files + list(paths), self.recursive.get())
        self.set_file_selection(files)

    def set_file_selection(self, files):
        self.dropped_files = files
        self._drop_display = f'已添加 {len(files)} 个文件，可继续拖入'
        self.input.set(self._drop_display)
        self.populate_files(files, text_source_root(files, files))

    def remove_files(self):
        if self.busy: return
        selected = {int(i) for i in self.tree.selection()}
        if not selected: return
        remaining = [p for i, p in enumerate(self.files) if i not in selected]
        if remaining: self.set_file_selection(remaining)
        else: self.clear_files()

    def clear_files(self):
        if self.busy: return
        self.dropped_files, self._scanned = None, None
        self.input.set('')
        self.populate_files([], None)
        self.remember_paths()

    def choose(self, variable):
        key = 'text_input' if variable is self.input else 'text_output'
        value = filedialog.askdirectory(parent=self, title='选择文件夹', initialdir=self.preferences.initial_directory(key, variable.get()))
        if value:
            variable.set(value)
            if variable is self.input:
                self.dropped_files = None
                self._scanned = None
                self.scan_folder()
            else: self.remember_paths()

    def add_range(self):
        try:
            mode = {'最小电流': 'min', '最大电流': 'max'}[self.extreme.get()]
            item = validate_ranges([(self.low.get(), self.high.get(), mode)])[0]
            if item not in self.ranges:
                self.ranges.append(item); self.range_list.insert('end', f'{item[0]:g} ～ {item[1]:g} V    {self.extreme.get()}')
        except ValueError:
            messagebox.showerror('区间无效', '请填写有效数字，下限不能大于上限。', parent=self)

    def remove_range(self):
        for index in reversed(self.range_list.curselection()): self.ranges.pop(index); self.range_list.delete(index)

    def options(self):
        return {'recursive': self.recursive.get(), 'kinds': [k for k, v in self.kinds.items() if v.get()],
                'merge': self.merge.get(), 'eis_simple': self.eis_simple.get(), 'cv_split': self.cv_split.get(),
                'delimiter': self.delimiter.get(), 'header': self.header.get(), 'peak_ranges': list(self.ranges)}

    def set_busy(self, value):
        self.busy = value
        has_failed = self.manifest and any(e['status'] == 'error' for e in self.manifest['entries'])
        self.failed_folder_button.configure(state='normal' if has_failed and not value else 'disabled')
        for control in self.controls + [self.start_button]: control.configure(state='disabled' if value else 'normal')
        for control in self.generic_boxes + [self.merge_box, self.extreme_box]: control.configure(state='disabled' if value else 'readonly')
        self.stop_button.configure(state='normal' if value else 'disabled')
        self.remove_button.configure(state='normal' if self.tree.selection() and not value else 'disabled')
        if value:
            self.start_button.configure(text='正在转换…')
            self.stop_button.pack(fill='x', pady=(10, 0), after=self.start_button)
        else:
            self.stop_button.pack_forget()
            self.start_button.configure(text='▶  开始转换')

    def start(self):
        if self.busy: return
        try:
            folder, output, options = self.input.get().strip(), self.output.get().strip(), self.options()
            if self.dropped_files is not None and folder == self._drop_display: folder = list(self.dropped_files)
            if not folder: raise ValueError('请选择输入文件夹或拖入文件。')
            files = collect_text_files(folder, options['recursive'])
            if not files: raise ValueError('没有找到 TXT、CSV 或 TSV 文件。')
            if not options['kinds']: raise ValueError('请至少选择一种文本类型。')
        except (ValueError, OSError) as exc:
            messagebox.showerror('无法开始', str(exc), parent=self); return
        if not output:
            self.choose(self.output)
            output = self.output.get().strip()
            if not output:
                self.status.set('未选择保存位置，文件列表保留。')
                return
        self.remember_paths()
        self.files = files
        self.tree.delete(*self.tree.get_children()); self.empty_hint.place_forget()
        self.count_text.set(f"{len(files)} 个文件")
        self.entries, self.manifest, self.run_options = {}, None, options
        base = text_source_root(folder, files)
        for index, file in enumerate(files): self.tree.insert('', 'end', iid=str(index), values=(text_identity(file, base), '', '等待转换', ''), tags=('alternate',) if index % 2 else ())
        self.cancel.clear(); self.set_busy(True); self.open_button.configure(state='disabled')
        self.advanced_window.withdraw()
        self.progress.configure(maximum=len(files), value=0)
        self.status.set('正在转换…')
        def work():
            try: run_text_batch(folder, output, options, cancel=self.cancel, on_event=self.events.put)
            except Exception as exc: self.events.put({'type': 'fatal', 'error': str(exc)})
        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        self.cancel.set(); self.stop_button.configure(state='disabled'); self.status.set('当前文件结束后保存已完成的结果。')

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait(); kind = event['type']
                if kind == 'reading': self.tree.set(str(event['index']), 'status', '正在读取…')
                elif kind == 'file_done':
                    index = event['index']; self.entries[index] = event
                    status = {'success': '已读取，等待保存', 'error': '读取失败', 'filtered': '未勾选此类型'}[event['status']]
                    self.tree.item(str(index), values=(event['identity'], event.get('kind', ''), status, event.get('rows', '')))
                    self.progress.configure(value=index+1)
                    self.status.set(f'已处理 {len(self.entries)} / {len(self.files)} · 提取成功率 {rate_text(file_statistics(self.entries.values()))}')
                elif kind == 'saving': self.status.set('正在保存 Excel…')
                elif kind == 'done':
                    self.manifest = event['manifest']; self.set_busy(False)
                    for item in self.manifest['entries']:
                        self.entries[item['index']] = item
                        if item['status'] == 'success': self.tree.set(str(item['index']), 'status', '完成' if item.get('workbook') else 'Excel 保存失败')
                    for index in range(len(self.manifest['entries']), len(self.tree.get_children())): self.tree.set(str(index), 'status', '未处理')
                    count = len(self.manifest['workbooks'])
                    self.status.set(summary_text(self.manifest['statistics'], stopped=self.manifest['cancelled'], skipped=self.manifest['unprocessed']))
                    self.open_button.configure(state='normal')
                    self.detail.set('；'.join(self.manifest['excel_errors']) or self.manifest['run_directory'])
                    first = next((i for i, e in self.entries.items() if e['status'] == 'success'), None)
                    if first is not None: self.tree.selection_set(str(first)); self.show_selection()
                    copied = offer_failed_files(self, self.manifest)
                    if copied: self.detail.set(copied)
                elif kind == 'fatal': self.set_busy(False); self.status.set('转换失败'); self.detail.set(event['error'])
        except queue.Empty: pass
        self.after(100, self.poll)

    def show_selection(self, _event=None):
        selected = self.tree.selection()
        self.remove_button.configure(state='normal' if selected and not self.busy else 'disabled')
        if not selected: return
        item = self.entries.get(int(selected[0]))
        if not item: return
        if item['status'] != 'success':
            self.detail.set(item.get('error', '此类型未勾选。')); return
        if self.manifest and self.manifest['excel_errors']:
            self.detail.set('；'.join(self.manifest['excel_errors'])); return
        location = item.get('workbook', '正在保存 Excel…')
        self.detail.set(f"{item['rows']:,} 条数据 · {location}")

    def open_results(self):
        if self.manifest:
            try: os.startfile(self.manifest['run_directory'])
            except OSError as exc: messagebox.showerror('无法打开', str(exc), parent=self)

    def open_failed_folder(self):
        if self.busy: return
        selected = self.tree.selection()
        entry = self.entries.get(int(selected[0])) if selected else None
        open_failure_folder(self, self.manifest, entry.get('source') if entry else None)
