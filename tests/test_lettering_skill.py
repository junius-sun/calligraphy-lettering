"""Observable image, provenance, layout and standalone CLI contracts."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image, ImageDraw

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/lettering.py'
TEMP_ROOT = Path(__file__).resolve().parent / '.tmp' / 'lettering'
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

def engine():
    assert SCRIPT.is_file(), '需要实现独立的 lettering.py prepare/compose 工具'
    spec = importlib.util.spec_from_file_location('lettering', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def strokes(background='white', ink='black', size=(120, 100)):
    image = Image.new('RGBA', size, background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((25, 20, 35, 75), fill=ink)
    draw.rectangle((25, 65, 90, 75), fill=ink)
    draw.rectangle((80, 30, 90, 75), fill=ink)
    return image

class LetteringTests(unittest.TestCase):
    def test_light_dark_and_yellow_backgrounds_keep_strokes(self):
        tool = engine()
        results = []
        for bg, ink in [('white', 'black'), ('black', 'white'), ((229, 210, 160), (20, 20, 20))]:
            clean, meta = tool.clean_image(strokes(bg, ink))
            self.assertGreater(clean.getchannel('A').getextrema()[1], 230)
            self.assertEqual(clean.getpixel((0, 0))[3], 0)
            self.assertTrue(all(p[:3] == (0, 0, 0) for p in clean.get_flattened_data()))
            results.append(clean.size)
        self.assertEqual(results[0], results[1])

    def test_existing_alpha_and_flying_white_are_preserved(self):
        tool = engine()
        image = Image.new('RGBA', (30, 30), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((5, 5, 24, 24), fill=(0, 0, 0, 128))
        image.putpixel((14, 14), (0, 0, 0, 0))
        clean, meta = tool.clean_image(image, padding=0)
        self.assertEqual(clean.size, (20, 20))
        self.assertEqual(clean.getpixel((0, 0))[3], 128)
        self.assertEqual(clean.getpixel((9, 9))[3], 0)

    def test_empty_images_and_out_of_bounds_crops_fail(self):
        tool = engine()
        for image in [Image.new('RGBA', (20, 20), 'white'), Image.new('RGBA', (20, 20), (0, 0, 0, 0))]:
            with self.assertRaises(ValueError): tool.clean_image(image)
        for box in [[-1, 0, 10, 10], [0, 0, 121, 90], [10, 10, 5, 20]]:
            with self.assertRaises(ValueError): tool.clean_image(strokes(), crop=box)

    def test_threshold_is_reversible_and_preserves_soft_edges(self):
        tool = engine()
        image = strokes(ink=(165, 165, 165))
        before = image.tobytes()
        low, _ = tool.clean_image(image, cutoff=180)
        high, _ = tool.clean_image(image, cutoff=245)
        self.assertLess(sum(low.getchannel('A').get_flattened_data()), sum(high.getchannel('A').get_flattened_data()))
        self.assertTrue(any(0 < a < 255 for a in high.getchannel('A').get_flattened_data()))
        self.assertEqual(before, image.tobytes())

    def test_local_background_normalization_handles_slow_paper_gradient(self):
        tool = engine()
        image = Image.new('RGB', (240, 140))
        for x in range(240):
            for y in range(140): image.putpixel((x, y), (160+x//3, 150+x//3, 125+x//3))
        ImageDraw.Draw(image).rectangle((80, 35, 95, 110), fill=(15, 15, 15))
        clean, meta = tool.clean_image(image)
        self.assertLess(clean.width, 60)
        self.assertGreater(clean.height, 70)

    def make_job(self, root, text='山水山', author='苏轼', strict=False):
        root = Path(root)
        image = root/'ink.png'; strokes().save(image)
        positions = []
        for i, char in enumerate(text):
            positions.append({'index': i, 'character': char, 'input': 'ink.png', 'character_verified': True,
                'verification_note': 'Synthetic labeled stroke fixture for layout testing.',
                'source': {'page_url': 'https://example.com/work', 'author': author, 'work': '测试原帖', 'script': '行书', 'author_status': 'source-labeled'}})
        selection = root/'selection.json'
        selection.write_text(json.dumps({'text': text, 'author_requirement': {'name': '苏轼', 'strict': strict}, 'positions': positions}, ensure_ascii=False), encoding='utf-8')
        return selection

    def accept(self, job):
        task = json.loads((job/'task.json').read_text(encoding='utf-8'))
        for p in task['positions']:
            if p['status'] == 'ready': p['processing_review'] = {'status': 'accepted', 'note': 'Test fixture checked.'}
        (job/'task.json').write_text(json.dumps(task, ensure_ascii=False), encoding='utf-8')
        return task

    def test_prepare_preserves_bytes_provenance_and_deduplicates_originals(self):
        tool = engine()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp); selected = self.make_job(root); job = root/'job'
            task = tool.prepare(selected, job)
            self.assertEqual(len(list((job/'originals').iterdir())), 1)
            self.assertEqual(task['text'], '山水山')
            for p in task['positions']:
                self.assertEqual((job/p['original']['path']).read_bytes(), (root/'ink.png').read_bytes())
                self.assertEqual(p['original']['sha256'], hashlib.sha256((root/'ink.png').read_bytes()).hexdigest())
                self.assertEqual(p['source']['author_status'], 'source-labeled')
                self.assertEqual(p['processing_review']['status'], 'pending')
            with self.assertRaises(FileExistsError): tool.prepare(selected, job)

    def test_unverified_wrong_author_and_failed_sources_cannot_be_final(self):
        tool = engine()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp); selected = self.make_job(root, author='米芾', strict=True)
            data = json.loads(selected.read_text(encoding='utf-8'))
            data['positions'][1].update(input=None, attempts=[{'page_url': 'https://example.com/expired', 'status': 'expired', 'note': 'Signed image expired; replacement unavailable.'}])
            data['positions'][2]['character_verified'] = False
            selected.write_text(json.dumps(data), encoding='utf-8')
            job = root/'job'; task = tool.prepare(selected, job)
            self.assertTrue(all(p['status'] == 'missing' for p in task['positions']))
            result = tool.compose(job)
            self.assertEqual(result['status'], 'draft')
            self.assertTrue(all('DRAFT' in f for f in result['files']))
            self.assertIn('expired', (job/'sources.md').read_text(encoding='utf-8'))

    def test_soft_author_substitution_is_reported(self):
        tool = engine()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp); selected = self.make_job(root, author='米芾')
            task = tool.prepare(selected, root/'job')
            self.assertTrue(all(p['status'] == 'ready' for p in task['positions']))
            self.assertTrue(all(p['substitution'] for p in task['positions']))

    def test_compose_requires_visual_review_and_detects_tampered_glyphs(self):
        tool = engine()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp); selected = self.make_job(root); job = root/'job'
            tool.prepare(selected, job)
            self.assertEqual(tool.compose(job)['status'], 'draft')
            task = self.accept(job)
            self.assertEqual(tool.compose(job)['status'], 'complete')
            (job/task['positions'][0]['glyph']['path']).write_bytes(b'changed')
            with self.assertRaises(ValueError): tool.compose(job)

    def test_composition_order_ratios_no_upscale_and_independent_positions(self):
        tool = engine()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp); selected = self.make_job(root); job = root/'job'
            tool.prepare(selected, job); task = self.accept(job)
            task['positions'][0]['layout'] = {'scale': .5, 'dx': -220, 'dy': 110}
            (job/'task.json').write_text(json.dumps(task), encoding='utf-8')
            result = tool.compose(job)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(len(result['files']), 6)
            layouts = result['segments'][0]['layouts']
            for name, layout in layouts.items():
                self.assertEqual([p['index'] for p in layout['items']], [0, 1, 2])
                for item in layout['items']:
                    self.assertGreaterEqual(item['x'], 0); self.assertGreaterEqual(item['y'], 0)
                    self.assertLessEqual(item['x']+item['width'], layout['width'])
                    self.assertLessEqual(item['y']+item['height'], layout['height'])
                    self.assertLessEqual(item['width'], task['positions'][item['index']]['glyph']['width'])
                self.assertLess(layout['items'][0]['width'], layout['items'][2]['width'])
            for f in result['files']:
                with Image.open(job/f) as img:
                    if 'transparent' in f: self.assertEqual(img.getpixel((0, 0))[3], 0)
                    else: self.assertEqual(img.convert('RGB').getpixel((0, 0)), (255, 255, 255))

    def test_more_than_twelve_characters_are_segmented_without_loss(self):
        tool = engine()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp); text = '山'*13; selected = self.make_job(root, text=text); job=root/'job'
            tool.prepare(selected, job); self.accept(job); result=tool.compose(job)
            self.assertEqual([len(s['indices']) for s in result['segments']], [12, 1])
            self.assertEqual([i for s in result['segments'] for i in s['indices']], list(range(13)))

    def test_cli_runs_without_project_or_server(self):
        engine()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root=Path(temp); selected=self.make_job(root); job=root/'job'
            a=subprocess.run([sys.executable,str(SCRIPT),'prepare','--selection',str(selected),'--output',str(job)],cwd=root,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(a.returncode,0,a.stderr)
            self.accept(job)
            b=subprocess.run([sys.executable,str(SCRIPT),'compose','--job',str(job)],cwd=root,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(b.returncode,0,b.stderr)
            self.assertEqual(json.loads(b.stdout)['ready'],3)
            self.assertTrue((job/'sources.md').is_file())
            self.assertTrue((job/'preview.png').is_file())

    def test_saved_selection_rebuilds_from_preserved_originals_after_downloads_are_gone(self):
        tool=engine()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root=Path(temp); selected=self.make_job(root); job=root/'job'
            tool.prepare(selected,job)
            (root/'ink.png').unlink()
            rebuilt=tool.prepare(job/'selection.json',root/'rebuild')
            self.assertTrue(all(p['status']=='ready' for p in rebuilt['positions']), 'Saved selection must use preserved originals, not the original download directory.')

    def test_exif_orientation_is_applied_before_crop_coordinates(self):
        tool=engine(); image=strokes(size=(120,100)); image.getexif()[274]=6
        clean, meta=tool.clean_image(image)
        self.assertEqual(meta['oriented_size'],[100,120])
        self.assertEqual(meta['crop'],[0,0,100,120])
        self.assertEqual(image.size,(120,100))

if __name__ == '__main__': unittest.main()
