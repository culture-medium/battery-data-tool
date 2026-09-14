import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app_preferences import Preferences
from neware_app import ExtractorApp


class FolderPreferencesTests(unittest.TestCase):
    def test_restart_restores_four_paths_without_changing_default_columns(self):
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
            app.close()
            root = tk.Tk(); root.withdraw()
            app = ExtractorApp(root, settings_path=settings)
            try:
                root.update_idletasks()
                self.assertEqual(app.preferences.get('battery_input'), str(battery))
                self.assertEqual(app.output.get(), str(base/'电池输出'))
                self.assertEqual(app.text_panel.input.get(), str(text))
                self.assertEqual(app.text_panel.output.get(), str(base/'文本输出'))
                self.assertEqual(len(app.files), 1)
                self.assertEqual(len(app.text_panel.tree.get_children()), 1)
                self.assertEqual(app.current_columns(), (0, 1, 2, 3))
                self.assertIsNone(app.last_manifest)
                app.tree.selection_set('0'); app.show_selection()
                app.actions_menu.invoke('移除选中')
                self.assertEqual(app.files, [])
                app.add_paths([battery])
                app.actions_menu.invoke('清空列表')
                self.assertEqual(app.files, [])
            finally: root.destroy()

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
