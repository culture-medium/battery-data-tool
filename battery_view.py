"""Reference-inspired sidebar, wide file list and pinned export controls."""
import tkinter as tk
from tkinter import ttk

from app_help import QUICK_HELP
from neware_columns import DEFAULT_COLUMNS
from text_panel import TextPanel
from ui_common import (BG, BLUE, WHITE, configure_style, card, inner, file_table,
                       wrap_label, icon, SettingsPanel, separator, summary_bar, responsive_drop)


def build_view(app, root, directory, version, modes):
    configure_style(root)
    width,height=min(1580,root.winfo_screenwidth()-40),min(950,root.winfo_screenheight()-90)
    root.geometry(f'{width}x{height}'); root.minsize(min(1180,width),min(720,height))
    root.title(f'电池数据处理工具  {version}'); root.protocol('WM_DELETE_WINDOW',app.close)
    shell=ttk.Frame(root,padding=(16,10,16,16)); shell.pack(fill='both',expand=True)
    shell.rowconfigure(1,weight=1); shell.columnconfigure(1,weight=1)
    brand=ttk.Frame(shell); brand.grid(row=0,column=0,columnspan=2,sticky='ew',pady=(0,18))
    tk.Label(brand,image=icon(root,'bolt',WHITE,28),background=BLUE,padx=5,pady=4).pack(side='left')
    ttk.Label(brand,text='电池数据处理工具',style='Brand.TLabel').pack(side='left',padx=12)
    sidebar=ttk.Frame(shell,width=194); sidebar.grid(row=1,column=0,sticky='ns',padx=(0,16)); sidebar.grid_propagate(False)
    sidebar.columnconfigure(0,weight=1); sidebar.rowconfigure(3,weight=1)
    app.notebook=ttk.Notebook(shell,style='Sidebar.TNotebook'); app.notebook.grid(row=1,column=1,sticky='nsew')
    page=ttk.Frame(app.notebook); page.columnconfigure(0,weight=1); page.rowconfigure(0,weight=1)
    app.notebook.add(page,text='电池文件提取')
    app.text_panel=TextPanel(app.notebook,directory,app.preferences); app.notebook.add(app.text_panel,text='TXT 转 Excel')
    help_page=ttk.Frame(app.notebook); app.notebook.add(help_page,text='使用说明')
    help_card=card(help_page); help_card.pack(fill='both',expand=True)
    ttk.Label(help_card,text='使用说明',style='Title.TLabel').pack(anchor='w',pady=(0,20))
    help_body=inner(help_card); help_body.pack(fill='both',expand=True)
    help_text=tk.Text(help_body,wrap='word',font=('Microsoft YaHei UI',12),relief='flat',background=WHITE,
        foreground='#3B506E',padx=4,pady=8,spacing3=9,borderwidth=0,highlightthickness=0)
    help_scroll=ttk.Scrollbar(help_body,command=help_text.yview)
    help_scroll.pack(side='right',fill='y'); help_text.pack(fill='both',expand=True)
    help_text.configure(yscrollcommand=help_scroll.set); help_text.insert('1.0',QUICK_HELP)
    help_text.tag_configure('section',font=('Microsoft YaHei UI',16,'bold'),foreground='#132344',spacing1=18,spacing3=12)
    for i,line in enumerate(QUICK_HELP.splitlines(),1):
        if line in ('电池文件','TXT 转 Excel','说明'): help_text.tag_add('section',f'{i}.0',f'{i}.end')
    help_text.configure(state='disabled')
    app.nav_buttons=[]
    for i,(name,shape) in enumerate((('电池文件提取','folder'),('TXT 转 Excel','file'),('使用说明','help'))):
        button=ttk.Button(sidebar,text='  '+name,image=icon(root,shape,'#536A8A',24),compound='left',
            command=lambda index=i: app.notebook.select(index),style='Nav.TButton')
        button.grid(row=i,column=0,sticky='ew',pady=(0,12)); app.nav_buttons.append(button)
    ttk.Label(sidebar,text='◉  本地运行',style='Hint.TLabel').grid(row=4,column=0,sticky='w',padx=16,pady=16)
    def sync_nav(_=None):
        current=app.notebook.index('current')
        for i,button in enumerate(app.nav_buttons):
            button.configure(style='NavActive.TButton' if i==current else 'Nav.TButton')
    app.notebook.bind('<<NotebookTabChanged>>',sync_nav); root.after_idle(sync_nav)

    files=card(page); files.grid(row=0,column=0,sticky='nsew',padx=(0,12))
    files.columnconfigure(0,weight=1); files.rowconfigure(3,weight=1)
    ttk.Label(files,text='电池文件提取',style='Title.TLabel').grid(row=0,column=0,sticky='w',pady=(0,20))
    drop=ttk.Frame(files,style='Soft.TFrame',padding=(18,18)); drop.grid(row=1,column=0,sticky='ew',pady=(0,22))
    drop.columnconfigure(1,weight=1); app.drop_zone=drop
    ttk.Label(drop,image=icon(root,'folder',size=36),style='Soft.TLabel').grid(row=0,column=0,rowspan=2,padx=(0,16))
    ttk.Label(drop,text='拖入文件或文件夹',style='SoftTitle.TLabel').grid(row=0,column=1,sticky='w')
    subtitle=ttk.Label(drop,text='支持新威 NDAX、蓝电 CEX，自动识别',style='SoftHint.TLabel',wraplength=330)
    subtitle.grid(row=1,column=1,sticky='w',pady=(6,0))
    buttons=ttk.Frame(drop,style='Soft.TFrame'); buttons.grid(row=0,column=2,rowspan=2,padx=(12,0))
    app.folder_button=ttk.Button(buttons,text='选择文件夹',image=icon(root,'folder',size=19),compound='left',command=app.choose_folder)
    app.folder_button.pack(side='left',padx=(0,8))
    app.add_button=ttk.Button(buttons,text='添加文件',image=icon(root,'add',WHITE,19),compound='left',command=app.choose_files,style='Primary.TButton')
    app.add_button.pack(side='left'); app.edit_buttons=[app.folder_button,app.add_button]
    responsive_drop(drop,buttons,subtitle)
    toolbar=inner(files); toolbar.grid(row=2,column=0,sticky='ew',pady=(0,10))
    ttk.Label(toolbar,text='文件列表',style='Section.TLabel').pack(side='left')
    app.count_text=tk.StringVar(value='0 个文件'); ttk.Label(toolbar,textvariable=app.count_text,style='CardHint.TLabel').pack(side='left',padx=12)
    app.more_button=ttk.Button(toolbar,text='更多操作 ▾',command=app.show_actions); app.more_button.pack(side='right')
    app.remove_button=ttk.Button(toolbar,text='移除选中',image=icon(root,'trash','#70839E',18),compound='left',command=app.remove_selected,state='disabled')
    app.remove_button.pack(side='right',padx=(0,10)); app.edit_buttons.append(app.remove_button)
    app.actions_menu=tk.Menu(app.more_button,tearoff=False,borderwidth=0,activeborderwidth=0,relief='flat',font=('Microsoft YaHei UI',11))
    for label,command in [('清空列表',app.clear),('移除选中',app.remove_selected),('另存所选列',app.export_selected)]:
        app.actions_menu.add_command(label=label,command=command,state='disabled')
    app.land_choice=tk.StringVar(value='auto')
    app.land_menu=tk.Menu(app.actions_menu,tearoff=False,font=('Microsoft YaHei UI',11))
    for label,mode in [('按文件设置（自动）','auto'),('先充后放（效率＝放 / 充）','charge'),('先放后充（效率＝充 / 放）','discharge')]:
        app.land_menu.add_radiobutton(label=label,variable=app.land_choice,value=mode,command=lambda m=mode: app.set_land_mode(m))
    app.actions_menu.add_cascade(label='蓝电循环口径',menu=app.land_menu,state='disabled')
    app.recursive=tk.BooleanVar(value=True)
    table,app.tree=file_table(files,('file','kind','status','cycles','mass'),('文件名称','类型','处理状态','循环数','质量 / mg'),(360,64,155,70,90),multiple=True)
    table.grid(row=3,column=0,sticky='nsew')
    app.empty_hint=ttk.Label(table,text='还没有文件\n从上方添加，或直接拖入',style='CardHint.TLabel',justify='center')
    app.empty_hint.place(relx=.5,rely=.5,anchor='center')
    app.tree.bind('<<TreeviewSelect>>',app.show_selection); app.tree.bind('<Delete>',lambda _: app.remove_selected())
    app.progress=ttk.Progressbar(files); app.progress.grid(row=4,column=0,sticky='ew',pady=(10,0))
    app.detail=tk.StringVar(value=''); wrap_label(files,app.detail).grid(row=5,column=0,sticky='ew',pady=(8,0))
    summary_bar(files,app,6)

    settings=SettingsPanel(page,'导出设置'); settings.grid(row=0,column=1,sticky='nsew')
    app.settings_panel=settings; body=settings.content
    ttk.Label(body,text='导出字段',style='Section.TLabel').grid(row=0,column=0,sticky='w',pady=(0,10))
    fields=inner(body); fields.grid(row=1,column=0,sticky='ew')
    app.field_count=tk.StringVar(value='')
    extras=inner(body); extras.grid(row=3,column=0,sticky='ew'); extras.grid_remove()
    app.extra_fields=extras; app.extra_fields_open=False
    def toggle_fields():
        app.extra_fields_open=not app.extra_fields_open
        if app.extra_fields_open: extras.grid()
        else: extras.grid_remove()
        app.metrics_button.configure(text='收起指标 ▴' if app.extra_fields_open else '更多指标 ▾')
        app.fields_changed()
    app.metrics_button=ttk.Button(body,text='更多指标 ▾',style='Quiet.TButton',command=toggle_fields)
    app.metrics_button.grid(row=2,column=0,sticky='w',pady=(8,0))
    app.field_vars,app.field_buttons={},[]
    labels=('循环号','充电比容量（mAh/g）','放电比容量（mAh/g）','充放电效率（%）','充电能量','放电能量','容量保持率（%）','能量保持率（蓝电）')
    for i,label in enumerate(labels):
        variable=tk.BooleanVar(value=i in DEFAULT_COLUMNS); app.field_vars[i]=variable
        button=ttk.Checkbutton(fields if i<4 else extras,text=label,variable=variable,command=app.fields_changed)
        button.pack(anchor='w',pady=3); app.field_buttons.append(button)
    separator(body,4)
    ttk.Label(body,text='保存位置',style='Section.TLabel').grid(row=5,column=0,sticky='w',pady=(0,12))
    app.output=tk.StringVar(value=app.preferences.get('battery_output'))
    app.output_entry=ttk.Entry(body,textvariable=app.output,width=26); app.output_entry.grid(row=6,column=0,sticky='ew')
    app.output_entry.bind('<FocusOut>',lambda _: app.remember_paths(battery_output=app.output.get()))
    app.output_entry.bind('<Return>',lambda _: app.remember_paths(battery_output=app.output.get()))
    app.browse_button=ttk.Button(body,text='选择位置',command=app.choose_output); app.browse_button.grid(row=7,column=0,sticky='e',pady=(10,0))
    ttk.Label(body,text='一个 Excel，每个文件一个工作表',style='CardHint.TLabel').grid(row=8,column=0,sticky='w',pady=(12,0))
    separator(body,9)
    app.settings_button=ttk.Button(body,text='更多设置 ▾',style='Quiet.TButton',command=app.toggle_settings)
    app.settings_button.grid(row=10,column=0,sticky='w')
    app.advanced_window=tk.Toplevel(root); app.advanced_window.withdraw(); app.advanced_window.transient(root)
    app.advanced_window.title('电池文件 · 更多设置'); app.advanced_window.geometry('590x260')
    app.advanced_window.protocol('WM_DELETE_WINDOW',app.advanced_window.withdraw)
    advanced=inner(app.advanced_window,padding=24); advanced.pack(fill='both',expand=True)
    ttk.Label(advanced,text='新威循环统计',style='Section.TLabel').grid(row=0,column=0,sticky='w',padx=(0,24),pady=12)
    app.mode=tk.StringVar(value=next(iter(modes)))
    app.mode_box=ttk.Combobox(advanced,textvariable=app.mode,values=list(modes),state='readonly',width=16)
    app.mode_box.grid(row=0,column=1); app.mode_box.bind('<<ComboboxSelected>>',lambda _: app.fields_changed())
    app.recursive_box=ttk.Checkbutton(advanced,text='包含子文件夹',variable=app.recursive,command=app.fields_changed)
    app.recursive_box.grid(row=1,column=0,columnspan=2,sticky='w',pady=8)
    ttk.Label(advanced,text='单个蓝电文件的循环口径在「更多操作」中设置。',style='CardHint.TLabel').grid(row=2,column=0,columnspan=2,sticky='w',pady=8)
    ttk.Button(advanced,text='完成',style='Primary.TButton',command=app.advanced_window.withdraw).grid(row=3,column=1,sticky='e',pady=8)
    app.start_button=ttk.Button(settings.actions,text='▶  开始提取',command=app.start,style='Large.TButton'); app.start_button.pack(fill='x')
    app.stop_button=ttk.Button(settings.actions,text='停止后续文件',command=app.stop,state='disabled')
    app.open_button=ttk.Button(settings.actions,text='打开 Excel',image=icon(root,'open',size=20),compound='left',command=app.open_results,state='disabled')
    app.open_button.pack(fill='x',pady=(10,0))
    app.fields_changed()
