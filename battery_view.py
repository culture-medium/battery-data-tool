"""Battery page layout; only files are displayed, data goes directly to Excel."""
import tkinter as tk
from tkinter import ttk

from app_help import QUICK_HELP
from neware_columns import DEFAULT_COLUMNS
from text_panel import TextPanel
from ui_common import configure_style, card, inner, file_table, wrap_label


def build_view(app, root, directory, version, modes):
    configure_style(root)
    width, height = min(1320, root.winfo_screenwidth()-60), min(940, root.winfo_screenheight()-44)
    root.geometry(f'{width}x{height}')
    root.minsize(min(1080, width), min(780, height))
    root.title(f'电池数据处理工具  {version}')
    root.protocol('WM_DELETE_WINDOW', app.close)
    shell = ttk.Frame(root, padding=(24, 20, 24, 18)); shell.pack(fill='both', expand=True)
    app.notebook = ttk.Notebook(shell); app.notebook.pack(fill='both', expand=True)
    page = ttk.Frame(app.notebook, padding=(0, 14, 0, 0)); app.notebook.add(page, text='电池文件提取')
    page.columnconfigure(0, weight=1); page.rowconfigure(0, weight=1)
    app.text_panel = TextPanel(app.notebook, directory, app.preferences); app.notebook.add(app.text_panel, text='TXT 转 Excel')
    help_page = ttk.Frame(app.notebook, padding=(0, 14, 0, 0)); app.notebook.add(help_page, text='使用说明')
    help_card = card(help_page); help_card.pack(fill='both', expand=True)
    help_text = tk.Text(help_card, wrap='word', font=('Microsoft YaHei UI', 11), relief='flat',
                        background='white', foreground='#394B63', padx=16, pady=8, spacing3=6, borderwidth=0)
    help_scroll = ttk.Scrollbar(help_card, command=help_text.yview)
    help_scroll.pack(side='right', fill='y'); help_text.pack(fill='both', expand=True)
    help_text.configure(yscrollcommand=help_scroll.set); help_text.insert('1.0', QUICK_HELP)
    help_text.tag_configure('section', font=('Microsoft YaHei UI', 14, 'bold'), foreground='#203047', spacing1=14, spacing3=10)
    for i, line in enumerate(QUICK_HELP.splitlines(), 1):
        if line.startswith(('一、', '二、', '三、', '四、')): help_text.tag_add('section', f'{i}.0', f'{i}.end')
    help_text.configure(state='disabled')

    files = card(page); files.grid(row=0, column=0, sticky='nsew')
    files.columnconfigure(0, weight=1); files.rowconfigure(1, weight=1)
    toolbar = inner(files); toolbar.grid(row=0, column=0, sticky='ew', pady=(0, 14))
    ttk.Label(toolbar, text='测试文件', style='Section.TLabel').pack(side='left')
    app.count_text = tk.StringVar(value='0 个文件')
    ttk.Label(toolbar, textvariable=app.count_text, style='CardHint.TLabel').pack(side='left', padx=14)
    app.folder_button = ttk.Button(toolbar, text='选择文件夹', command=app.choose_folder)
    app.folder_button.pack(side='right', padx=(10, 0))
    app.edit_buttons = [app.folder_button]
    app.more_button = ttk.Button(toolbar, text='更多操作 ▾', command=app.show_actions)
    app.more_button.pack(side='right')
    app.actions_menu = tk.Menu(app.more_button, tearoff=False, borderwidth=0, activeborderwidth=0,
                               relief='flat', font=('Microsoft YaHei UI', 11))
    for label, command in [('清空列表', app.clear), ('移除选中', app.remove_selected), ('另存所选列', app.export_selected)]:
        app.actions_menu.add_command(label=label, command=command, state='disabled')
    app.land_choice = tk.StringVar(value='auto')
    app.land_menu = tk.Menu(app.actions_menu, tearoff=False, font=('Microsoft YaHei UI', 11))
    for label, mode in [('按文件设置（自动）', 'auto'), ('先充后放（效率＝放 / 充）', 'charge'), ('先放后充（效率＝充 / 放）', 'discharge')]:
        app.land_menu.add_radiobutton(label=label, variable=app.land_choice, value=mode,
                                      command=lambda m=mode: app.set_land_mode(m))
    app.actions_menu.add_cascade(label='蓝电循环口径', menu=app.land_menu, state='disabled')
    app.recursive = tk.BooleanVar(value=True)
    frame, app.tree = file_table(files, ('file', 'status', 'cycles', 'mass'),
                                 ('文件名称', '处理状态', '循环数', '质量 / mg'), (800, 170, 85, 100), multiple=True)
    frame.grid(row=1, column=0, sticky='nsew')
    app.empty_hint = ttk.Label(frame, text='拖入文件或文件夹，或点击「选择文件夹」',
                               style='CardHint.TLabel', justify='center')
    app.empty_hint.place(relx=.5, rely=.5, anchor='center')
    app.tree.bind('<<TreeviewSelect>>', app.show_selection)
    app.detail = tk.StringVar(value='')
    wrap_label(files, app.detail).grid(row=2, column=0, sticky='ew', pady=(10, 0))

    settings = card(page); settings.grid(row=1, column=0, sticky='ew', pady=(14, 0))
    settings.columnconfigure(0, weight=1)
    row = inner(settings); row.grid(row=0, column=0, sticky='ew', pady=(0, 10))
    ttk.Label(row, text='导出设置', style='Section.TLabel').pack(side='left')
    app.field_count = tk.StringVar(value='')
    app.settings_button = ttk.Button(row, text='更多设置', command=app.toggle_settings)
    app.settings_button.pack(side='right')
    fields = inner(settings); fields.grid(row=1, column=0, sticky='ew', pady=(0, 12))
    app.advanced_window = tk.Toplevel(root)
    app.advanced_window.withdraw()
    app.advanced_window.transient(root)
    app.advanced_window.title('电池文件 · 更多设置')
    app.advanced_window.geometry('650x340')
    app.advanced_window.minsize(600, 320)
    app.advanced_window.protocol('WM_DELETE_WINDOW', app.advanced_window.withdraw)
    advanced = inner(app.advanced_window, padding=24); advanced.pack(fill='both', expand=True)
    advanced.columnconfigure(0, weight=1); advanced.columnconfigure(1, weight=1)
    app.field_vars, app.field_buttons = {}, []
    labels = ('循环号', '充电容量 / 比容量', '放电容量 / 比容量', '充放电效率',
              '充电能量', '放电能量', '容量保持率', '能量保持率（蓝电）')
    for i, label in enumerate(labels):
        variable = tk.BooleanVar(value=i in DEFAULT_COLUMNS); app.field_vars[i] = variable
        parent = fields if i < 4 else advanced
        button = ttk.Checkbutton(parent, text=label, variable=variable, command=app.fields_changed)
        button.grid(row=0 if i < 4 else (i-4)//2, column=i if i < 4 else (i-4)%2,
                    sticky='w', padx=(0, 16), pady=3 if i < 4 else 8)
        app.field_buttons.append(button)
    for i in range(4): fields.columnconfigure(i, weight=1, uniform='fields')
    mode_row = inner(advanced); mode_row.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(18, 10))
    ttk.Label(mode_row, text='新威循环统计', style='CardHint.TLabel').pack(side='left', padx=(0, 18))
    app.mode = tk.StringVar(value=next(iter(modes)))
    app.mode_box = ttk.Combobox(mode_row, textvariable=app.mode, values=list(modes), state='readonly', width=14)
    app.mode_box.pack(side='left'); app.mode_box.bind('<<ComboboxSelected>>', lambda _: app.fields_changed())
    app.recursive_box = ttk.Checkbutton(advanced, text='包含子文件夹', variable=app.recursive, command=app.fields_changed)
    app.recursive_box.grid(row=3, column=0, columnspan=2, sticky='w', pady=(4, 14))
    ttk.Button(advanced, text='完成', style='Primary.TButton', command=app.advanced_window.withdraw).grid(row=4, column=1, sticky='e')
    row = inner(settings); row.grid(row=2, column=0, sticky='ew'); row.columnconfigure(1, weight=1)
    ttk.Label(row, text='保存位置', style='CardHint.TLabel').grid(row=0, column=0, padx=(0, 14))
    app.output = tk.StringVar(value=app.preferences.get('battery_output', directory/'提取结果'))
    app.output_entry = ttk.Entry(row, textvariable=app.output); app.output_entry.grid(row=0, column=1, sticky='ew')
    app.output_entry.bind('<FocusOut>', lambda _: app.remember_paths(battery_output=app.output.get()))
    app.output_entry.bind('<Return>', lambda _: app.remember_paths(battery_output=app.output.get()))
    app.browse_button = ttk.Button(row, text='选择目录', command=app.choose_output); app.browse_button.grid(row=0, column=2, padx=(10, 0))
    app.progress = ttk.Progressbar(page); app.progress.grid(row=2, column=0, sticky='ew', pady=(14, 12))
    bottom = ttk.Frame(page); bottom.grid(row=3, column=0, sticky='ew')
    app.status = tk.StringVar(value='就绪')
    ttk.Label(bottom, textvariable=app.status, style='Hint.TLabel').pack(side='left')
    app.start_button = ttk.Button(bottom, text='开始提取', command=app.start, style='Primary.TButton', width=12)
    app.start_button.pack(side='right', padx=(12, 0))
    app.stop_button = ttk.Button(bottom, text='停止后续文件', command=app.stop, state='disabled')
    app.open_button = ttk.Button(bottom, text='打开 Excel', command=app.open_results, state='disabled'); app.open_button.pack(side='right')
