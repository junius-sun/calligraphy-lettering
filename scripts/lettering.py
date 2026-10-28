#!/usr/bin/env python3
"""Local calligraphy cleanup, composition and optional reviewed SVG tracing.

PNG preparation/composition requires Pillow; SVG uses vtracer and resvg-py.

The agent performs discovery and visual verification. This tool never fetches
URLs, invents strokes, authenticates, or reads a catalog / running website.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
from urllib.parse import urlparse

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

VERSION = 1
FORMATS = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'TIFF': '.tif', 'BMP': '.bmp', 'GIF': '.gif'}
LAYOUTS = {'compact': ('horizontal', .12), 'airy': ('horizontal', .32), 'vertical': ('vertical', .20)}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Task asset must stay inside the job directory.')
    return path


def text_characters(text):
    if not isinstance(text, str):
        raise ValueError('text must be a string.')
    chars = list(''.join(text.split()))
    def han(c):
        return any(a <= ord(c) <= b for a, b in [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x323AF)])
    if not chars or len(chars) > 120 or any(not han(c) for c in chars):
        raise ValueError('Use 1-120 Han characters without punctuation; compositions split every 12 positions.')
    return chars


def clean_image(image, crop=None, polarity='auto', cutoff=245, padding=5, normalize=True):
    """EXIF-orient, crop, locally normalize paper, and encode black strokes as alpha.

    crop uses [left, top, right, bottom] pixels AFTER EXIF orientation, right and
    bottom exclusive. No morphology, inpainting or connected-component deletion.
    """
    if polarity not in ('auto', 'light', 'dark') or not isinstance(cutoff, int) or not 140 <= cutoff <= 254:
        raise ValueError('Invalid polarity or cutoff (140-254).')
    if not isinstance(padding, int) or not 0 <= padding <= 100:
        raise ValueError('Invalid padding (0-100).')
    oriented = ImageOps.exif_transpose(image).convert('RGBA')
    if min(oriented.size) < 2 or oriented.width * oriented.height > 40_000_000:
        raise ValueError('Image dimensions outside processing limits (40 MP).')
    box = list(crop) if crop is not None else [0, 0, oriented.width, oriented.height]
    if len(box) != 4 or any(type(n) is not int for n in box) or not (0 <= box[0] < box[2] <= oriented.width and 0 <= box[1] < box[3] <= oriented.height):
        raise ValueError('Crop must be inside the oriented image, using exclusive right/bottom.')
    rgba = oriented.crop(tuple(box))
    alpha_in = rgba.getchannel('A')
    # Composite for polarity estimation only; existing alpha remains authoritative.
    base = Image.new('RGBA', rgba.size, 'white')
    base.alpha_composite(rgba)
    gray = base.convert('L')
    w, h = gray.size
    pixels = gray.load(); opacity = alpha_in.load()
    border = [pixels[x, y] for y in range(h) for x in range(w)
              if (x in (0, w-1) or y in (0, h-1)) and opacity[x, y] > 128]
    actual = ('dark' if border and sum(border)/len(border) < 128 else 'light') if polarity == 'auto' else polarity
    gray = ImageOps.invert(rgba.convert('L')) if actual == 'dark' else rgba.convert('L')
    # A uniform transparent canvas must not invent background ink. Black pixels
    # with existing partial alpha retain exactly that alpha after this mapping.
    if normalize and alpha_in.getextrema() == (255, 255):
        radius = max(3, min(60, round(min(w, h) / 7)))
        paper = gray.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(radius))
        # Divide by estimated local paper brightness, keeping dark ink unaltered.
        normalized = bytes(min(255, round(v*255/max(1, bg))) for v, bg in zip(gray.tobytes(), paper.tobytes()))
        gray = Image.frombytes('L', gray.size, normalized)
    table = [round(max(0, min(1, (cutoff-v)/max(1, cutoff-96))) * 255) for v in range(256)]
    alpha = ImageChops.multiply(gray.point(table), alpha_in)
    bbox = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox is None:
        raise ValueError('No visible strokes; choose another source or processing threshold.')
    alpha = alpha.crop(bbox)
    output = Image.new('RGBA', (alpha.width+2*padding, alpha.height+2*padding), (0, 0, 0, 0))
    output.paste(Image.new('RGBA', alpha.size, (0, 0, 0, 255)), (padding, padding), alpha)
    return output, {'version': VERSION, 'coordinate_space': 'exif-oriented-original', 'oriented_size': list(oriented.size),
                    'crop': box, 'ink_bbox_in_crop': list(bbox), 'polarity': actual,
                    'cutoff': cutoff, 'padding': padding, 'normalize': bool(normalize)}


def valid_source(source):
    if not isinstance(source, dict):
        raise ValueError('Source metadata required.')
    if source.get('kind') == 'user-provided':
        return
    parsed = urlparse(source.get('page_url', ''))
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('An HTTP(S) source page without credentials is required.')


def prepare(selection_path, output):
    selection_path = Path(selection_path).resolve()
    selection = json.loads(selection_path.read_text(encoding='utf-8-sig'))
    chars = text_characters(selection.get('text'))
    positions = selection.get('positions', [])
    if not isinstance(positions, list):
        raise ValueError('positions must be a list.')
    indices = [p.get('index') for p in positions]
    if any(type(i) is not int or not 0 <= i < len(chars) for i in indices) or len(set(indices)) != len(indices):
        raise ValueError('Position indices must be unique and match text.')
    selected = {p['index']: p for p in positions}
    if any(p.get('character') != chars[i] for i, p in selected.items()):
        raise ValueError('Position character differs from requested text; aliases require explicit agent review.')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Output directory already exists; choose a new versioned job directory.')
    output.mkdir(parents=True)
    (output/'originals').mkdir(); (output/'glyphs').mkdir()
    requirement = selection.get('author_requirement', {})
    if not isinstance(requirement, dict):
        raise ValueError('author_requirement must be an object.')
    task = {'version': VERSION, 'text': ''.join(chars), 'created_at': datetime.now(timezone.utc).isoformat(),
            'author_requirement': requirement, 'notes': selection.get('notes', []), 'positions': []}
    for i, character in enumerate(chars):
        p = selected.get(i, {})
        row = {'index': i, 'character': character, 'status': 'missing',
               'attempts': p.get('attempts', []), 'candidates': p.get('candidates', [])[:3],
               'source': p.get('source', {}), 'verification_note': p.get('verification_note', ''),
               'character_verified': p.get('character_verified') is True,
               'processing_review': {'status': 'pending', 'note': ''},
               'layout': p.get('layout', {'scale': 1, 'dx': 0, 'dy': 0})}
        try:
            if not p.get('input'):
                raise ValueError(p.get('missing_reason') or 'No usable source selected.')
            source = row['source']; valid_source(source)
            row['source'] = {**source, 'author_status': source.get('author_status', 'unknown')}
            path = (selection_path.parent / p['input']).resolve()
            if not path.is_file() or path.stat().st_size > 40_000_000:
                raise ValueError('Source image missing or exceeds 40 MB.')
            with Image.open(path) as image:
                if getattr(image, 'n_frames', 1) != 1 or image.format not in FORMATS:
                    raise ValueError('Use a supported still image.')
                if image.width * image.height > 40_000_000:
                    raise ValueError('Source image exceeds 40 MP.')
                image.load()
                digest = sha256(path)
                relative = 'originals/' + digest + FORMATS[image.format]
                if not (output/relative).exists(): shutil.copyfile(path, output/relative)
                row['original'] = {'path': relative, 'sha256': digest, 'width': image.width,
                                   'height': image.height, 'format': image.format}
                if not row['character_verified'] or not row['verification_note'].strip():
                    raise ValueError('Character has not been visually verified with a note.')
                requested = requirement.get('name')
                row['substitution'] = bool(requested and source.get('author') != requested)
                if requirement.get('strict') and row['substitution']:
                    raise ValueError('Selected author does not meet the strict author requirement.')
                cleaned, processing = clean_image(image, crop=p.get('crop'), polarity=p.get('polarity', 'auto'),
                    cutoff=p.get('cutoff', 245), padding=p.get('padding', 5), normalize=p.get('normalize', True))
            target = f'glyphs/{i+1:03}-{character}.png'
            cleaned.save(output/target)
            row.update(status='ready', processing=processing, glyph={'path': target, 'sha256': sha256(output/target),
                       'width': cleaned.width, 'height': cleaned.height})
        except (OSError, ValueError, TypeError, Image.DecompressionBombError) as error:
            row['missing_reason'] = str(error)
        task['positions'].append(row)
    # Rebase inputs to preserved bytes so a copied job survives deleted downloads.
    replay = json.loads(json.dumps(selection))
    for p in replay['positions']:
        row = task['positions'][p['index']]
        if row.get('original'): p['input'] = row['original']['path']
    write_json(output/'selection.json', replay)
    write_json(output/'task.json', task)
    write_sources(output, task)
    return task


def write_sources(job, task):
    lines = ['# 集字素材与处理记录', '', '文字：'+task['text'], '',
             '字形归属按下列状态记录；下载、看图核对和作者鉴定是不同层次。', '']
    for p in task['positions']:
        source = p.get('source', {})
        lines += [f"## {p['index']+1}. {p['character']}", '', f"状态：{p['status']}；处理检查：{p.get('processing_review', {}).get('status', 'pending')}",
                  f"书家：{source.get('author') or '未知'}；书体：{source.get('script') or '未知'}；作品：{source.get('work') or '未知'}",
                  '作者归属状态：'+source.get('author_status', 'unknown'), '来源页：'+source.get('page_url', '用户提供'),
                  '文字核对：'+p.get('verification_note', ''), '']
        if p.get('substitution'): lines += ['已替换原偏好书家；未满足原书家偏好。', '']
        if p.get('missing_reason'): lines += ['未完成原因：'+p['missing_reason'], '']
        if p.get('original'): lines += ['原图 SHA-256：`'+p['original']['sha256']+'`', '']
        if p.get('processing'): lines += ['处理：`'+json.dumps(p['processing'], ensure_ascii=False)+'`', '']
        for attempt in p.get('attempts', []):
            lines += [f"- {attempt.get('status', 'unknown')} · {attempt.get('page_url', '')} · {attempt.get('note', '')}"]
        lines += ['']
    (job/'sources.md').write_text('\n'.join(lines), encoding='utf-8')


def accepted_position(p, task):
    source = p.get('source', {})
    requirement = task.get('author_requirement', {})
    return (p.get('status') == 'ready' and p.get('character_verified') is True
            and p.get('processing_review', {}).get('status') == 'accepted'
            and bool(p.get('processing_review', {}).get('note', '').strip())
            and not (requirement.get('strict') and source.get('author') != requirement.get('name')))


def layout_items(positions, images, name):
    direction, spacing = LAYOUTS[name]
    base = min([512] + [max(im.size) for im in images.values()])
    base = max(16, base); gap = max(2, round(base*spacing)); padding = max(12, round(base*.10))
    items = []
    for n, p in enumerate(positions):
        image = images.get(p['index']); native = image.size if image else (base, base)
        adjustment = p.get('layout', {})
        scale, dx, dy = adjustment.get('scale', 1), adjustment.get('dx', 0), adjustment.get('dy', 0)
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (scale, dx, dy)) or not .25 <= scale <= 1 or max(abs(dx), abs(dy)) > 4096:
            raise ValueError('Layout requires scale .25-1 and offsets within 4096 pixels.')
        ratio = min(1, base/max(native)) * scale
        w, h = max(1, round(native[0]*ratio)), max(1, round(native[1]*ratio))
        items.append({'index': p['index'], 'character': p['character'], 'width': w, 'height': h,
                      'x': (n*(base+gap) if direction == 'horizontal' else 0)+(base-w)/2+dx,
                      'y': (n*(base+gap) if direction == 'vertical' else 0)+(base-h)/2+dy,
                      'placeholder': image is None})
    left = math.floor(min(i['x'] for i in items)); top = math.floor(min(i['y'] for i in items))
    width = math.ceil(max(i['x']+i['width'] for i in items))-left+2*padding
    height = math.ceil(max(i['y']+i['height'] for i in items))-top+2*padding
    for item in items: item['x'] = round(item['x']-left+padding); item['y'] = round(item['y']-top+padding)
    if width*height > 40_000_000: raise ValueError('Composition exceeds 40 MP.')
    return {'width': width, 'height': height, 'cell': base, 'gap': gap, 'padding': padding, 'items': items}


def compose(job):
    job = Path(job).resolve()
    task = json.loads((job/'task.json').read_text(encoding='utf-8'))
    chars = text_characters(task.get('text'))
    positions = task.get('positions', [])
    if task.get('version') != VERSION or len(positions) != len(chars) or any(p.get('index') != i or p.get('character') != chars[i] for i, p in enumerate(positions)):
        raise ValueError('Task text and position records do not match.')
    images = {}
    for p in positions:
        if p.get('status') == 'ready':
            for kind in ('original', 'glyph'):
                asset = p[kind]; path = local_path(job, asset['path'])
                if not path.is_file() or sha256(path) != asset['sha256']:
                    raise ValueError('Asset changed or missing; prepare again instead of silently changing the original: '+asset['path'])
            if accepted_position(p, task):
                with Image.open(local_path(job, p['glyph']['path'])) as image: images[p['index']] = image.convert('RGBA')
    result = {'version': VERSION, 'text': task['text'], 'ready': len(images), 'status': 'complete' if len(images) == len(positions) else 'draft',
              'missing_or_unreviewed': [p['index'] for p in positions if p['index'] not in images], 'files': [], 'segments': []}
    out = job/'exports'; out.mkdir(exist_ok=True)
    # Remove only files generated by the prior compose, avoiding stale finals.
    previous = job/'composition.json'
    if previous.exists():
        prior = json.loads(previous.read_text(encoding='utf-8'))
        for relative in prior.get('files', []):
            path = local_path(job, relative)
            if path.parent == out and path.suffix == '.png': path.unlink(missing_ok=True)
    previews = []
    for start in range(0, len(positions), 12):
        subset = positions[start:start+12]
        draft = any(p['index'] not in images for p in subset)
        segment = {'indices': [p['index'] for p in subset], 'status': 'draft' if draft else 'complete', 'layouts': {}}
        for name in LAYOUTS:
            plan = layout_items(subset, {p['index']: images[p['index']] for p in subset if p['index'] in images}, name)
            canvas = Image.new('RGBA', (plan['width'], plan['height']), (0, 0, 0, 0))
            draw = ImageDraw.Draw(canvas)
            for item in plan['items']:
                x, y, w, h = (item[k] for k in ('x', 'y', 'width', 'height'))
                image = images.get(item['index'])
                if image:
                    canvas.alpha_composite(image.resize((w, h), Image.Resampling.LANCZOS), (x, y))
                else:
                    draw.rectangle((x, y, x+w-1, y+h-1), outline=(180, 40, 40, 255), width=2)
                    draw.line((x, y, x+w-1, y+h-1), fill=(180, 40, 40, 255), width=2)
                    draw.text((x+3, y+3), str(item['index']+1), fill=(180, 40, 40, 255))
            if draft: draw.text((4, 1), 'DRAFT - missing / unreviewed', fill=(180, 40, 40, 255))
            prefix = ('DRAFT-' if draft else '')+f'segment-{start//12+1:02}-{name}'
            for background in ('transparent', 'white'):
                target = canvas
                if background == 'white':
                    target = Image.new('RGBA', canvas.size, 'white'); target.alpha_composite(canvas)
                relative = 'exports/'+prefix+'-'+background+'.png'
                target.save(job/relative); result['files'].append(relative)
            segment['layouts'][name] = plan
            white = Image.new('RGBA', canvas.size, 'white'); white.alpha_composite(canvas)
            white.thumbnail((1000, 450)); previews.append((prefix, white.convert('RGB')))
        result['segments'].append(segment)
    height = sum(im.height+38 for _, im in previews)+20
    sheet = Image.new('RGB', (max(im.width for _, im in previews)+40, height), '#f0f0ee')
    draw = ImageDraw.Draw(sheet); top = 16
    for label, im in previews:
        draw.text((20, top), label, fill='#333333'); sheet.paste(im, (20, top+20)); top += im.height+38
    sheet.save(job/'preview.png')
    write_json(job/'composition.json', result)
    write_sources(job, task)
    return result


def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare', help='Preserve source files and prepare verified glyphs for visual review.')
    p.add_argument('--selection', required=True, type=Path); p.add_argument('--output', required=True, type=Path)
    c = commands.add_parser('compose', help='Export three layouts; pending or missing positions produce DRAFT files.')
    c.add_argument('--job', required=True, type=Path)
    v = commands.add_parser('vectorize', help='Trace PNGs into SVG paths; separate visual review is required.')
    v.add_argument('--job', required=True, type=Path)
    v.add_argument('--alpha-threshold', type=int, default=96)
    v.add_argument('--mode', choices=['spline', 'polygon'], default='spline')
    args = parser.parse_args()
    try:
        if args.command == 'prepare': value = prepare(args.selection, args.output)
        elif args.command == 'compose': value = compose(args.job)
        else:
            from svg_export import vectorize
            value = vectorize(args.job, alpha_threshold=args.alpha_threshold, mode=args.mode)
        print(json.dumps({'status': value.get('status', 'prepared'), 'text': value['text'],
                          'ready': value.get('ready', sum(p['status'] == 'ready' for p in value.get('positions', []))),
                          'files': value.get('files', []), 'job': str(args.output if args.command == 'prepare' else args.job)}, ensure_ascii=False))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(str(error), file=sys.stderr); return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
