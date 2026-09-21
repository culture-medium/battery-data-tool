"""UI behavior regressions: selection, navigation, file pickers and scroll."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from neware_app import ExtractorApp
from test_app_preferences import cancel_callbacks


class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.root = tk.Tk(); self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(str(args[1]))
        self.app = ExtractorApp(self.root, settings_path=self.base/'settings.json')
        self.root.update_idletasks()

    def tearDown(self):
        cancel_callbacks(self.root); self.root.destroy(); self.directory.cleanup()
        self.assertEqual(self.errors, [])

    def test_navigation_and_extra_columns_preserve_independent_state(self):
        self.app.metrics_button.invoke(); self.assertTrue(self.app.extra_fields_open)
        self.app.field_buttons[4].invoke()
        self.app.nav_buttons[1].invoke()
        self.assertEqual(self.app.notebook.index('current'),1)
        self.app.text_panel.cv_split.set(False)
        self.app.nav_buttons[0].invoke()
        self.assertEqual(self.app.current_columns(),(0,1,2,3,4))
        self.assertFalse(self.app.text_panel.cv_split.get())
        self.app.metrics_button.invoke(); self.assertFalse(self.app.extra_fields_open)
        self.assertIn('已选 1 项',self.app.metrics_button['text'])

    def test_picker_adds_supported_files_once_and_remove_preserves_sources(self):
        a,b,c=self.base/'sample.cex',self.base/'sample.ndax',self.base/'table.txt'
        for path in (a,b,c): path.write_text('x,y\n1,2',encoding='utf-8')
        with patch('neware_app.filedialog.askopenfilenames',return_value=(str(a),str(b),str(a))):
            self.app.add_button.invoke()
        self.assertEqual(len(self.app.files),2)
        self.assertEqual({self.app.tree.set(i,'kind') for i in self.app.tree.get_children()},{'CEX','NDAX'})
        self.app.tree.selection_set('0'); self.app.show_selection(); self.app.remove_button.invoke()
        self.assertEqual(len(self.app.files),1)
        with patch('text_panel.filedialog.askopenfilenames',return_value=(str(c),str(c))):
            self.app.text_panel.add_button.invoke()
        self.assertEqual(self.app.text_panel.files,[c])
        self.assertTrue(all(p.exists() for p in (a,b,c)))

    def test_checkboxes_shift_selection_keyboard_and_scrolling_keep_row_identity(self):
        tree=self.app.tree
        for i in range(1000): tree.insert('','end',iid=str(i),values=(f'样品_{i}.cex','CEX','完成',i,1.2))
        self.root.update_idletasks(); tree._layout()
        y=tree.header_height+tree.row_height/2
        tree._click(SimpleNamespace(x=18,y=y,state=0))
        tree._click(SimpleNamespace(x=18,y=y+tree.row_height,state=0))
        self.assertEqual(tree.selection(),('0','1'))
        tree._click(SimpleNamespace(x=75,y=y+3*tree.row_height,state=1))
        self.assertEqual(tree.selection(),('1','2','3'))
        tree._select_all(SimpleNamespace()); tree._select_all(SimpleNamespace())
        self.assertEqual(len(tree.selection()),1000)
        tree._click(SimpleNamespace(x=18,y=10,state=0)); self.assertEqual(tree.selection(),())
        tree.see('950'); self.root.update_idletasks()
        self.assertGreater(tree._top,900)
        self.assertLess(len(tree.find_all()),500)
        self.assertEqual(tree.get_children(),tuple(map(str,range(1000))))
        tree.focus('950'); tree._key(SimpleNamespace(keysym='Down',state=0))
        self.assertEqual(tree.selection(),('951',))
        self.assertEqual(tree.item('951')['values'][0],'样品_951.cex')

    def test_busy_and_missing_mass_do_not_mislabel_actions_or_units(self):
        self.app.entries={0:{'status':'success','capacity_basis':'absolute'}}
        self.app.fields_changed()
        self.assertEqual(self.app.field_buttons[1]['text'],'充电容量（mAh）')
        self.app.set_busy(True)
        self.assertEqual(str(self.app.add_button['state']),'disabled')
        self.assertEqual(str(self.app.metrics_button['state']),'disabled')
        self.assertEqual(str(self.app.stop_button['state']),'normal')
        self.app.set_busy(False)
        self.assertEqual(str(self.app.add_button['state']),'normal')
        self.assertEqual(str(self.app.remove_button['state']),'disabled')
        self.app.clear()
        self.assertEqual(self.app.field_buttons[1]['text'],'充电比容量（mAh/g）')

    def test_import_actions_reflow_in_both_narrow_panels(self):
        for panel in (self.app,self.app.text_panel):
            panel.drop_zone.reflow(SimpleNamespace(width=520))
            self.assertEqual(int(panel.add_button.master.grid_info()['row']),2)
            panel.drop_zone.reflow(SimpleNamespace(width=860))
            self.assertEqual(int(panel.add_button.master.grid_info()['row']),0)


if __name__=='__main__': unittest.main()
