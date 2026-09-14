"""Exercise the loaded Windows TkDnD bridge without synthesizing OS input."""
from pathlib import Path
import tempfile


def native_drop(app, paths, widget=None):
    widget = widget or app.tree
    tk = app.root.tk
    data = tuple(str(Path(p).resolve()) for p in paths)
    action = tk.call('tkdnd::olednd::HandleDragEnter', str(widget), ('CF_HDROP',), ('copy',), (), 0, 0, ('15',), data)
    if action == 'refuse_drop':
        tk.call('tkdnd::olednd::HandleDragLeave', str(widget))
        return action
    return tk.call('tkdnd::olednd::HandleDrop', str(widget), (), 0, 0, 'CF_HDROP', data)


def check_drop_inputs(app):
    assert app.dnd_enabled
    from file_drop import receive_drop
    from text_batch import run_text_batch
    assert app.root.tk.call('package', 'present', 'tkdnd')
    app.clear(); app.text_panel.clear_files()
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder); nested = base/'中文 空格 {数据}'; nested.mkdir()
        a, b = nested/'电池 #1.cex', base/'电池2.NDAX'
        a.write_bytes(b'input only'); b.write_bytes(b'input only')
        x, y, ignored = nested/'指定文本.TXT', base/'第二份.tsv', nested/'不可误加.txt'
        for p in (x, y, ignored): p.write_text('x\ty\n1\t2', encoding='utf-8')
        assert native_drop(app, [a, x], app.empty_hint) == 'copy'
        assert app.files == [a.resolve()] and app.text_panel.files == [x.resolve()]
        assert app.notebook.index('current') == 0
        assert native_drop(app, [x, y], app.text_panel.tree) == 'copy'
        assert app.text_panel.files == [x.resolve(), y.resolve()]
        app.text_panel.scan_folder()  # Focus changes must not import siblings.
        assert ignored.resolve() not in app.text_panel.files
        result = run_text_batch(app.text_panel.dropped_files, base/'output')
        assert result['success'] == 2 and result['failed'] == 0 and not result['excel_errors']
        assert len({e['identity'] for e in result['entries']}) == 2
        app.busy = True
        assert native_drop(app, [b]) == 'refuse_drop'
        assert app.files == [a.resolve()]
        app.busy = False
        assert receive_drop(app, '{broken') == 'refuse_drop'
        app.clear(); app.text_panel.clear_files()
        app.recursive.set(False); app.text_panel.recursive.set(False)
        assert native_drop(app, [base]) == 'copy'
        assert app.files == [b.resolve()] and app.text_panel.files == [y.resolve()]
        app.recursive.set(True); app.text_panel.recursive.set(True)
        assert native_drop(app, [base, a, x]) == 'copy'
        assert set(app.files) == {a.resolve(), b.resolve()}
        assert set(app.text_panel.files) == {x.resolve(), y.resolve(), ignored.resolve()}
        assert not app.busy and not app.text_panel.busy and app.last_manifest is None
        app.clear(); app.text_panel.clear_files(); app.notebook.select(0)
    return {'tkdnd_version': app.root.tk.call('package', 'present', 'tkdnd'),
            'windows_tcl_bridge': True, 'multi_file_folder_chinese_spaces_braces': True,
            'deduplication_and_busy_rejection': True, 'explicit_text_files_only': True,
            'physical_mouse_drag_tested': False}
