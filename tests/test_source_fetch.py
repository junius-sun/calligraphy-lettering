"""Fixed-provider routing, bounded retrieval and cache behavior without live sites."""
from pathlib import Path
import importlib.util
import io,json,sys,tempfile,unittest
from PIL import Image,ImageDraw
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
TEMP=Path(__file__).resolve().parent/'.tmp'/'fetch';TEMP.mkdir(parents=True,exist_ok=True)

def picture():
    im=Image.new('RGB',(200,200),'white');ImageDraw.Draw(im).rectangle((35,30,165,170),fill='black');b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()

def page(ch,author='赵孟頫'):
    return f'<title>{ch}字书法字典</title><div class="title">“{ch}” 字 行书书法</div><div class="cont f12"><ul class="oul shuimg"><li><img alt="{author}" src="/images/{ch}.png"></li></ul></div>'

class FetchTests(unittest.TestCase):
    def tool(self):
        f=SCRIPTS/'fetch_sources.py';self.assertTrue(f.is_file(),'Fixed-source fetch helper is required.')
        spec=importlib.util.spec_from_file_location('fetch_sources_test',f);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

    def test_parser_keeps_requested_character_style_and_fixed_host(self):
        m=self.tool();s=page('山')+page('水')+page('山','王羲之').replace('行书','草书')
        s+=page('山','bad').replace('/images/山.png','https://outside.example/image.png')
        rows=m.parse_shufa5(s,'https://www.shufa5.com/entry.html','山','行书')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['author'],'赵孟頫')
        self.assertEqual(m.parse_shufa5(page('間'),'https://www.shufa5.com/e.html','间','行书'),[])

    def test_repeated_positions_query_once_cache_bytes_and_never_auto_verify(self):
        m=self.tool();calls=[]
        def request(url,data,timeout):
            calls.append((url,data))
            if data:
                from urllib.parse import parse_qs
                ch=parse_qs(data.decode())['q'][0];return page(ch).encode(),f'https://www.shufa5.com/{ch}.html'
            return picture(),url
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            r=Path(temp);cache=r/'cache';result=m.fetch('山水山',r/'first',cache_dir=cache,transport=request,max_candidates=1)
            self.assertEqual(len(calls),4)
            selected=json.loads((r/'first/selection.json').read_text(encoding='utf-8'))
            self.assertEqual([p['index'] for p in selected['positions']],[0,1,2])
            self.assertEqual(selected['positions'][0]['input'],selected['positions'][2]['input'])
            self.assertTrue(all(not p['character_verified'] for p in selected['positions']))
            def offline(*args):self.fail('A valid cached candidate should not need the network.')
            second=m.fetch('山水山',r/'second',cache_dir=cache,transport=offline,max_candidates=1)
            self.assertEqual(second['network_requests'],0);self.assertEqual(second['cache_hits'],2)
            self.assertEqual(result['candidate_characters'],2)

    def test_only_missing_character_uses_secondary_source_with_detail_provenance(self):
        m=self.tool();calls=[]
        def request(url,data,timeout):
            calls.append(url)
            if data:
                from urllib.parse import parse_qs
                ch=parse_qs(data.decode())['q'][0]
                return (page(ch).encode(),f'https://www.shufa5.com/{ch}.html') if ch=='山' else (b'<script>location.href="/"</script>',url)
            if 'index.asp?' in url:
                return '<a href="view.asp?id=42" class="card"><img src="ziku/qing.jpg"><div class="card-char">清</div><div class="card-style">行书</div><div class="card-desc">元 赵孟頫《前后...</div></a>'.encode('gbk'),url
            if 'view.asp' in url:return '<meta charset="gb2312"><img src=ziku/qing.jpg><div class="desc-text">元 赵孟頫《前后赤壁赋》</div>'.encode('gbk'),url
            return picture(),url
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            r=Path(temp);result=m.fetch('山清',r/'job',cache_dir=r/'cache',transport=request,max_candidates=1)
            self.assertEqual(sum('index.asp?' in u for u in calls),1)
            data=json.loads((r/'job/candidates.json').read_text(encoding='utf-8'))
            self.assertEqual(data['清'][0]['source']['work'],'前后赤壁赋')
            self.assertEqual(result['candidate_characters'],2)

    def test_network_failure_is_not_reported_as_no_glyph_and_budget_stops_requests(self):
        m=self.tool()
        def fail(*args):raise TimeoutError('test timeout')
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            r=Path(temp);result=m.fetch('山',r/'bad',cache_dir=r/'cache',transport=fail,max_candidates=1)
            attempts=json.loads((r/'bad/fetch-report.json').read_text(encoding='utf-8'))['attempts']['山']
            self.assertTrue(all(a['status']=='unavailable' for a in attempts))
            def forbidden(*args):self.fail('Budget exhausted: no new request may start.')
            stopped=m.fetch('水',r/'stopped',cache_dir=r/'cache',transport=forbidden,budget_seconds=0,max_candidates=1)
            self.assertEqual(stopped['network_requests'],0);self.assertEqual(stopped['candidate_characters'],0)

    def test_strict_author_never_substitutes_and_tampered_cache_is_not_trusted(self):
        m=self.tool()
        def request(url,data,timeout):return (page('山').encode(),url) if data else (picture(),url)
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            r=Path(temp);m.fetch('山',r/'one',cache_dir=r/'cache',transport=request,sources=['shufa5'],max_candidates=1)
            for p in (r/'cache/blobs').iterdir():p.write_bytes(b'tampered')
            second=m.fetch('山',r/'two',cache_dir=r/'cache',transport=request,sources=['shufa5'],max_candidates=1)
            self.assertGreater(second['network_requests'],0)
            m.fetch('山',r/'strict',cache_dir=r/'cache',transport=request,sources=['shufa5'],author='苏轼',strict_author=True,max_candidates=1)
            selected=json.loads((r/'strict/selection.json').read_text(encoding='utf-8'))
            self.assertIsNone(selected['positions'][0]['input'])

    def test_unavailable_site_is_not_retried_for_every_character(self):
        m=self.tool();calls=[]
        def fail(url,data,timeout):calls.append(url);raise TimeoutError('offline')
        with tempfile.TemporaryDirectory(dir=TEMP) as temp:
            r=Path(temp);m.fetch('明月松間照清泉石上流',r/'job',cache_dir=r/'cache',transport=fail,sources=['shufa5'])
            self.assertLessEqual(len(calls),4)

if __name__=='__main__':unittest.main()
