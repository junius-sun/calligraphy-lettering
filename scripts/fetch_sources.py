"""Bounded candidate retrieval from fixed public sites. No visual auto-approval."""
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urljoin, urlsplit, quote_from_bytes
import hashlib, html, io, json, re, shutil, threading, time
from PIL import Image, ImageDraw
import lettering

HOSTS = {'www.shufa5.com', 'shufa5.com', '9610.com', 'www.9610.com'}
DEFAULT_SOURCES = ['shufa5', '9610']
ALIASES = {'赵子昂': '赵孟頫', '文徵明': '文征明'}
RANK = ['赵孟頫', '文征明', '王羲之', '米芾', '敬世江']


def plain(s):
    return html.unescape(re.sub('<[^>]+>', '', s)).strip()


def fixed_url(base, path):
    url = urljoin(base, html.unescape(path)); p = urlsplit(url)
    if p.scheme not in ('http', 'https') or p.hostname not in HOSTS or p.username or p.password:
        raise ValueError('URL is outside the fixed source sites.')
    return url


def author_name(label):
    return ALIASES.get(label, label)


def parse_shufa5(text, page_url, character, script):
    rows = []
    sections = re.findall(r'<div class="title">([^<]+)</div>\s*<div class="cont f12">\s*<ul class="oul shuimg">(.*?)</ul>', text, re.S)
    for title, body in sections:
        if not re.search(r'[“"\s]'+re.escape(character)+r'[”"\s]', title) or script not in title:
            continue
        for author, src in re.findall(r'<img\b[^>]*alt="([^"]*)"[^>]*src="([^"]*)"', body):
            try: image_url = fixed_url(page_url, src)
            except ValueError: continue
            rows.append({'author': author_name(plain(author)), 'author_label': plain(author), 'script': script,
                'page_url': page_url, 'image_url': image_url, 'work': '来源页未提供原帖名称', 'provider': 'shufa5'})
    return rows


def parse_9610(text, page_url, character, script):
    rows = []
    for path, body in re.findall(r'<a\b[^>]*href="([^"]*view\.asp\?id=\d+)"[^>]*class="card"[^>]*>(.*?)</a>', text, re.S):
        char = re.search(r'class="card-char">(.*?)</div>', body, re.S)
        style = re.search(r'class="card-style">(.*?)</div>', body, re.S)
        image = re.search(r'<img\b[^>]*src="([^"]+)"', body)
        if not char or plain(char[1]) != character or not style or plain(style[1]) != script or not image:
            continue
        desc = re.search(r'class="card-desc">(.*?)</div>', body, re.S)
        description = plain(desc[1]) if desc else ''
        author = re.search(r'^(?:元|明|清|宋|唐|晋|隋|汉|北宋|南宋|东晋|南北朝)\s+([^\s《.]+)', description)
        label = author[1] if author else '未知'
        try: url = fixed_url(page_url, path); image_url = fixed_url(page_url, image[1])
        except ValueError: continue
        rows.append({'author': author_name(label), 'author_label': label, 'script': script,
            'page_url': url, 'image_url': image_url, 'work': '待核对详情页', 'provider': '9610'})
    return rows


def transport(url, data, timeout):
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': urlsplit(url).scheme+'://'+urlsplit(url).netloc+'/'}
    if data is not None: headers['Content-Type'] = 'application/x-www-form-urlencoded'
    with urlopen(Request(url, data=data, headers=headers), timeout=timeout) as response:
        raw = response.read(6_000_001); final_url = response.url
    if len(raw) > 6_000_000: raise ValueError('Response exceeds the 6 MB candidate limit.')
    fixed_url(final_url, final_url)
    return raw, final_url


def fetch(text, output, script='行书', author=None, strict_author=False, max_candidates=2,
          budget_seconds=90, cache_dir=None, sources=None, transport=transport):
    chars = lettering.text_characters(text); text = ''.join(chars)
    if script not in ('行书', '楷书', '草书', '隶书', '篆书'): raise ValueError('Choose a supported script.')
    if type(max_candidates) is not int or not 1 <= max_candidates <= 3: raise ValueError('max_candidates must be 1—3.')
    if not 0 <= budget_seconds <= 600: raise ValueError('budget_seconds must be 0—600.')
    if strict_author and not author: raise ValueError('strict_author requires an author.')
    sources = DEFAULT_SOURCES if sources is None else sources
    if not sources or len(set(sources)) != len(sources) or any(p not in DEFAULT_SOURCES for p in sources):
        raise ValueError('Automatic sources are shufa5 and 9610 only.')
    output = Path(output).resolve()
    if output.exists(): raise FileExistsError('Output exists; use a new fetch directory.')
    output.mkdir(parents=True); (output/'downloads').mkdir(); (output/'pages').mkdir()
    cache = Path(cache_dir).resolve() if cache_dir else output.parent/'.calligraphy-cache'
    (cache/'blobs').mkdir(parents=True, exist_ok=True); (cache/'queries').mkdir(exist_ok=True)
    start = time.monotonic(); deadline = start+budget_seconds; lock = threading.Lock()
    stats = {'network_requests': 0, 'cache_hits': 0}
    failures = {'shufa5': 0, '9610': 0}
    attempts = {ch: [] for ch in dict.fromkeys(chars)}; pools = {ch: [] for ch in attempts}
    requested_author = author_name(author) if author else None

    def get(url, data=None):
        fixed_url(url, url); remaining = deadline-time.monotonic()
        if remaining <= 0: raise TimeoutError('Search budget exhausted.')
        provider = 'shufa5' if 'shufa5.com' in urlsplit(url).netloc else '9610'
        with lock:
            if failures[provider] >= 2: raise TimeoutError('Source circuit open for this run.')
            stats['network_requests'] += 1
        try:
            result = transport(url, data, min(6, remaining))
        except (OSError, ValueError, TimeoutError):
            with lock: failures[provider] += 1
            raise
        with lock: failures[provider] = 0
        return result

    def page(provider, ch):
        try:
            if provider == 'shufa5':
                url = 'https://www.shufa5.com/'
                raw, final = get(url, urlencode({'q': ch}).encode())
                decoded = raw.decode('utf-8', errors='replace')
                rows = parse_shufa5(decoded, final, ch, script)
            else:
                url = 'https://9610.com/zidian/index.asp?key='+quote_from_bytes(ch.encode('gbk'))
                raw, final = get(url); decoded = raw.decode('gb18030', errors='replace')
                rows = parse_9610(decoded, final, ch, script)
            (output/'pages'/f'{provider}-{ch}.html').write_text(decoded, encoding='utf-8')
            if any(term in plain(decoded) for term in ('真人安全验证', '验证码验证', 'Access denied')):
                attempts[ch].append({'provider': provider, 'page_url': final, 'status': 'unavailable', 'note': 'Access restriction; not bypassed.'})
                return []
            if requested_author and strict_author: rows = [r for r in rows if r['author'] == requested_author]
            attempts[ch].append({'provider': provider, 'page_url': final, 'status': 'candidates' if rows else 'no-candidates',
                                 'note': 'Requested character/script and author filter only; not visual verification.'})
            return rows
        except (OSError, ValueError, TimeoutError, UnicodeError) as error:
            attempts[ch].append({'provider': provider, 'status': 'budget-exhausted' if time.monotonic() >= deadline else 'unavailable', 'note': type(error).__name__})
            return []

    def cache_key(ch):
        value = [1, ch, script, requested_author, bool(strict_author), max_candidates, sources]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()

    for ch in pools:
        file = cache/'queries'/(cache_key(ch)+'.json')
        try:
            data = json.loads(file.read_text(encoding='utf-8'))
            if not 0 <= time.time()-data['saved_at'] < 7*86400: continue
            if not data['rows']: continue
            for row in data['rows']:
                blob = lettering.local_path(cache, 'blobs/'+row['blob'])
                if not blob.is_file() or lettering.sha256(blob) != row['sha256']: raise ValueError('Cache hash mismatch.')
            pools[ch] = data['rows']; stats['cache_hits'] += 1
            attempts[ch].append({'provider': 'cache', 'status': 'cached-candidates', 'note': 'Bytes and hash checked; character still requires visual review.'})
        except (OSError, ValueError, TypeError, KeyError): pass

    def download(ch, rows, preferred):
        ranked = sorted(rows, key=lambda r: (r['author'] != requested_author if requested_author else False,
            -preferred.get(r['author'], 0), RANK.index(r['author']) if r['author'] in RANK else len(RANK)))
        found = []
        for row in ranked[:max_candidates+1]:
            if len(found) >= max_candidates or time.monotonic() >= deadline: break
            try:
                if row['provider'] == '9610':
                    raw, detail_url = get(row['page_url']); detail = raw.decode('gb18030', errors='replace')
                    (output/'pages'/('9610-detail-'+ch+'-'+str(len(found))+'.html')).write_text(detail, encoding='utf-8')
                    image = re.search(r'<img\b[^>]*src=(?:"([^"]+)"|([^\s>]+))', detail)
                    if not image: raise ValueError('Detail image not found.')
                    row = dict(row, image_url=fixed_url(detail_url, image[1] or image[2]))
                    desc = re.search(r'class="desc-text">(.*?)</div>', detail, re.S)
                    full = plain(desc[1]) if desc else ''
                    work = re.search('《([^》]+)》', full)
                    if work: row['work'] = work[1]
                raw, image_url = get(row['image_url'])
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in lettering.FORMATS or getattr(image, 'n_frames', 1) != 1: raise ValueError('Unsupported image.')
                    if image.width*image.height > 40_000_000 or max(image.size) < 160: raise ValueError('Candidate image size unsuitable.')
                    image.load(); width, height = image.size; extension = lettering.FORMATS[image.format]
                digest = hashlib.sha256(raw).hexdigest(); blob_name = digest+extension
                (cache/'blobs'/blob_name).write_bytes(raw)
                found.append({'character': ch, 'blob': blob_name, 'sha256': digest, 'width': width, 'height': height,
                    'source': {**row, 'image_url': image_url, 'author_status': 'source-labeled'}, 'provider': row['provider']})
            except (OSError, ValueError, TimeoutError) as error:
                attempts[ch].append({'provider': row['provider'], 'page_url': row['page_url'],
                    'status': 'budget-exhausted' if time.monotonic() >= deadline else 'download-unavailable', 'note': type(error).__name__})
        return found

    for provider in sources:
        missing = [ch for ch in pools if not pools[ch]]
        if not missing: break
        if time.monotonic() >= deadline:
            for ch in missing: attempts[ch].append({'provider': provider, 'status': 'budget-exhausted', 'note': 'No new requests started.'})
            break
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = dict(zip(missing, executor.map(lambda ch: page(provider, ch), missing)))
        coverage = Counter()
        for rows in results.values(): coverage.update(set(r['author'] for r in rows))
        with ThreadPoolExecutor(max_workers=3) as executor:
            downloaded = list(executor.map(lambda ch: download(ch, results[ch], coverage), missing))
        for ch, rows in zip(missing, downloaded):
            if rows:
                pools[ch] = rows
                lettering.write_json(cache/'queries'/(cache_key(ch)+'.json'), {'saved_at': time.time(), 'rows': rows})

    candidates = {}; positions = []
    for ch, rows in pools.items():
        candidates[ch] = []
        for row in rows:
            rel = 'downloads/'+row['blob']; shutil.copyfile(cache/'blobs'/row['blob'], output/rel)
            candidates[ch].append({k: v for k, v in row.items() if k != 'blob'} | {'input': rel})
    for i, ch in enumerate(chars):
        rows = candidates[ch]; first = rows[0] if rows else {}
        positions.append({'index': i, 'character': ch, 'input': first.get('input'), 'source': first.get('source', {}),
            'character_verified': False, 'verification_note': '', 'candidates': rows, 'attempts': attempts[ch],
            **({'missing_reason': 'Fixed-source search has no downloaded candidate; see attempts for missing, failed or budget-limited retrieval.'} if not rows else {})})
    selection = {'text': text, 'notes': ['Candidate retrieval only. Visually inspect originals before marking any character verified.',
        f'Fixed sources: {sources}; retrieval budget {budget_seconds}s; at most {max_candidates} candidates per unique character.'], 'positions': positions}
    if author: selection['author_requirement'] = {'name': requested_author, 'strict': bool(strict_author)}
    lettering.write_json(output/'candidates.json', candidates); lettering.write_json(output/'selection.json', selection)
    flat = [r for rows in candidates.values() for r in rows]; sheets = []
    for start_at in range(0, len(flat), 12):
        subset = flat[start_at:start_at+12]; sheet = Image.new('RGB', (720, ((len(subset)+2)//3)*260), '#f0f0ee'); draw = ImageDraw.Draw(sheet)
        for n, row in enumerate(subset):
            with Image.open(output/row['input']) as original:
                image = original.convert('RGBA'); white = Image.new('RGBA', image.size, 'white'); white.alpha_composite(image)
                tile = white.convert('RGB'); tile.thumbnail((220, 220))
            x, y = n%3*240, n//3*260
            sheet.paste(tile, (x+(240-tile.width)//2, y+28)); draw.text((x+8, y+5), f'candidate {start_at+n+1}', fill='black')
        rel = f'candidates-{start_at//12+1:02}.png'; sheet.save(output/rel); sheets.append(rel)
    result = {'status': 'candidates-only', 'text': text, 'candidate_characters': sum(bool(r) for r in pools.values()),
        'total_unique_characters': len(pools), 'missing': [ch for ch in pools if not pools[ch]],
        'elapsed_seconds': round(time.monotonic()-start, 3), **stats, 'attempts': attempts,
        'files': ['selection.json', 'candidates.json', 'fetch-report.json']+sheets,
        'contact_sheet_candidates': [dict(number=i+1, character=r['character'], author=r['source']['author'], input=r['input']) for i, r in enumerate(flat)]}
    lettering.write_json(output/'fetch-report.json', result)
    return result
