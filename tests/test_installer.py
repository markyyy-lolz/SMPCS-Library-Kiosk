import tempfile
from pathlib import Path
import unittest
import zipfile
from shared.installer import checksum_for,extract_verified,replace_install,sha256,validate_archive

class InstallerTests(unittest.TestCase):
    def archive(self,root,extra=None):
        path=Path(root)/'update.zip'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('SMPCS_Library/SMPCS_Library.exe',b'example')
            z.writestr('SMPCS_Library/_internal/example.dll',b'library')
            if extra:
                entry=zipfile.ZipInfo()
                entry.filename=extra  # Preserve malformed separators on Windows too.
                z.writestr(entry,b'bad')
        return path
    def test_hash_and_extract(self):
        with tempfile.TemporaryDirectory() as root:
            archive=self.archive(root);digest=sha256(archive)
            self.assertEqual(checksum_for(digest+'  update.zip','update.zip'),digest)
            target=extract_verified(archive,digest,Path(root)/'new')
            self.assertTrue((target/'SMPCS_Library.exe').exists())
            with self.assertRaises(ValueError):extract_verified(archive,'0'*64,Path(root)/'wrong')
            self.assertFalse((Path(root)/'wrong').exists())
    def test_reject_unsafe_zip_paths(self):
        for name in ('../outside','SMPCS_Library/../../outside','/absolute','SMPCS_Library/x:ads','SMPCS_Library/CON','SMPCS_Library//duplicate','SMPCS_Library/bad\\file'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                with self.assertRaises(ValueError):validate_archive(self.archive(root,name))
    def test_rollback_and_preserve_config(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'app';target.mkdir();(target/'version').write_text('old');(target/'.env').write_text('local')
            staged=Path(root)/'new';staged.mkdir();(staged/'version').write_text('new')
            def fail(_):raise RuntimeError('new app cannot start')
            with self.assertRaises(RuntimeError):replace_install(target,staged,fail)
            self.assertEqual((target/'version').read_text(),'old')
            self.assertEqual((target/'.env').read_text(),'local')
    def test_success_keeps_backup(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'app';target.mkdir();(target/'version').write_text('old')
            staged=Path(root)/'new';staged.mkdir();(staged/'version').write_text('new')
            backup=replace_install(target,staged,lambda p:self.assertEqual((p/'version').read_text(),'new'))
            self.assertEqual((backup/'version').read_text(),'old')
            self.assertEqual((target/'version').read_text(),'new')
