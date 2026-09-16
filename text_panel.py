"""Categorized text conversion controls; background workers never access Tk."""
from pathlib import Path
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from text_batch import MERGE_MODES, collect_text_files, run_text_batch, text_source_root, text_identity
from text_extract import validate_ranges
from ui_common import card, inner, file_table, wrap_label


class TextPanel(ttk.Frame):
    def __init__(self, parent, directory, preferences):
        super().__init__(parent, padding=(0, 14, 0, 0))
        self.busy, self.manifest = False, None
        self.events, self.cancel = queue.Queue(), threading.Event()
        self.entries, self.ranges, self.controls = {}, [], []
        self.files, self.dropped_files = [], None
        self.preferences = preferences
        self.columnconfigure(0, weight=1); self.rowconfigure(0, weight=1)
        self.input = tk.StringVar(value='')
        self.output = tk.StringVar(value=preferences.get('text_output'))
        files = card(self); files.grid(row=0, column=0, sticky='nsew')
        files.columnconfigure(0, weight=1); files.rowconfigure(2, weight=1)
        header = inner(files); header.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        ttk.Label(header, text='文本文件', style='Section.TLabel').pack(side='left')
        self.count_text = tk.StringVar(value='0 个文件')
        ttk.Label(header, textvariable=self.count_text, style='CardHint.TLabel').pack(side='left', padx=14)
        self.recursive = tk.BooleanVar(value=True)
        box = ttk.Checkbutton(header, text='包含子文件夹', variable=self.recursive, command=self.scan_folder)
        box.pack(side='right'); self.controls.append(box)
        button = ttk.Button(header, text='清空列表', command=self.clear_files)
        button.pack(side='right', padx=(0, 10)); self.controls.append(button)
        self.remove_button = ttk.Button(header, text='移除选中', command=self.remove_files)
        self.remove_button.pack(side='right', padx=(0, 10)); self.controls.append(self.remove_button)
        row = inner(files); row.grid(row=1, column=0, sticky='ew', pady=(0, 14)); row.columnconfigure(0, weight=1)
        self.input_entry = ttk.Entry(row, textvariable=self.input)
        self.input_entry.grid(row=0, column=0, sticky='ew'); self.controls.append(self.input_entry)
        self.input_entry.bind('<Return>', lambda _: self.scan_folder())
        self.input_entry.bind('<FocusOut>', lambda _: self.scan_folder())
        button = ttk.Button(row, text='选择文件夹', command=lambda: self.choose(self.input))
        button.grid(row=0, column=1, padx=(10, 0)); self.controls.append(button)
        table, self.tree = file_table(files, ('file', 'kind', 'status', 'rows'),
                                      ('文件名称', '类型', '处理状态', '数据行数'), (800, 85, 170, 100), multiple=True)
        table.grid(row=2, column=0, sticky='nsew')
        self.empty_hint = ttk.Label(table, text='拖入文件或文件夹，或点击「选择文件夹」', style='CardHint.TLabel', justify='center')
        self.empty_hint.place(relx=.5, rely=.5, anchor='center')
        self.tree.bind('<<TreeviewSelect>>', self.show_selection)
        self.tree.bind('<Delete>', lambda _: self.remove_files())
        self.detail = tk.StringVar(value='')
        wrap_label(files, self.detail).grid(row=3, column=0, sticky='ew', pady=(10, 0))

        options = card(self); options.grid(row=1, column=0, sticky='ew', pady=(14, 0)); options.columnconfigure(0, weight=1)
        header = inner(options); header.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        ttk.Label(header, text='转换设置', style='Section.TLabel').pack(side='left')
        self.kinds = {}
        for kind in ('EIS', 'CV', '通用'):
            variable = tk.BooleanVar(value=True); self.kinds[kind] = variable
            box = ttk.Checkbutton(header, text=kind, variable=variable)
            box.pack(side='left', padx=(18, 0)); self.controls.append(box)
        self.merge = tk.StringVar(value=MERGE_MODES[1])
        self.merge_box = ttk.Combobox(header, textvariable=self.merge, values=MERGE_MODES, state='readonly', width=18)
        self.merge_box.pack(side='right')
        ttk.Label(header, text='合并方式', style='CardHint.TLabel').pack(side='right', padx=12)
        row = inner(options); row.grid(row=1, column=0, sticky='ew'); row.columnconfigure(1, weight=1)
        ttk.Label(row, text='保存位置', style='CardHint.TLabel').grid(row=0, column=0, padx=(0, 14))
        entry = ttk.Entry(row, textvariable=self.output); entry.grid(row=0, column=1, sticky='ew'); self.controls.append(entry)
        entry.bind('<FocusOut>', lambda _: self.remember_paths())
        entry.bind('<Return>', lambda _: self.remember_paths())
        button = ttk.Button(row, text='选择目录', command=lambda: self.choose(self.output))
        button.grid(row=0, column=2, padx=(10, 0)); self.controls.append(button)
        advanced_row = inner(options); advanced_row.grid(row=2, column=0, sticky='ew', pady=(12, 0))
        self.settings_button = ttk.Button(advanced_row, text='更多设置', command=self.toggle_settings)
        self.settings_button.pack(side='left')
        self.controls.append(self.settings_button)
        self.advanced_window = tk.Toplevel(self)
        self.advanced_window.withdraw()
        self.advanced_window.title('文本转换 · 更多设置')
        self.advanced_window.transient(self.winfo_toplevel())
        self.advanced_window.geometry('860x370')
        self.advanced_window.minsize(760, 360)
        self.advanced_window.protocol('WM_DELETE_WINDOW', self.advanced_window.withdraw)
        self.advanced = inner(self.advanced_window, padding=18); self.advanced.pack(fill='both', expand=True)
        settings = ttk.Notebook(self.advanced, style='Settings.TNotebook'); settings.pack(fill='x')
        eis, cv, generic = [ttk.Frame(settings, padding=12, style="Inner.TFrame") for _ in range(3)]
        for panel, name in zip((eis, cv, generic), ('EIS 阻抗', 'CV 分圈与找峰', '普通表格')): settings.add(panel, text=name)
        self.eis_simple, self.cv_split = tk.BooleanVar(value=False), tk.BooleanVar(value=True)
        box = ttk.Checkbutton(eis, text='仅导出 Z′、−Z″', variable=self.eis_simple)
        box.pack(anchor='w'); self.controls.append(box)
        cv.columnconfigure(0, weight=1)
        box = ttk.Checkbutton(cv, text='按圈并排', variable=self.cv_split)
        box.grid(row=0, column=0, sticky='w'); self.controls.append(box)
        peak = inner(cv); peak.grid(row=1, column=0, sticky='ew', pady=(6, 4))
        self.low, self.high, self.extreme = tk.StringVar(), tk.StringVar(), tk.StringVar(value='最小电流')
        for label, variable in [('下限 V', self.low), ('上限 V', self.high)]:
            ttk.Label(peak, text=label, style='CardHint.TLabel').pack(side='left', padx=(0, 5))
            entry = ttk.Entry(peak, textvariable=variable, width=7)
            entry.pack(side='left', padx=(0, 12)); self.controls.append(entry)
        self.extreme_box = ttk.Combobox(peak, textvariable=self.extreme, values=('最小电流', '最大电流'), state='readonly', width=8)
        self.extreme_box.pack(side='left', padx=(0, 8))
        for label, command in [('添加区间', self.add_range), ('移除选中', self.remove_range)]:
            button = ttk.Button(peak, text=label, command=command)
            button.pack(side='left', padx=4); self.controls.append(button)
        self.range_list = tk.Listbox(cv, height=2, font=('Microsoft YaHei UI', 11), exportselection=False,
                                    relief='flat', borderwidth=0, highlightthickness=0, background='#F3F5F7',
                                    selectbackground='#E8F0FD', selectforeground='#263445')
        self.range_list.grid(row=2, column=0, sticky='ew')
        self.delimiter, self.header = tk.StringVar(value='自动'), tk.StringVar(value='自动')
        self.generic_boxes = []
        for row, (label, variable, values) in enumerate([('分隔符', self.delimiter, ('自动', '逗号', '制表符', '分号', '空白')), ('表头', self.header, ('自动', '首行为表头', '无表头'))]):
            ttk.Label(generic, text=label, style='CardHint.TLabel').grid(row=row, column=0, sticky='w', padx=(0, 12), pady=5)
            box = ttk.Combobox(generic, textvariable=variable, values=values, state='readonly', width=20)
            box.grid(row=row, column=1, sticky='w'); self.generic_boxes.append(box)
        ttk.Button(self.advanced, text='完成设置', command=self.advanced_window.withdraw, style='Primary.TButton').pack(side='bottom', anchor='e', pady=(12, 0))
        self.progress = ttk.Progressbar(self); self.progress.grid(row=2, column=0, sticky='ew', pady=(14, 12))
        bottom = ttk.Frame(self); bottom.grid(row=3, column=0, sticky='ew')
        self.status = tk.StringVar(value='就绪')
        ttk.Label(bottom, textvariable=self.status, style='Hint.TLabel').pack(side='left')
        self.start_button = ttk.Button(bottom, text='开始转换', command=self.start, style='Primary.TButton', width=12)
        self.start_button.pack(side='right', padx=(12, 0))
        self.stop_button = ttk.Button(bottom, text='停止后续文件', command=self.stop, state='disabled')
        self.open_button = ttk.Button(bottom, text='打开结果文件夹', command=self.open_results, state='disabled')
        self.open_button.pack(side='right')
        self.after(100, self.poll)

    def remember_paths(self):
        values = {'text_output': self.output.get()}
        if self.dropped_files is None: values['text_input'] = self.input.get()
        try: self.preferences.remember(**values)
        except (OSError, ValueError) as exc: self.detail.set(f'无法记住文件夹：{exc}')

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
        self.tree.delete(*self.tree.get_children())
        for i, file in enumerate(files):
            self.tree.insert('', 'end', iid=str(i), values=(text_identity(file, base), '待识别', '等待转换', ''), tags=('alternate',) if i % 2 else ())
        self.count_text.set(f'{len(files)} 个文件')
        self.empty_hint.place_forget()
        if not files: self.empty_hint.place(relx=.5, rely=.5, anchor='center')
        self.open_button.configure(state='disabled')
        self.detail.set('' if files else '没有匹配的文本文件')

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
        for control in self.controls + [self.start_button]: control.configure(state='disabled' if value else 'normal')
        for control in self.generic_boxes + [self.merge_box, self.extreme_box]: control.configure(state='disabled' if value else 'readonly')
        self.stop_button.configure(state='normal' if value else 'disabled')
        if value: self.stop_button.pack(side='right', padx=(10, 0), after=self.start_button)
        else: self.stop_button.pack_forget()

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
                elif kind == 'saving': self.status.set('正在保存 Excel…')
                elif kind == 'done':
                    self.manifest = event['manifest']; self.set_busy(False)
                    for item in self.manifest['entries']:
                        self.entries[item['index']] = item
                        if item['status'] == 'success': self.tree.set(str(item['index']), 'status', '完成' if item.get('workbook') else 'Excel 保存失败')
                    for index in range(len(self.manifest['entries']), len(self.tree.get_children())): self.tree.set(str(index), 'status', '未处理')
                    count = len(self.manifest['workbooks'])
                    self.status.set(f'已保存 {count} 个 Excel · 读取失败 {self.manifest["failed"]} 个' + (' · 已停止' if self.manifest['cancelled'] else ''))
                    self.open_button.configure(state='normal')
                    self.detail.set('；'.join(self.manifest['excel_errors']) or self.manifest['run_directory'])
                    first = next((i for i, e in self.entries.items() if e['status'] == 'success'), None)
                    if first is not None: self.tree.selection_set(str(first)); self.show_selection()
                elif kind == 'fatal': self.set_busy(False); self.status.set('转换失败'); self.detail.set(event['error'])
        except queue.Empty: pass
        self.after(100, self.poll)

    def show_selection(self, _event=None):
        selected = self.tree.selection()
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
