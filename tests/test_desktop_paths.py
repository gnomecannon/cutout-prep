import tempfile
import unittest
from pathlib import Path

from cutout_prep.desktop_paths import create_results_folder


class DesktopResultFolders(unittest.TestCase):
    def test_repeated_loads_preserve_previous_results_and_originals(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'Rock photos'
            source.mkdir()
            original = source / 'photo.jpg'
            original.write_bytes(b'original photograph')
            first = create_results_folder(source, 'Scan Masks')
            previous = first / 'hand-edited mask.png'
            previous.write_bytes(b'keep this edit')
            second = create_results_folder(source, 'Scan Masks')
            self.assertEqual(first.parent, source.parent.resolve())
            self.assertEqual(second.name, 'Rock photos - Scan Masks (2)')
            self.assertEqual(previous.read_bytes(), b'keep this edit')
            self.assertEqual(original.read_bytes(), b'original photograph')
            self.assertEqual(list(second.iterdir()), [])

    def test_name_collision_with_a_regular_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'Leaves'
            source.mkdir()
            existing = source.parent / 'Leaves - Cutouts'
            existing.write_bytes(b'not an output directory')
            output = create_results_folder(source, 'Cutouts')
            self.assertEqual(output.name, 'Leaves - Cutouts (2)')
            self.assertEqual(existing.read_bytes(), b'not an output directory')

    def test_missing_input_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                create_results_folder(Path(temp) / 'Missing', 'Scan Masks')
            self.assertEqual(list(Path(temp).iterdir()), [])
