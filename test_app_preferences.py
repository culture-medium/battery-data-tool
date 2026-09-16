import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from app_preferences import Preferences
from neware_app import ExtractorApp


def cancel_callbacks(root):
    for callback in root.tk.call('after', 'info'):
        root.tk.call('after', 'cancel', callback)


class FolderPreferencesTests(unittest.TestCase):
    def test_restart_remembers_folders_but_keeps_both_queues_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            battery = base/'电池输入'; battery.mkdir()
            text = base/'文本输入'; text.mkdir()
            (battery/'sample.ndax').write_bytes(b'not parsed during restore')
            (text/'sample.txt').write_text('1\t2', encoding='utf-8')
            settings = base/'设置.json'
            root = tk.Tk(); root.withdraw()
            app = ExtractorApp(root, settings_path=settings)
            root.update_idletasks()
            with patch('neware_app.filedialog.askdirectory', return_value=str(battery)):
                app.choose_folder()
            app.output.set(str(base/'电池输出'))
            with patch('text_panel.filedialog.askdirectory', return_value=str(text)):
                app.text_panel.choose(app.text_panel.input)
            app.text_panel.output.set(str(base/'文本输出'))
            app.field_buttons[4].invoke()
            root.update_idletasks()
            cancel_callbacks(root); app.close()
            root = tk.Tk(); root.withdraw()
            app = ExtractorApp(root, settings_path=settings)
            try:
                root.update_idletasks()
                self.assertEqual(app.preferences.get('battery_input'), str(battery))
                self.assertEqual(app.output.get(), str(base/'电池输出'))
                self.assertEqual(app.text_panel.input.get(), '')
                self.assertEqual(app.preferences.initial_directory('text_input'), str(text))
                self.assertEqual(app.text_panel.output.get(), str(base/'文本输出'))
                self.assertEqual(app.files, [])
                self.assertEqual(len(app.text_panel.tree.get_children()), 0)
                self.assertEqual(app.current_columns(), (0, 1, 2, 3))
                self.assertIsNone(app.last_manifest)
                app.add_paths([battery])
                app.tree.selection_set('0'); app.show_selection()
                app.actions_menu.invoke('移除选中')
                self.assertEqual(app.files, [])
                app.add_paths([battery])
                app.actions_menu.invoke('清空列表')
                self.assertEqual(app.files, [])
            finally: cancel_callbacks(root); root.destroy()

    def test_save_location_is_chosen_once_and_cancel_preserves_queue(self):
        from test_neware_batch import fake_result
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base/'sample.ndax'; source.write_bytes(b'original')
            root = tk.Tk(); root.withdraw()
            app = ExtractorApp(root, settings_path=base/'settings.json')
            try:
                app.add_paths([source])
                self.assertEqual(app.output.get(), '')
                with patch('neware_app.filedialog.askdirectory', return_value='') as choose:
                    app.start()
                    choose.assert_called_once()
                self.assertFalse(app.busy)
                self.assertEqual(app.files, [source])
                self.assertFalse(list(base.rglob('*.xlsx')))
                chosen = base/'用户指定保存目录'
                with patch('neware_app.filedialog.askdirectory', return_value=str(chosen)) as choose:
                    app.choose_output()
                    choose.assert_called_once()
                with (patch('neware_app.filedialog.askdirectory', side_effect=AssertionError('Already selected')),
                     patch('neware_app.filedialog.asksaveasfilename', side_effect=AssertionError('No second prompt')),
                     patch('neware_batch.extract', side_effect=fake_result)):
                    for _ in range(2):
                        app.start()
                        deadline = time.monotonic()+15
                        while app.busy and time.monotonic() < deadline:
                            root.update(); time.sleep(.02)
                        self.assertFalse(app.busy)
                        self.assertIsNone(app.last_error)
                        self.assertTrue(app.last_workbook.is_relative_to(chosen))
                        self.assertTrue(app.last_workbook.is_file())
                self.assertEqual(Preferences(base/'settings.json').get('battery_output'), str(chosen))
                self.assertEqual(source.read_bytes(), b'original')
            finally: cancel_callbacks(root); root.destroy()

    def test_text_remove_stays_removed_and_uses_chosen_output_without_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); source = base/'inputs'; source.mkdir()
            a, b = source/'a.txt', source/'b.txt'
            for path in (a, b): path.write_text('X\tY\n1\t2\n3\t4', encoding='utf-8')
            root = tk.Tk(); root.withdraw()
            app = ExtractorApp(root, settings_path=base/'settings.json'); panel = app.text_panel
            try:
                panel.input.set(str(source)); panel.scan_folder()
                panel.tree.selection_set('0'); panel.remove_button.invoke()
                self.assertEqual(panel.files, [b])
                with patch('text_panel.filedialog.askdirectory', return_value=''):
                    panel.start()
                self.assertFalse(panel.busy)
                self.assertEqual(panel.files, [b])
                chosen = base/'chosen'
                with patch('text_panel.filedialog.askdirectory', return_value=str(chosen)):
                    panel.choose(panel.output)
                with patch('text_panel.filedialog.askdirectory', side_effect=AssertionError('Already selected')):
                    panel.start()
                    deadline = time.monotonic()+15
                    while panel.busy and time.monotonic() < deadline:
                        root.update(); time.sleep(.02)
                self.assertFalse(panel.busy)
                self.assertEqual(len(panel.manifest['entries']), 1)
                self.assertEqual(panel.manifest['success'], 1)
                self.assertTrue(all(Path(p).is_relative_to(chosen) for p in panel.manifest['workbooks']))
                self.assertEqual(panel.files, [b])
                self.assertTrue(a.is_file() and b.is_file())
                panel.clear_files(); panel.scan_folder()
                self.assertEqual(panel.files, [])
            finally: cancel_callbacks(root); root.destroy()

    def test_invalid_settings_and_missing_folder_do_not_break_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); settings=base/'设置.json'
            for content in ('invalid json', 'null', '[]', '{"battery_input": 123}'):
                settings.write_text(content, encoding='utf-8')
                self.assertEqual(Preferences(settings).get('battery_input'), '')
            settings.write_text(json.dumps({'battery_input': str(base/'missing')}), encoding='utf-8')
            pref=Preferences(settings)
            self.assertEqual(pref.initial_directory('battery_input'), str(base))

    def test_failed_save_preserves_previous_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); settings=base/'设置.json'; pref=Preferences(settings)
            pref.remember(battery_output=base/'old')
            original=settings.read_bytes()
            with patch('app_preferences.os.replace', side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError): pref.remember(battery_output=base/'new')
            self.assertEqual(settings.read_bytes(), original)
            self.assertEqual(Preferences(settings).get('battery_output'), str(base/'old'))
            self.assertEqual(list(base.glob('.folders_*')), [])


if __name__ == '__main__': unittest.main(verbosity=2)
