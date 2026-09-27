import json
import os
from pathlib import Path
import tempfile
import time
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from niri_translate.theme import DARK,LIGHT,ThemeWatcher,map_palette

class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_semantic_foreground_background_pairs(self):
        for colors,dark in ((LIGHT,False),(DARK,True)):
            mapped=map_palette(colors)
            self.assertEqual(mapped['dark'],dark)
            self.assertEqual(mapped['ink'],colors['on_surface'])
            self.assertEqual(mapped['on_accent'],colors['on_primary'])
            self.assertEqual(mapped['footer_text'],colors['on_primary_container'])
    def test_atomic_palette_switch_survives_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config=root/'config.json';colors=root/'colors.json'
            config.write_text('{"theme":{"mode":"light"}}');colors.write_text(json.dumps(LIGHT))
            watcher=ThemeWatcher(files=(config,colors));seen=[];watcher.updated.connect(seen.append)
            def replace(palette):
                tmp=root/'new.json';tmp.write_text(json.dumps(palette));tmp.replace(colors)
                end=time.monotonic()+2
                while time.monotonic()<end:
                    self.app.processEvents();time.sleep(.01)
                    if watcher.current['dark']==(palette==DARK):return
                self.fail('theme did not update')
            replace(DARK);self.assertTrue(watcher.current['dark'])
            replace(LIGHT);self.assertFalse(watcher.current['dark'])
            self.assertGreaterEqual(len(seen),2)
            watcher.deleteLater();self.app.processEvents()

if __name__=='__main__':unittest.main()
