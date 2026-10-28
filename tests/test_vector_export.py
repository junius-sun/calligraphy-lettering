"""Rendered SVG contracts: transparent holes, tiny strokes, review binding, layout."""
from pathlib import Path
from PIL import Image, ImageDraw
import importlib.util
import io
import json
import sys
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import lettering
import resvg_py

TEMP_ROOT=Path(__file__).resolve().parent/'.tmp'/'vectors'
TEMP_ROOT.mkdir(parents=True,exist_ok=True)

def render(svg):
    return Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg,skip_system_fonts=True))).convert('RGBA')

class VectorTests(unittest.TestCase):
    def tool(self):
        path=SCRIPTS/'svg_export.py'
        self.assertTrue(path.is_file(),'A real path-based SVG exporter is required.')
        spec=importlib.util.spec_from_file_location('svg_export_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def fixture(self,root,text='山水山',graded=False,faint=False):
        image=Image.new('RGBA',(80,80),(0,0,0,0));d=ImageDraw.Draw(image)
        d.rectangle((12,12,58,58),fill=(0,0,0,255));d.rectangle((24,24,44,44),fill=(0,0,0,0))
        d.rectangle((64,18,67,45),fill=(0,0,0,128 if graded else 255))
        if faint:image.putalpha(image.getchannel('A').point(lambda a:a//8))
        image.save(root/'input.png')
        selection=dict(text=text,positions=[dict(index=i,character=ch,input='input.png',character_verified=True,verification_note='Synthetic fixture, not real Chinese lettering.',source=dict(kind='user-provided')) for i,ch in enumerate(text)])
        (root/'selection.json').write_text(json.dumps(selection),encoding='utf-8')
        job=root/'job';t=lettering.prepare(root/'selection.json',job)
        for p in t['positions']:p['processing_review']=dict(status='accepted',note='Synthetic fixture checked.')
        (job/'task.json').write_text(json.dumps(t),encoding='utf-8');lettering.compose(job)
        return job

    def accept(self,job,result):
        report=dict(positions=[dict(index=g['index'],glyph_sha256=g['glyph_sha256'],svg_sha256=g['svg_sha256'],status='accepted',note='Rendered fixture checked for inner holes and fine strokes.') for g in result['glyphs'] if g.get('svg_sha256')])
        (job/'vector-review.json').write_text(json.dumps(report),encoding='utf-8')

    def test_paths_preserve_transparent_holes_flying_white_and_one_pixel_dot(self):
        tool=self.tool();im=Image.new('RGBA',(70,70),(0,0,0,0));d=ImageDraw.Draw(im)
        d.rectangle((10,10,50,50),fill='black');d.rectangle((22,22,38,38),fill=(0,0,0,0))
        d.line((14,15,14,45),fill=(0,0,0,0),width=1);im.putpixel((60,60),(0,0,0,255))
        svg=tool.trace_glyph(im,alpha_threshold=96,mode='polygon')
        root=ET.fromstring(svg);self.assertTrue(root.findall('.//{http://www.w3.org/2000/svg}path'))
        self.assertFalse(root.findall('.//{http://www.w3.org/2000/svg}image'))
        a=render(svg)
        for xy in [(0,0),(30,30),(14,28)]:self.assertEqual(a.getpixel(xy)[3],0)
        self.assertGreater(a.getpixel((18,18))[3],240);self.assertGreater(a.getpixel((60,60))[3],200)
        self.assertEqual(a.size,im.size)

    def test_alpha_threshold_is_explicit_reversible_and_does_not_trace_transparent_rgb(self):
        tool=self.tool();im=Image.new('RGBA',(60,40),(0,0,0,0));d=ImageDraw.Draw(im)
        d.rectangle((8,8,23,30),fill=(0,0,0,255));d.rectangle((34,8,50,30),fill=(0,0,0,128));before=im.tobytes()
        low=render(tool.trace_glyph(im,alpha_threshold=96,mode='polygon'));high=render(tool.trace_glyph(im,alpha_threshold=200,mode='polygon'))
        self.assertGreater(low.getpixel((40,20))[3],240);self.assertEqual(high.getpixel((40,20))[3],0)
        self.assertEqual(low.getpixel((0,0))[3],0);self.assertEqual(before,im.tobytes())
        for n in [0,256,True]:
            with self.assertRaises(ValueError):tool.trace_glyph(im,alpha_threshold=n)

    def test_dual_delivery_requires_vector_review_and_uses_existing_layout(self):
        tool=self.tool()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root=Path(temp);job=self.fixture(root);pngs={p.name:p.read_bytes() for p in (job/'exports').glob('*.png')}
            a=tool.vectorize(job,mode='polygon');self.assertEqual(a['status'],'draft');self.assertEqual(len(a['glyphs']),3)
            self.assertTrue(all('DRAFT-' in f for f in a['files'] if f.endswith('.svg')))
            self.accept(job,a);b=tool.vectorize(job,mode='polygon');self.assertEqual(b['status'],'complete')
            self.assertEqual(len([f for f in b['files'] if f.endswith('.svg')]),9)
            self.assertFalse(any('DRAFT-' in f for f in b['files']))
            self.assertEqual(pngs,{p.name:p.read_bytes() for p in (job/'exports').glob('*.png')})
            composition=json.loads((job/'composition.json').read_text(encoding='utf-8'))
            for name,plan in composition['segments'][0]['layouts'].items():
                svgpath=next(job/f for f in b['files'] if f.endswith(f'{name}-transparent.svg'))
                xml=ET.parse(svgpath).getroot();groups=xml.findall('{http://www.w3.org/2000/svg}g')
                self.assertEqual([int(g.attrib['data-index']) for g in groups],[0,1,2])
                self.assertEqual(xml.attrib['viewBox'],f"0 0 {plan['width']} {plan['height']}")
                self.assertTrue(all(g.attrib['transform'].startswith(f"translate({p['x']} {p['y']})") for g,p in zip(groups,plan['items'])))
                self.assertEqual(render(svgpath.read_text(encoding='utf-8')).getpixel((0,0))[3],0)
                white=render(svgpath.with_name(svgpath.name.replace('-transparent.svg','-white.svg')).read_text(encoding='utf-8'))
                self.assertEqual(white.getchannel('A').getextrema(),(255,255))
            self.assertTrue((job/'vectors/preview.png').is_file())

    def test_changed_threshold_revokes_reviews_and_removes_only_old_generated_files(self):
        tool=self.tool()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            job=self.fixture(Path(temp),graded=True);a=tool.vectorize(job,alpha_threshold=96,mode='polygon');self.accept(job,a)
            b=tool.vectorize(job,alpha_threshold=96,mode='polygon');self.assertEqual(b['status'],'complete')
            foreign=job/'vectors/keep.svg';foreign.write_text('<svg/>',encoding='utf-8')
            c=tool.vectorize(job,alpha_threshold=200,mode='polygon');self.assertEqual(c['status'],'draft')
            self.assertTrue(foreign.exists());self.assertTrue(all(not (job/f).exists() for f in b['files'] if f.endswith('.svg')))
            self.assertTrue(all(g['review']['status']=='pending' for g in c['glyphs']))

    def test_tampered_glyph_and_stale_layout_are_rejected(self):
        tool=self.tool()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            job=self.fixture(Path(temp));t=json.loads((job/'task.json').read_text(encoding='utf-8'))
            t['positions'][0]['layout']['dx']=7;(job/'task.json').write_text(json.dumps(t),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'compose'):tool.vectorize(job)
            lettering.compose(job);(job/t['positions'][0]['glyph']['path']).write_bytes(b'tampered')
            with self.assertRaises(ValueError):tool.vectorize(job)

    def test_pending_pngs_are_not_vectorized_or_passed_as_finals(self):
        tool=self.tool()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            job=self.fixture(Path(temp));t=json.loads((job/'task.json').read_text(encoding='utf-8'))
            t['positions'][1]['processing_review']['status']='pending';(job/'task.json').write_text(json.dumps(t),encoding='utf-8');lettering.compose(job)
            r=tool.vectorize(job);self.assertEqual(r['status'],'draft');self.assertFalse(r['glyphs'][1].get('svg_sha256'))
            self.assertIn(1,r['missing_or_unreviewed'])

    def test_cli_exports_vectors_and_reports_draft_status(self):
        self.tool()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            job=self.fixture(Path(temp));p=subprocess.run([sys.executable,str(SCRIPTS/'lettering.py'),'vectorize','--job',str(job),'--mode','polygon'],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)['status'],'draft')
            self.assertTrue((job/'vectorization.json').is_file())

    def test_default_spline_retains_tiny_marks_and_clear_counter(self):
        tool=self.tool();im=Image.new('RGBA',(50,50));d=ImageDraw.Draw(im)
        d.rectangle((6,6,32,32),fill='black');d.rectangle((14,14,24,24),fill=(0,0,0,0));im.putpixel((42,42),(0,0,0,255))
        rendered=render(tool.trace_glyph(im))
        self.assertEqual(rendered.getpixel((19,19))[3],0)
        self.assertGreater(rendered.getpixel((42,42))[3],128)

    def test_review_for_a_different_png_hash_is_not_accepted(self):
        tool=self.tool()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            job=self.fixture(Path(temp));r=tool.vectorize(job);self.accept(job,r)
            report=json.loads((job/'vector-review.json').read_text(encoding='utf-8'))
            report['positions'][0]['glyph_sha256']='not-the-reviewed-PNG'
            (job/'vector-review.json').write_text(json.dumps(report),encoding='utf-8')
            r=tool.vectorize(job);self.assertEqual(r['glyphs'][0]['status'],'draft')
            self.assertEqual(r['glyphs'][1]['status'],'ready')
        with self.assertRaisesRegex(ValueError,'No ink'):tool.trace_glyph(Image.new('RGBA',(20,20)))

    def test_faint_glyphs_report_missing_vectors_and_keep_png_exports(self):
        tool=self.tool()
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            job=self.fixture(Path(temp),faint=True)
            pngs={p.name:p.read_bytes() for p in (job/'exports').glob('*.png')}
            result=tool.vectorize(job,alpha_threshold=96)
            self.assertEqual(result['status'],'draft')
            self.assertTrue(all(g['status']=='missing' and 'No ink' in g['reason'] for g in result['glyphs']))
            self.assertEqual(pngs,{p.name:p.read_bytes() for p in (job/'exports').glob('*.png')})

if __name__=='__main__':unittest.main()
