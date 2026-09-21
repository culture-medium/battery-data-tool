"""Portable boundary tests for terminal current samples and stored baselines."""
from pathlib import Path
import struct
import tempfile
import unittest

from land_extract import extract, read_cex
from neware_extract import ExtractionError
from test_land_energy import header, marker, step, point, CHARGE, DISCHARGE


def sample(layout, mode, final_current):
    data = header(layout, mode) + marker(layout, mode, int(mode == CHARGE)) + step(mode)
    data += point(layout, 0, 0, 0, mode) + point(layout, 1, 1000, 20, mode)
    last = bytearray(point(layout, 2, 2000, 40, mode)); struct.pack_into('<h', last, 6, final_current)
    data += last
    rest = bytearray(point(layout, 3, 2000, 40, mode)); struct.pack_into('<h', rest, 6, 0)
    return data + step(0x70, 101) + rest + rest


class TerminalCurrentTests(unittest.TestCase):
    def test_terminal_zero_or_reversed_current_uses_mode_and_held_rest(self):
        for layout in ('counter16', 'float16'):
            for mode in (CHARGE, DISCHARGE):
                for current in (0, -3 if mode == CHARGE else 3):
                    blob = sample(layout, mode, current); audit = {}
                    steps = read_cex(blob, metadata=audit)[2]
                    self.assertEqual(audit['terminal_current_anomaly_count'], 1)
                    self.assertEqual(steps[0]['last']['current_raw'], current)
                    with tempfile.TemporaryDirectory() as folder:
                        path = Path(folder)/'random-name.cex'; path.write_bytes(blob)
                        result = extract(path)
                        self.assertEqual(len(result['cycles']), 1)
                        self.assertEqual(result['cycles'][0]['source_step_endpoints'][0]['mode'], mode)

    def test_interior_outlier_and_unsupported_terminal_conditions_still_fail(self):
        original = sample('float16', DISCHARGE, 3)
        variants = [original[:-48]]  # No following rest.
        for offset, fmt, value in [(118, '<h', 3), (144+8, '<I', CHARGE),
                                   (160+6, '<h', 1), (160+8, '<f', .003),
                                   (160+12, '<f', .000041), (176+12, '<f', .000041),
                                   (160, '<I', 1), (144+12, '<I', 99), (64+8, '<I', 0)]:
            data = bytearray(original); struct.pack_into(fmt, data, offset, value); variants.append(bytes(data))
        for index, blob in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ExtractionError): read_cex(blob)


if __name__ == '__main__': unittest.main()
