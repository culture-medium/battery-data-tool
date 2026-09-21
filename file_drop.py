"""Native file drops add inputs only; dropping never moves or starts a file."""
from pathlib import Path
import tkinter as tk

from neware_batch import collect_files
from text_batch import collect_text_files


def receive_drop(app, data):
    # Tcl list parsing preserves spaces, Chinese, braces and multi-file drops.
    if app.busy or app.text_panel.busy:
        app.status.set('正在处理，请完成后再拖入文件。')
        app.text_panel.status.set('正在处理，请完成后再拖入文件。')
        return 'refuse_drop'
    try:
        paths = [Path(p) for p in app.root.tk.splitlist(data)]
        battery = collect_files(paths, app.recursive.get())
        text = collect_text_files(paths, app.text_panel.recursive.get())
        if not battery and not text:
            panel = app.text_panel if app.notebook.index('current') == 1 else app
            panel.detail.set('没有可添加的文件：支持 NDAX、CEX、TXT、CSV、TSV。')
            return 'refuse_drop'
        if battery: app.add_paths(battery)
        if text: app.text_panel.add_paths(text)
        app.notebook.select(0 if battery else 1)
        message = f'已添加电池文件 {len(battery)} 个、文本文件 {len(text)} 个；重复文件自动忽略。'
        app.status.set(message); app.text_panel.status.set(message)
        return 'copy'
    except (OSError, ValueError, tk.TclError) as exc:
        app.detail.set(f'无法添加拖入的文件：{exc}')
        app.text_panel.detail.set(f'无法添加拖入的文件：{exc}')
        return 'refuse_drop'


def register_drop(app):
    if not hasattr(app.root, 'drop_target_register'): return False
    from tkinterdnd2 import DND_FILES
    # Explicitly cover the lists and their empty-state labels as well as the
    # window, so dropping on a child control follows the same route.
    widgets = [app.root, app.tree, app.empty_hint, app.text_panel.tree, app.text_panel.empty_hint]
    def add_zone(widget):
        widgets.append(widget)
        for child in widget.winfo_children(): add_zone(child)
    for zone in (app.drop_zone, app.text_panel.drop_zone): add_zone(zone)
    for widget in widgets:
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind('<<Drop>>', lambda event: receive_drop(app, event.data))
        widget.dnd_bind('<<DropPosition>>', lambda event: 'refuse_drop' if app.busy or app.text_panel.busy else 'copy')
    return True
