"""Trace reviewed PNG alpha into SVG paths; preserve PNGs and require SVG review."""
import copy
import hashlib
import io
import json
from importlib.metadata import version
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops, ImageDraw
import lettering

NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
MAX_TRACE_PIXELS = 4_000_000


def element(tag, attrs=None):
    return ET.Element('{'+NS+'}'+tag, attrs or {})


def svg_root(width, height):
    root = element('svg', {'version': '1.1', 'width': str(width), 'height': str(height),
                           'viewBox': f'0 0 {width} {height}'})
    return root


def serialize(root):
    return ET.tostring(root, encoding='unicode') + '\n'


def check_options(alpha_threshold, mode):
    if type(alpha_threshold) is not int or not 1 <= alpha_threshold <= 255:
        raise ValueError('alpha_threshold must be an integer from 1 to 255.')
    if mode not in ('spline', 'polygon'):
        raise ValueError('mode must be spline or polygon.')


def ink_mask(image, alpha_threshold):
    return image.convert('RGBA').getchannel('A').point(lambda a: 255 if a >= alpha_threshold else 0)


def trace_glyph(image, alpha_threshold=96, mode='spline'):
    """Trace alpha only, avoiding opaque black rectangles from transparent RGB."""
    check_options(alpha_threshold, mode)
    if image.width * image.height > MAX_TRACE_PIXELS:
        raise ValueError('Glyph exceeds 4 MP for tracing; keep PNG or select a smaller source crop.')
    mask = ink_mask(image, alpha_threshold)
    if not mask.getbbox():
        raise ValueError('No ink remains at this alpha threshold; lower it or keep PNG only.')
    try:
        import vtracer
    except ImportError as error:
        raise ValueError('SVG tracing requires vtracer; install requirements.txt in the task environment.') from error
    # A two-times nearest-neighbour tracing grid prevents isolated 1 px marks
    # becoming degenerate zero-area contours. Coordinates return to native size.
    tracing = ImageChops.invert(mask).convert('RGB').resize((image.width*2, image.height*2), Image.Resampling.NEAREST)
    data = io.BytesIO(); tracing.save(data, format='PNG')
    raw = vtracer.convert_raw_image_to_svg(data.getvalue(), img_format='png', colormode='binary',
        mode=mode, filter_speckle=0, corner_threshold=60, length_threshold=3.5,
        max_iterations=10, splice_threshold=45, path_precision=3)
    traced = ET.fromstring(raw)
    root = svg_root(image.width, image.height)
    desc = ET.SubElement(root, '{'+NS+'}desc')
    desc.text = 'Traced outline from PNG alpha, not reconstructed original brushwork. Review: vectorization.json.'
    group = ET.SubElement(root, '{'+NS+'}g', {'transform': 'scale(0.5)'})
    for path in traced:
        if path.tag == '{'+NS+'}path':
            group.append(copy.deepcopy(path))
    if not len(group):
        raise ValueError('The tracing engine returned no paths.')
    return serialize(root)


def rasterize(svg):
    try:
        import resvg_py
    except ImportError as error:
        raise ValueError('SVG review requires resvg-py; install requirements.txt in the task environment.') from error
    return Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True))).convert('RGBA')


def review_metrics(image, rendered, threshold):
    target = ink_mask(image, threshold)
    observed = rendered.getchannel('A').point(lambda a: 255 if a >= 128 else 0)
    missing = ImageChops.subtract(target, observed); added = ImageChops.subtract(observed, target)
    intersection = sum(ImageChops.darker(target, observed).histogram()[1:])
    union = sum(ImageChops.lighter(target, observed).histogram()[1:])
    ink = sum(target.histogram()[1:])
    lost = sum(missing.histogram()[1:]); extra = sum(added.histogram()[1:])
    overlay = Image.new('RGB', image.size, 'white')
    overlay.paste('black', mask=ImageChops.darker(target, observed))
    overlay.paste('#d62424', mask=missing); overlay.paste('#008ea8', mask=added)
    return {'mask_iou': round(intersection/max(1, union), 6),
            'lost_ink_ratio': round(lost/max(1, ink), 6),
            'added_ink_ratio': round(extra/max(1, ink), 6)}, overlay


def verified_images(job, task):
    chars = lettering.text_characters(task.get('text')); positions = task.get('positions', [])
    if task.get('version') != lettering.VERSION or len(positions) != len(chars) or any(p.get('index') != i or p.get('character') != chars[i] for i, p in enumerate(positions)):
        raise ValueError('Task text and position records do not match.')
    images = {}
    for p in positions:
        if p.get('status') == 'ready':
            for kind in ('original', 'glyph'):
                a = p[kind]; path = lettering.local_path(job, a['path'])
                if not path.is_file() or lettering.sha256(path) != a['sha256']:
                    raise ValueError('Asset changed or missing; prepare and review again: '+a['path'])
            if lettering.accepted_position(p, task):
                with Image.open(lettering.local_path(job, p['glyph']['path'])) as im:
                    images[p['index']] = im.convert('RGBA')
    return images


def load_plans(job, task, images):
    file = job/'composition.json'
    if not file.is_file():
        raise ValueError('Run compose before vectorize.')
    composition = json.loads(file.read_text(encoding='utf-8'))
    if composition.get('text') != task['text']:
        raise ValueError('Layout is stale; run compose again.')
    positions = task['positions']; expected_segments = []
    for start in range(0, len(positions), 12):
        subset = positions[start:start+12]
        plans = {name: lettering.layout_items(subset, {p['index']: images[p['index']] for p in subset if p['index'] in images}, name) for name in lettering.LAYOUTS}
        expected_segments.append({'indices': [p['index'] for p in subset],
                                  'status': 'draft' if any(p['index'] not in images for p in subset) else 'complete',
                                  'layouts': plans})
    if composition.get('segments') != expected_segments:
        raise ValueError('Layout is stale; run compose again after changing images or layout parameters.')
    return expected_segments


def layout_svg(plan, glyphs, background, draft):
    root = svg_root(plan['width'], plan['height'])
    desc = ET.SubElement(root, '{'+NS+'}desc')
    desc.text = ('DRAFT: missing or unreviewed vector outlines. ' if draft else '') + 'Traced lettering; PNG remains available separately.'
    if background == 'white':
        ET.SubElement(root, '{'+NS+'}rect', {'width': '100%', 'height': '100%', 'fill': '#ffffff'})
    for item in plan['items']:
        glyph = glyphs.get(item['index'])
        w, h = item['width'], item['height']
        transform = f"translate({item['x']} {item['y']})"
        if glyph:
            transform += f" scale({w/glyph['width']:.9f} {h/glyph['height']:.9f})"
        group = ET.SubElement(root, '{'+NS+'}g', {'data-index': str(item['index']),
            'data-character': item['character'], 'transform': transform})
        if glyph:
            for child in ET.fromstring(glyph['content']):
                if child.tag != '{'+NS+'}desc': group.append(copy.deepcopy(child))
        else:
            ET.SubElement(group, '{'+NS+'}path', {'d': f'M0 0H{w}V{h}H0ZM0 0L{w} {h}',
                'fill': 'none', 'stroke': '#b42828', 'stroke-width': '2'})
    return serialize(root)


def vectorize(job, alpha_threshold=96, mode='spline'):
    check_options(alpha_threshold, mode)
    # Check both dependencies before touching output or old exports.
    try:
        engine_version = version('vtracer'); renderer_version = version('resvg-py')
    except Exception as error:
        raise ValueError('Install requirements.txt for vtracer and resvg-py before vectorize.') from error
    job = Path(job).resolve(); task = json.loads((job/'task.json').read_text(encoding='utf-8'))
    images = verified_images(job, task); plans = load_plans(job, task, images)
    report_file = job/'vector-review.json'
    report = json.loads(report_file.read_text(encoding='utf-8')) if report_file.is_file() else {'positions': []}
    reviews = {p['index']: p for p in report.get('positions', [])}
    result = {'version': 1, 'text': task['text'], 'engine': {'name': 'vtracer', 'version': engine_version},
        'renderer': {'name': 'resvg-py', 'version': renderer_version},
        'parameters': {'alpha_threshold': alpha_threshold, 'mode': mode, 'filter_speckle': 0,
                       'tracing_grid_scale': 2, 'corner_threshold': 60, 'length_threshold': 3.5,
                       'max_iterations': 10, 'splice_threshold': 45, 'path_precision': 3},
        'notes': ['SVG is a thresholded traced outline; it cannot recover missing source detail.',
                  'Masks and metrics assist comparison, never replace visual inspection.'],
        'glyphs': [], 'segments': [], 'files': []}
    payloads = {}; traced = {}; comparisons = []
    for p in task['positions']:
        i = p['index']; image = images.get(i)
        row = {'index': i, 'character': p['character'], 'status': 'missing', 'review': {'status': 'pending', 'note': ''}}
        if image is None:
            row['reason'] = 'PNG missing or its visual review has not passed.'
        else:
            try:
                content = trace_glyph(image, alpha_threshold, mode); rendered = rasterize(content)
                digest = hashlib.sha256(content.encode('utf-8')).hexdigest(); review = reviews.get(i, {})
                accepted = (review.get('status') == 'accepted' and bool(review.get('note', '').strip())
                            and review.get('glyph_sha256') == p['glyph']['sha256'] and review.get('svg_sha256') == digest)
                status = 'ready' if accepted else 'draft'; prefix = '' if accepted else 'DRAFT-'
                relative = f"vectors/glyphs/{prefix}{i+1:03}-{p['character']}.svg"
                row.update(status=status, path=relative, svg_sha256=digest, glyph_sha256=p['glyph']['sha256'],
                           width=image.width, height=image.height,
                           review={'status': 'accepted' if accepted else 'pending', 'note': review.get('note', '') if accepted else ''})
                metrics, overlay = review_metrics(image, rendered, alpha_threshold); row['metrics'] = metrics
                payloads[relative] = content
                for name, im in [('traced', rendered), ('difference', overlay)]:
                    key = f'vectors/review/{i+1:03}-{name}.png'; payloads[key] = im; row[name+'_preview'] = key
                traced[i] = {'content': content, 'width': image.width, 'height': image.height}
                comparisons.append((i, image, rendered, overlay))
            except ValueError as error:
                row['reason'] = str(error)
        result['glyphs'].append(row)
    ready = {g['index'] for g in result['glyphs'] if g['status'] == 'ready'}
    for n, segment in enumerate(plans, 1):
        draft = any(i not in ready for i in segment['indices'])
        record = {'indices': segment['indices'], 'status': 'draft' if draft else 'complete', 'layouts': segment['layouts']}
        for name, plan in segment['layouts'].items():
            prefix = ('DRAFT-' if draft else '') + f'segment-{n:02}-{name}'
            for bg in ('transparent', 'white'):
                svg = layout_svg(plan, traced, bg, draft)
                payloads[f'vectors/exports/{prefix}-{bg}.svg'] = svg
                payloads[f'vectors/previews/{prefix}-{bg}.png'] = rasterize(svg)
        result['segments'].append(record)
    # Side by side: original PNG alpha, rendered SVG, lost (red) / added (cyan).
    for start in range(0, len(comparisons), 8):
        chunk = comparisons[start:start+8]; sheet = Image.new('RGB', (640, 44+len(chunk)*212), '#f0f0ee'); draw = ImageDraw.Draw(sheet)
        draw.text((12, 10), 'PNG                  SVG TRACE             DIFF: red lost / cyan added', fill='black')
        for n, (i, *variants) in enumerate(chunk):
            y = 44+n*212; draw.text((8, y), str(i+1), fill='black')
            for col, image in enumerate(variants):
                white = Image.new('RGBA', image.size, 'white'); white.alpha_composite(image.convert('RGBA'))
                tile = white.convert('RGB'); tile.thumbnail((190, 190)); sheet.paste(tile, (24+col*208, y+16))
        key = 'vectors/preview.png' if start == 0 else f'vectors/preview-{start//8+1:02}.png'; payloads[key] = sheet
    if not comparisons:
        sheet = Image.new('RGB', (640, 80), 'white'); ImageDraw.Draw(sheet).text((12, 25), 'DRAFT - no reviewed PNG glyphs available', fill='#b42828'); payloads['vectors/preview.png'] = sheet
    # Validate destinations before mutation; remove only files owned by our last run.
    vector_dir = lettering.local_path(job, 'vectors')
    destinations = {key: lettering.local_path(job, key) for key in payloads}
    previous = job/'vectorization.json'
    if previous.exists():
        old = json.loads(previous.read_text(encoding='utf-8'))
        for rel in old.get('files', []):
            file = lettering.local_path(job, rel)
            if file.is_relative_to(vector_dir) and file.suffix in ('.svg', '.png') and file not in destinations.values():
                file.unlink(missing_ok=True)
    for key, payload in payloads.items():
        target = destinations[key]; target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str): target.write_bytes(payload.encode('utf-8'))
        else: payload.save(target)
        result['files'].append(key)
    result.update(status='complete' if len(ready) == len(task['positions']) else 'draft', ready=len(ready),
                  missing_or_unreviewed=[p['index'] for p in task['positions'] if p['index'] not in ready])
    lettering.write_json(job/'vectorization.json', result)
    return result
