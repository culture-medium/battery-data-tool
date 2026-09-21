"""Portable tests for header-bound recovery events, not arbitrary rollback."""
from pathlib import Path
import struct
import tempfile
import unittest

from land_extract import extract, read_cex
from neware_extract import ExtractionError
from test_land_energy import header, marker, step, point, CHARGE, DISCHARGE


def recovery_sample(mode=CHARGE, placeholder=False):
    head = bytearray(header('float16', mode))
    head[4:8] = bytes.fromhex('07000400'); head[8:10] = bytes([13, 6])
    struct.pack_into('<HH', head, 24, 0xe005, 0xc005)
    struct.pack_into('<I', head, 40, 0x07040706)
    data = bytes(head) + marker('float16', mode, int(mode == CHARGE)) + step(mode)
    data += b''.join(point('float16', t, q, e, mode) for t, q, e in ((1000,0,0),(2000,1000,2000),(4000,3000,6000)))
    if placeholder: data += bytes(16)
    events_offset = len(data)
    for code, value in ((0x803,10000),(0x203,11000),(0x1008,0x00040007),(0x11012,0x07040706),(0x0d06100e,11000)):
        data += struct.pack('<4I', 0xffffcccc, 0x33, code, value)
    restored_offset = len(data)
    data += point('float16', 4500 if placeholder else 3500, 3500 if placeholder else 2500, 6500 if placeholder else 5000, mode)
    data += point('float16',5000,4000,7000,mode)
    return data, events_offset, restored_offset


class RecoveryTests(unittest.TestCase):
    def test_verified_checkpoint_keeps_source_order_and_final_cumulative_value(self):
        for mode in (CHARGE, DISCHARGE):
            blob, _, restored = recovery_sample(mode)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'arbitrary.cex'; path.write_bytes(blob)
                result = extract(path); audit = result['audit']
                self.assertEqual(audit['resume_checkpoint_count'], 1)
                self.assertEqual(audit['record_count'], 5)
                self.assertTrue(audit['cycle_assignment']['source_order_preserved'])
                self.assertEqual(audit['resume_checkpoints'][0]['restored']['offset'], restored)
                self.assertEqual(audit['resume_checkpoints'][0]['recovered_at_offset'], restored+16)
                self.assertGreater(audit['resume_checkpoints'][0]['previous']['time_raw'], audit['resume_checkpoints'][0]['restored']['time_raw'])
                key = 'charge_capacity_mAh' if mode == CHARGE else 'discharge_capacity_mAh'
                self.assertAlmostEqual(result['cycles'][0][key], 4, places=5)
                self.assertEqual(path.read_bytes(), blob)

    def test_corrupted_handshake_or_unmarked_rollback_is_rejected(self):
        original, events, restored = recovery_sample()
        cases = [(events+8,0), (events+16+8,0), (events+16+12,9999),
                 (events+32+12,0x00040001), (events+48+12,0),
                 (events+64+8,0x0d05100e), (events+64+12,11001), (restored,999)]
        for offset, value in cases:
            data = bytearray(original); struct.pack_into('<I',data,offset,value)
            with self.subTest(offset=offset), self.assertRaises(ExtractionError):read_cex(bytes(data))
        with self.assertRaises(ExtractionError): read_cex(original[:events]+original[restored:])

    def test_zero_slot_only_with_complete_handshake_and_continuous_following_point(self):
        original, events, restored = recovery_sample(DISCHARGE, placeholder=True)
        metadata = {}; read_cex(original,metadata=metadata)
        self.assertEqual(metadata['resume_placeholder_count'],1)
        self.assertEqual(metadata['resume_checkpoint_count'],0)
        self.assertEqual(metadata['resume_placeholders'][0]['offset'],events-16)
        for offset, fmt, value in ((events+8,'<I',0),(restored,'<I',3000),(restored+8,'<f',.002),
                                   (restored+6,'<h',1),(restored+12,'<f',float('nan'))):
            data=bytearray(original);struct.pack_into(fmt,data,offset,value)
            with self.subTest(offset=offset),self.assertRaises(ExtractionError):read_cex(bytes(data))
        with self.assertRaises(ExtractionError):read_cex(original[:events-16]+bytes(32)+original[events:])
        with self.assertRaises(ExtractionError):read_cex(original[:events])

    def test_same_handshake_does_not_expand_other_profiles(self):
        data=bytearray(recovery_sample()[0]); data[4:8]=bytes.fromhex('01000400');struct.pack_into('<HH',data,24,5,5)
        with self.assertRaises(ExtractionError):read_cex(bytes(data))

    def test_incomplete_recovery_is_rejected_until_time_and_capacity_recover(self):
        data, _, restored = recovery_sample()
        with self.assertRaisesRegex(ExtractionError, '续测数据不足'):
            read_cex(data[:restored+16])
        for time, capacity in ((3900,4000), (5000,2700)):
            partial = data[:restored+16]+point('float16',time,capacity,5500,CHARGE)
            with self.subTest(time=time), self.assertRaisesRegex(ExtractionError, '续测数据不足'):
                read_cex(partial)


if __name__ == '__main__': unittest.main()
