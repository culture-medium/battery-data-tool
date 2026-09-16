"""Portable synthetic regressions: signed energy must not determine order."""
from pathlib import Path
import struct
import tempfile
import unittest

from land_extract import extract, read_cex
from land_statistics import CHARGE, DISCHARGE
from neware_extract import ExtractionError


def header(layout, mode=CHARGE):
    data = bytearray(64)
    data[:8] = bytes.fromhex('10110988' + ('02010100' if layout == 'counter16' else '01000400'))
    struct.pack_into('<HHfB', data, 24, 5, 5, .001, int(mode == DISCHARGE))
    return bytes(data)


def marker(layout, mode, native=1):
    return struct.pack('<4I', 0xffffcccc, 0x44, int(mode == DISCHARGE),
                       (native if layout == 'float16' else 0) << 16)


def step(mode, timestamp=100):
    return struct.pack('<4I', 0xffffcccc, 0x22, mode, timestamp)


def point(layout, time, capacity, energy, mode=CHARGE, voltage=1):
    # Synthetic raw counts for counter16, and Ah/Wh for float16.
    return struct.pack('<Ihh', time, voltage, 100 if mode == CHARGE else -100) + (
        struct.pack('<If', capacity, energy) if layout == 'counter16'
        else struct.pack('<ff', capacity / 1e6, energy / 1e6))


def energy_in_wh(layout, raw):
    raw = struct.unpack('<f', struct.pack('<f', raw if layout == 'counter16' else raw / 1e6))[0]
    return raw * (5 / 16128) * (5 / 16128) / 3600 / 1000 if layout == 'counter16' else raw


class SignedEnergyTests(unittest.TestCase):
    def read_result(self, blob):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.cex'
            path.write_bytes(blob)
            result = extract(path)
            self.assertEqual(path.read_bytes(), blob)
            return result

    def test_decreasing_and_negative_endpoints_keep_sign_and_last_value(self):
        for layout in ('counter16', 'float16'):
            for mode in (CHARGE, DISCHARGE):
                for voltage in (-5, 0, 5):
                    for end in (20, 0, -10):
                        with self.subTest(layout=layout, mode=mode, voltage=voltage, end=end):
                            blob = header(layout, mode) + marker(layout, mode, int(mode == CHARGE)) + step(mode)
                            blob += b''.join(point(layout, i, i*1000, energy, mode, voltage)
                                             for i, energy in enumerate((0, 40, end)))
                            result = self.read_result(blob)
                            key = 'charge_energy_Wh' if mode == CHARGE else 'discharge_energy_Wh'
                            self.assertEqual(result['cycles'][0][key], energy_in_wh(layout, end))
                            self.assertEqual(result['audit']['energy_decrease_count'], 1)
                            self.assertEqual(result['audit']['negative_energy_record_count'], int(end < 0))
                            self.assertTrue(result['audit']['cycle_assignment']['source_order_preserved'])

    def test_continuation_uses_last_energy_without_summing_or_sorting(self):
        for layout in ('counter16', 'float16'):
            for mode in (CHARGE, DISCHARGE):
                blob = header(layout, mode) + marker(layout, mode, int(mode == CHARGE)) + step(mode)
                blob += point(layout, 0, 0, 0, mode) + point(layout, 1, 1000, 40, mode)
                blob += step(mode, 101) + point(layout, 2, 2000, 20, mode) + point(layout, 3, 3000, -10, mode)
                result = self.read_result(blob)
                self.assertEqual(len(result['cycles']), 1)
                self.assertEqual(result['audit']['continued_steps'], 1)
                self.assertEqual(result['audit']['energy_decrease_count'], 2)
                self.assertTrue(any(e['segment_boundary'] for e in result['audit']['energy_decrease_examples']))
                endpoint, = result['cycles'][0]['source_step_endpoints']
                self.assertEqual(len(endpoint['segments']), 2)
                self.assertEqual(endpoint['last']['energy_Wh'], energy_in_wh(layout, -10))

    def test_time_capacity_and_nonfinite_energy_remain_strict(self):
        for layout in ('counter16', 'float16'):
            prefix = header(layout) + marker(layout, CHARGE) + step(CHARGE)
            prefix += point(layout, 0, 0, 0) + point(layout, 2, 2000, 40)
            bad_points = [(1, 3000, 20), (3, 1000, 20), (3, 3000, float('nan')),
                          (3, 3000, float('inf')), (3, 3000, -float('inf'))]
            for t, q, e in bad_points:
                for continuation in (False, True):
                    with self.subTest(layout=layout, time=t, capacity=q, energy=e, continuation=continuation):
                        blob = prefix + (step(CHARGE, 101) if continuation else b'') + point(layout, t, q, e)
                        with self.assertRaises(ExtractionError): self.read_result(blob)

    def test_audit_count_is_complete_but_examples_are_bounded(self):
        for layout in ('counter16', 'float16'):
            blob = header(layout) + marker(layout, CHARGE) + step(CHARGE)
            blob += b''.join(point(layout, i, i*1000, -i) for i in range(81))
            result = self.read_result(blob)
            self.assertEqual(result['audit']['energy_decrease_count'], 80)
            self.assertEqual(result['audit']['negative_energy_record_count'], 80)
            self.assertEqual(len(result['audit']['energy_decrease_examples']), 32)
            self.assertEqual(result['cycles'][0]['charge_energy_Wh'], energy_in_wh(layout, -80))

    def test_missing_duplicate_reordered_cycles_are_rejected(self):
        layout = 'float16'
        groups = [marker(layout, mode, i//2+1) + step(mode, 100+i) +
                  point(layout, 0, 0, 0, mode) + point(layout, 1, 1000, 40, mode) +
                  point(layout, 2, 2000, 20, mode)
                  for i, mode in enumerate((CHARGE, DISCHARGE, CHARGE, DISCHARGE))]
        self.assertEqual(len(self.read_result(header(layout) + b''.join(groups))['cycles']), 2)
        for indices in ((0, 2, 3), (0, 1, 1, 2, 3), (0, 2, 1, 3), (2, 3)):
            with self.subTest(indices=indices), self.assertRaises(ExtractionError):
                self.read_result(header(layout) + b''.join(groups[i] for i in indices))

    def test_nonzero_initial_and_truncated_records_still_fail(self):
        for layout in ('counter16', 'float16'):
            prefix = header(layout) + marker(layout, CHARGE) + step(CHARGE)
            with self.assertRaises(ExtractionError): self.read_result(prefix + point(layout, 0, 0, -1))
            with self.assertRaises(ExtractionError): read_cex((prefix + point(layout, 0, 0, 0))[:-1])


if __name__ == '__main__': unittest.main()
