"""Exercise the real per-file CEX choice UI in source and frozen smoke runs."""
from pathlib import Path
import tempfile


def check_statistics_choice(app, manifest, output, wait_for, start_without_prompt):
    source = next((e['source'] for e in manifest['entries']
                   if e.get('capacity_basis') == 'absolute' and e.get('format') == 'land_cex'), None)
    if not source:
        return {'skipped': 'No absolute CEX input provided'}
    original = Path(source).read_bytes()
    with tempfile.TemporaryDirectory(dir=output, prefix='口径检查_') as folder:
        root = Path(folder)
        unknown, known = root/'待确认.cex', root/'已核验.cex'
        changed = bytearray(original); changed[32] = 255
        unknown.write_bytes(changed); known.write_bytes(original)
        app.clear(); app.add_paths([unknown, known])
        app.output.set(str(output/'口径流程'))
        # The advanced Neware setting must not override CEX file settings.
        app.mode.set('放电优先')
        start_without_prompt(app); wait_for(app.root, app)
        first = app.last_manifest
        assert (first['failed'], first['success']) == (1, 1), first
        error = next(e for e in first['entries'] if e['status'] == 'error')
        assert error['error_code'] == 'statistics_choice_required'
        assert app.tree.set(str(error['index']), 'status') == '需确认口径'
        app.tree.selection_set(str(error['index'])); app.show_selection()
        assert '蓝电循环口径' in app.detail.get()
        assert str(app.actions_menu.entrycget('蓝电循环口径', 'state')) == 'normal'
        app.land_menu.invoke(1)  # The actual "先充后放" per-file menu action.
        assert not app.busy and app.last_manifest is None
        assert str(app.actions_menu.entrycget('另存所选列', 'state')) == 'disabled'
        assert app.land_modes[str(unknown)] == 'charge'
        assert app.land_modes.get(str(known), 'auto') == 'auto'
        start_without_prompt(app); wait_for(app.root, app)
        second = app.last_manifest
        assert (second['failed'], second['success']) == (0, 2), second
        assert all(e['cycles'] == 191 for e in second['entries'])
        sources = [e['statistics_policy']['source'] for e in second['entries']]
        assert sources == ['explicit_user_choice', 'file_header_byte_32_verified_mapping'], sources
        app.clear(); app.mode.set('自动')
        assert not app.land_modes
    return {'unknown_marked_for_confirmation': True, 'valid_files_continue': True,
            'per_file_menu_retry': True, 'stale_results_invalidated': True,
            'neware_setting_does_not_override_cex': True, 'confirmed_cycles': 191}
