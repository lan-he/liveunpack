import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
import live_export as app


def box(kind, payload=b'', extended=False):
    if extended:
        return struct.pack('>I4sQ', 1, kind, len(payload)+16)+payload
    return struct.pack('>I4s', len(payload)+8, kind)+payload


def video(extended=False):
    return box(b'ftyp', b'mp42\0\0\0\0isommp42')+box(b'moov', b'metadata')+box(b'mdat', b'original video bytes', extended)


def photo(v=None):
    return b'\xff\xd8synthetic jpeg\xff\xd9'+(v if v is not None else video())


class ExtractionTests(unittest.TestCase):
    def test_exact_bytes(self):
        self.assertEqual(app.extract(photo()), video())

    def test_extended_mdat(self):
        self.assertEqual(app.extract(photo(video(True))), video(True))

    def test_xmp_preserves_vendor_trailer(self):
        resource = video(True)+b'vivo-vendor-trailer'
        xmp = f'<Container:Item Item:Mime="video/mp4" Item:Length="{len(resource)}"/>'.encode()
        self.assertEqual(app.extract(b'\xff\xd8'+xmp+b'\xff\xd9'+resource), resource)

    def test_ordinary_photo_rejected(self):
        with self.assertRaises(ValueError):
            app.extract(b'\xff\xd8ordinary\xff\xd9')

    def test_mp4_input_rejected(self):
        with self.assertRaises(ValueError):
            app.extract(video())

    def test_truncated_video_rejected(self):
        with self.assertRaises(ValueError):
            app.extract(photo()[:-5])

    def test_false_marker_before_real_video(self):
        self.assertEqual(app.extract(b'\xff\xd8garbageftypgarbage'+photo()[2:]), video())

    def test_trailing_non_mp4_excluded_without_xmp(self):
        self.assertEqual(app.extract(photo()+b'unknown trailer'), video())

    def test_zero_size_mdat(self):
        v = box(b'ftyp', b'mp42isom')+box(b'moov')+struct.pack('>I4s', 0, b'mdat')+b'payload'
        self.assertEqual(app.extract(photo(v)), v)

    def test_duplicate_names_and_path_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            a = app.save(photo(), '../../test.jpg', out)
            b = app.save(photo(), 'test.jpg', out)
            self.assertNotEqual(a['output'], b['output'])
            self.assertEqual(Path(a['output']).parent, out)
            self.assertEqual(Path(a['output']).read_bytes(), video())

    def test_zip_batch_skips_resource_forks_and_continues(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z:
            z.writestr('__MACOSX/._a.jpg', b'ignored')
            z.writestr('folder/a.jpg', photo())
            z.writestr('folder/b.jpg', b'ordinary')
            z.writestr('folder/c.JPG', photo())
        with tempfile.TemporaryDirectory() as directory:
            rows = app.process(stream.getvalue(), 'photos.zip', Path(directory))
            self.assertEqual(len(rows), 3)
            self.assertEqual(sum(r['status']=='成功' for r in rows), 2)

    def test_cli_missing_file_returns_failure(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['missing-photo.jpg']), 1)

    def test_cli_recursive_report_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'input'/'sub'/'photo.jpg'
            source.parent.mkdir(parents=True)
            source.write_bytes(photo())
            report = root/'report.json'
            with contextlib.redirect_stdout(io.StringIO()):
                code = app.main([str(root/'input'), '-o', str(root/'output'), '--report', str(report)])
            self.assertEqual(code, 0)
            self.assertEqual(source.read_bytes(), photo())
            self.assertEqual(json.loads(report.read_text())[0]['bytes'], len(video()))


if __name__ == '__main__':
    unittest.main()
