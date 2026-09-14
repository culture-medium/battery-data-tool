"""Shared, quiet desktop styling and full-width file lists."""
import tkinter as tk
from tkinter import ttk

BG, WHITE, INK, MUTED, BLUE = '#FFFFFF', '#FFFFFF', '#263445', '#657284', '#3168D5'
FIELD = '#F3F5F7'


def install_tick_indicator(root, style):
    """Use a check-shaped image instead of clam's cross-shaped indicator."""
    size = max(20, round(float(root.tk.call('tk', 'scaling')) * 15))
    images = []
    for selected, disabled in ((False, False), (True, False), (False, True), (True, True)):
        image = tk.PhotoImage(master=root, width=size + 10, height=size)
        fill = '#ABC0E5' if selected and disabled else BLUE if selected else '#E6EAF0' if disabled else '#E0E6ED'
        for y in range(size):
            for x in range(size):
                # A filled rounded square, with no outline.
                if (x < 3 or x >= size-3) and (y < 3 or y >= size-3):
                    cx = 3 if x < 3 else size-4
                    cy = 3 if y < 3 else size-4
                    if (x-cx)**2 + (y-cy)**2 > 10: continue
                color = fill
                if selected:
                    px, py = x / size, y / size
                    points = ((.22, .49), (.42, .69), (.78, .29))
                    for (ax, ay), (bx, by) in zip(points, points[1:]):
                        t = max(0, min(1, ((px-ax)*(bx-ax)+(py-ay)*(by-ay))/((bx-ax)**2+(by-ay)**2)))
                        if (px-ax-t*(bx-ax))**2 + (py-ay-t*(by-ay))**2 < .065**2:
                            color = WHITE
                image.put(color, (x, y))
        images.append(image)
    root._tick_images = images
    style.element_create('Tick.indicator', 'image', images[0],
                         ('disabled', 'selected', images[3]), ('disabled', images[2]), ('selected', images[1]))
    style.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
        ('Tick.indicator', {'side': 'left', 'sticky': ''}),
        ('Checkbutton.label', {'side': 'left', 'sticky': 'w'})]})])


def configure_style(root):
    root.configure(background=BG)
    root.option_add('*Font', ('Microsoft YaHei UI', 11))
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Microsoft YaHei UI', 11), foreground=INK)
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=WHITE, relief='flat', borderwidth=0)
    style.configure('Inner.TFrame', background=WHITE)
    style.configure('TLabel', background=BG, foreground=INK)
    style.configure('Card.TLabel', background=WHITE)
    style.configure('Title.TLabel', font=('Microsoft YaHei UI', 20, 'bold'), foreground='#1E304B')
    style.configure('Section.TLabel', background=WHITE, font=('Microsoft YaHei UI', 11, 'bold'))
    style.configure('Hint.TLabel', foreground=MUTED, font=('Microsoft YaHei UI', 11))
    style.configure('CardHint.TLabel', background=WHITE, foreground=MUTED, font=('Microsoft YaHei UI', 11))
    style.configure('TButton', background=FIELD, bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD,
                    borderwidth=0, relief='flat', padding=(14, 9), focusthickness=0)
    style.map('TButton', background=[('disabled', '#F8F9FA'), ('active', '#EAF0F9')],
              foreground=[('disabled', '#AAB3C1')], relief=[('pressed', 'flat'), ('!pressed', 'flat')],
              bordercolor=[('active', '#EAF0F9'), ('!active', FIELD)])
    style.configure('Primary.TButton', background=BLUE, foreground=WHITE, bordercolor=BLUE, lightcolor=BLUE, darkcolor=BLUE, font=('Microsoft YaHei UI', 11, 'bold'))
    style.map('Primary.TButton', background=[('disabled', '#DCE4F1'), ('active', '#2456BA')],
              foreground=[('disabled', '#94A4BB'), ('!disabled', WHITE)], bordercolor=[('disabled', '#DCE4F1'), ('!disabled', BLUE)])
    style.configure('TEntry', padding=(9, 8), borderwidth=0, relief='flat', bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD, fieldbackground=FIELD)
    style.map('TEntry', bordercolor=[('focus', FIELD), ('!focus', FIELD)], lightcolor=[('focus', FIELD)], darkcolor=[('focus', FIELD)])
    style.configure('TCombobox', padding=(8, 7), borderwidth=0, relief='flat', bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD, background=FIELD, fieldbackground=FIELD, arrowsize=13)
    style.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', INK)], bordercolor=[('focus', FIELD), ('!focus', FIELD)], lightcolor=[('focus', FIELD)], darkcolor=[('focus', FIELD)])
    style.configure('TCheckbutton', background=WHITE, font=('Microsoft YaHei UI', 11), padding=(0, 4))
    style.map('TCheckbutton', background=[('active', WHITE)])
    install_tick_indicator(root, style)
    style.configure('TNotebook', background=BG, borderwidth=0, bordercolor=WHITE, lightcolor=WHITE, darkcolor=WHITE, tabmargins=(0, 0, 0, 0))
    style.configure('TNotebook.Tab', background=BG, foreground=MUTED, padding=(25, 11), borderwidth=0, bordercolor=WHITE, lightcolor=WHITE, darkcolor=WHITE, font=('Microsoft YaHei UI', 11))
    style.map('TNotebook.Tab', background=[('selected', WHITE), ('active', '#EAF0F9')], foreground=[('selected', BLUE)])
    style.configure('Settings.TNotebook', background=WHITE, borderwidth=0)
    style.configure('Settings.TNotebook.Tab', background=WHITE, padding=(18, 7), font=('Microsoft YaHei UI', 11))
    style.map('Settings.TNotebook.Tab', background=[('selected', '#EAF0FC'), ('active', '#F4F7FC')], foreground=[('selected', BLUE)])
    style.configure('Treeview', background=WHITE, fieldbackground=WHITE, borderwidth=0, relief='flat', rowheight=36, font=('Microsoft YaHei UI', 11))
    style.configure('Treeview.Heading', background=FIELD, foreground=MUTED, relief='flat', borderwidth=0, bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD, padding=(12, 11), font=('Microsoft YaHei UI', 11))
    style.map('Treeview', background=[('selected', '#E8F0FD')], foreground=[('selected', '#234B85')])
    style.map('Treeview.Heading', background=[('active', '#EDF2FA')])
    style.configure('Horizontal.TProgressbar', background=BLUE, troughcolor='#E2E9F3', borderwidth=0, thickness=4)
    style.configure('TScrollbar', background='#D9E1EC', troughcolor=WHITE, borderwidth=0, arrowsize=11)
    return style


def card(parent, **kwargs):
    return ttk.Frame(parent, style='Card.TFrame', padding=(0, 10, 0, 4), **kwargs)


def inner(parent, **kwargs):
    return ttk.Frame(parent, style='Inner.TFrame', **kwargs)


def file_table(parent, columns, labels, widths, *, multiple=False):
    frame = inner(parent)
    frame.columnconfigure(0, weight=1); frame.rowconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=columns, show='headings', height=8,
                       selectmode='extended' if multiple else 'browse')
    for key, label, width in zip(columns, labels, widths):
        tree.heading(key, text=label, anchor='w' if key == 'file' else 'center')
        tree.column(key, width=width, minwidth=80 if key != 'file' else 320,
                    stretch=key == 'file', anchor='w' if key == 'file' else 'center')
    tree.grid(row=0, column=0, sticky='nsew')
    y = ttk.Scrollbar(frame, orient='vertical', command=tree.yview); y.grid(row=0, column=1, sticky='ns')
    x = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview); x.grid(row=1, column=0, sticky='ew')
    tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
    tree.tag_configure('error', foreground='#B34C4C')
    tree.tag_configure('warning', foreground='#AB7B2F')
    tree.tag_configure('success', foreground='#2E7962')
    tree.tag_configure('alternate', background='#FAFBFD')
    return frame, tree


def wrap_label(parent, variable):
    label = ttk.Label(parent, textvariable=variable, style='CardHint.TLabel', wraplength=1000)
    parent.bind('<Configure>', lambda e: label.configure(wraplength=max(200, e.width-36)), add='+')
    def update_visibility(*_):
        if variable.get(): label.grid()
        else: label.grid_remove()
    variable.trace_add('write', update_visibility)
    label.after_idle(update_visibility)
    return label
