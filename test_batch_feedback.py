import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from batch_statistics import file_statistics, rate_text
from failed_files import copy_failed_files, offer_failed_files, failure_folder, open_failure_folder
from neware_batch import run_batch
from test_neware_batch import fake_result
from text_batch import run_text_batch


class BatchFeedbackTests(unittest.TestCase):
    def test_open_button_prefers_copy_folder_then_selected_failed_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); entries = []
            for i in range(2):
                parent = root/str(i); parent.mkdir()
                source = parent/'bad.cex'; source.write_bytes(b'original')
                entries.append({'index':i, 'source':str(source), 'status':'error'})
            manifest = {'entries':entries, 'run_directory':str(root/'out')}
            self.assertEqual(failure_folder(manifest, entries[1]['source']), (root/'1').resolve())
            manifest['failed_file_copies'] = copy_failed_files(manifest)
            expected = Path(manifest['failed_file_copies']['directory']).resolve()
            with patch('failed_files.os.startfile') as start:
                open_failure_folder(None, manifest, entries[1]['source']); start.assert_called_once_with(str(expected))
            manifest['failed_file_copies']['directory'] = str(root/'missing')
            self.assertEqual(failure_folder(manifest, entries[1]['source']), (root/'1').resolve())
            self.assertIsNone(failure_folder({'entries':[{'status':'success'}]}))

    def test_rate_excludes_filtered_and_unprocessed_without_claiming_accuracy(self):
        entries = [{'index': i, 'status': status} for i, status in enumerate(('success', 'error', 'success', 'filtered'))]
        stats = file_statistics(entries)
        self.assertEqual((stats['successful'], stats['failed'], stats['processed'], stats['filtered']), (2, 1, 3, 1))
        self.assertEqual(rate_text(stats), '66.7%')
        self.assertEqual(stats['basis'], 'file_extraction')
        self.assertIsNone(file_statistics([])['success_rate_percent'])
        self.assertEqual(rate_text(file_statistics([entries[-1]])), '—')

    def test_cancel_and_excel_failure_have_separate_meanings(self):
        with tempfile.TemporaryDirectory() as folder, patch('neware_batch.extract', side_effect=fake_result):
            root = Path(folder); stop = threading.Event()
            def receive(event):
                if event['type'] == 'file_done': stop.set()
            result = run_batch([root/'a.ndax', root/'b.ndax'], root/'out', cancel=stop, on_event=receive)
            self.assertEqual(result['statistics']['success_rate_percent'], 100.)
            self.assertEqual(result['statistics']['processed'], 1)
            self.assertEqual(result['skipped'], 1)
            with patch('neware_batch.export_workbook', side_effect=OSError('Excel unavailable')):
                result = run_batch([root/'a.ndax'], root/'out')
            self.assertEqual(result['statistics']['success_rate_percent'], 100.)
            self.assertIn('Excel unavailable', result['excel_error'])

    def test_text_batch_records_actual_parse_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            good, bad = root/'good.txt', root/'bad.txt'
            good.write_text('x,y\n1,2\n3,4', encoding='utf-8'); bad.write_bytes(b'\xff\xfe\x00')
            result = run_text_batch([good, bad], root/'out')
            self.assertEqual(result['statistics']['success_rate_percent'], 50.)
            self.assertEqual(result['statistics']['failed'], 1)

    def test_failed_copies_keep_originals_and_disambiguate_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); entries = []; originals = {}
            for index, status in enumerate(('error', 'error', 'success', 'filtered')):
                parent = root/str(index); parent.mkdir()
                path = parent/'same.cex'; path.write_bytes(bytes([index])*16); originals[path] = path.read_bytes()
                entries.append({'index': index, 'source': str(path), 'status': status, 'error': 'test failure'})
            manifest = {'entries': entries, 'run_directory': str(root/'out')}
            report = copy_failed_files(manifest)
            self.assertEqual(len(report['copied']), 2); self.assertFalse(report['copy_errors'])
            self.assertEqual({Path(e['copy']).name for e in report['copied']}, {'same.cex', 'same_2.cex'})
            for e in report['copied']: self.assertEqual(Path(e['source']).read_bytes(), Path(e['copy']).read_bytes())
            for path, data in originals.items(): self.assertEqual(path.read_bytes(), data)
            self.assertNotEqual(copy_failed_files(manifest)['directory'], report['directory'])

    def test_no_copy_until_yes_and_no_prompt_for_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root/'bad.cex'; source.write_bytes(b'original')
            manifest = {'entries': [{'index': 0, 'source': str(source), 'status': 'error'}], 'run_directory': str(root/'out')}
            with patch('failed_files.messagebox.askyesno', return_value=False) as ask:
                self.assertIsNone(offer_failed_files(None, manifest))
                self.assertIsNone(offer_failed_files(None, manifest)); ask.assert_called_once()
                self.assertFalse((root/'out').exists())
            manifest.pop('failed_files_prompted')
            with patch('failed_files.messagebox.askyesno', return_value=True) as ask:
                self.assertIn('已复制 1', offer_failed_files(None, manifest)); ask.assert_called_once()
            persisted = json.loads((root/'out'/'批次记录.json').read_text(encoding='utf-8'))
            self.assertEqual(len(persisted['failed_file_copies']['copied']), 1)
            with patch('failed_files.messagebox.askyesno') as ask:
                self.assertIsNone(offer_failed_files(None, {'entries': [{'status': 'success'}]})); ask.assert_not_called()

    def test_missing_failed_source_is_reported_without_losing_other_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); good = root/'exists.cex'; good.write_bytes(b'unchanged')
            manifest = {'entries': [{'status': 'error', 'source': str(p)} for p in (root/'missing.cex', good)],
                        'run_directory': str(root/'out')}
            report = copy_failed_files(manifest)
            self.assertEqual(len(report['copied']), 1); self.assertEqual(len(report['copy_errors']), 1)
            self.assertEqual(good.read_bytes(), b'unchanged')


if __name__ == '__main__': unittest.main()
