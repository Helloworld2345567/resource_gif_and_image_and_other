"""
Resize images to a target width with proportional height scaling.
Supports GIF (preserving animation), PNG, JPG, WebP, BMP, and more.

Features:
  - Proper transparency handling (avoids dark edges on transparent backgrounds)
  - High-quality LANCZOS resampling
  - Preserves GIF animation with correct frame timing
  - Handles frame offsets (partial frames) and disposal methods
  - Unified palette across animated frames to avoid color shifts
  - Supports batch processing of multiple image formats

Usage:
  python scripts/resize_gif.py -i resource/arc_cute_gif -w 160
  python scripts/resize_gif.py -i resource/arc_cute_gif -o output -w 320 -f gif,png,jpg
"""
import os
import argparse
from PIL import Image, ImageSequence, ImageFilter

ANIMATED_FORMATS = {'gif', 'webp'}
SUPPORTED_FORMATS = {'gif', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tiff', 'ico'}
BLEED_RADIUS = 3  # How many pixels to bleed visible colors into transparent areas


def _has_transparency(img):
    """Check if an image has transparency information."""
    if img.mode in ('RGBA', 'LA', 'PA'):
        return True
    if img.mode == 'P' and 'transparency' in img.info:
        return True
    return False


def _bleed_alpha(img):
    """
    Fill fully transparent pixels with nearby visible colors.

    When resizing a transparent image, fully transparent pixels (which often have
    RGB=0, i.e. black in the GIF palette) get blended with visible edge pixels
    during LANCZOS sampling, creating dark halos around the subject.

    This function bleeds visible neighbor colors outward into transparent areas
    before the resize, so interpolation produces clean (non-black) edge pixels.
    """
    rgba = img.convert('RGBA')
    r, g, b, a = rgba.split()

    # No fully transparent pixels → nothing to bleed
    if a.getextrema()[0] > 0:
        return rgba

    # Blur each RGB channel to spread visible colors into transparent areas
    r_blurred = r.filter(ImageFilter.GaussianBlur(radius=BLEED_RADIUS))
    g_blurred = g.filter(ImageFilter.GaussianBlur(radius=BLEED_RADIUS))
    b_blurred = b.filter(ImageFilter.GaussianBlur(radius=BLEED_RADIUS))

    # Use original color where alpha > threshold (~92% transparent or less),
    # otherwise use the blurred (neighbor-averaged) color
    threshold = 20
    alpha_mask = a.point(lambda x: 255 if x > threshold else 0)

    r = Image.composite(r, r_blurred, alpha_mask)
    g = Image.composite(g, g_blurred, alpha_mask)
    b = Image.composite(b, b_blurred, alpha_mask)

    return Image.merge('RGBA', (r, g, b, a))


def _resize_with_alpha(img, size):
    """Resize an image while preserving transparency — no dark halos."""
    if not _has_transparency(img):
        return img.resize(size, Image.LANCZOS)

    rgba = _bleed_alpha(img)
    return rgba.resize(size, Image.LANCZOS)


def _rgba_to_p(rgba, palette_seed=None):
    """
    Convert an RGBA frame to P (palette) mode with a transparent entry.

    A palette seed (a P-mode image) can be provided to share a unified palette
    across multiple frames — the first frame creates it, subsequent frames reuse it.

    This version avoids calling quantize() directly on RGBA (unsupported in some
    Pillow versions) by first converting to RGB, quantizing, then manually
    assigning a transparent palette entry based on the alpha channel.
    """
    alpha = rgba.getchannel('A')
    has_transparency = alpha.getextrema()[0] < 255

    # Color-bleeding already filled transparent areas with neighbor colors,
    # so converting to RGB now is safe — there are no black pixels to leak in.
    rgb = rgba.convert('RGB')

    if palette_seed is not None:
        # Reuse existing palette from the first frame
        p = rgb.quantize(palette=palette_seed, dither=Image.Dither.NONE)
    else:
        # Create new palette: 255 colours + 1 reserved for transparency
        p = rgb.quantize(
            method=Image.Quantize.FASTOCTREE,
            dither=Image.Dither.NONE,
            colors=255,
        )
        # Extend palette to 256 entries so index 255 is available
        pal_ext = list(p.getpalette())  # 255 * 3 = 765 items
        pal_ext.extend([0, 0, 0])       # now 768 items (256 * 3)
        p.putpalette(pal_ext)

    if has_transparency:
        # Remap fully transparent pixels to palette index 255
        binary_alpha = alpha.point(lambda x: 0 if x < 128 else 255)
        pdata = list(p.get_flattened_data())
        adata = list(binary_alpha.get_flattened_data())
        new_data = [255 if a == 0 else d for d, a in zip(pdata, adata)]

        p.putdata(new_data)
        p.info['transparency'] = 255

    return p


def _quantize_palette(frames):
    """
    Quantize all frames to P mode with a *shared* palette so GIF playback
    doesn't flicker between colour tables.
    """
    quantized = []
    palette_seed = None

    for f in frames:
        if f.mode != 'RGBA':
            quantized.append(f if f.mode == 'P' else f.convert('P'))
            continue

        p = _rgba_to_p(f, palette_seed)
        if palette_seed is None:
            palette_seed = p
        quantized.append(p)

    return quantized


def _composite_frames(img, raw_frames, has_offsets, has_transparency):
    """
    Build full-canvas frames by compositing each (possibly partial) frame
    onto a transparent canvas, respecting disposal methods (1=keep, 2=clear,
    3=restore previous).

    Returns a list of RGBA images, each the full size of the original image.
    """
    composited = []
    canvas = Image.new('RGBA', img.size, (0, 0, 0, 0))

    for raw in raw_frames:
        x0 = raw.info.get('x_offset', 0)
        y0 = raw.info.get('y_offset', 0)
        disposal = raw.info.get('disposal', 1)

        # Snapshot for disposal=3 (restore to previous)
        if disposal == 3:
            prev_canvas = canvas.copy()

        # Composite this frame onto the canvas
        if has_transparency and _has_transparency(raw):
            f_rgba = raw.convert('RGBA')
            canvas.paste(f_rgba, (x0, y0), f_rgba)
        else:
            f_rgb = raw.convert('RGBA')
            canvas.paste(f_rgb, (x0, y0))

        composited.append(canvas.copy())

        # Apply disposal for next frame
        if disposal == 2:
            # Restore to background (transparent)
            canvas = Image.new('RGBA', img.size, (0, 0, 0, 0))
        elif disposal == 3:
            # Restore to previous snapshot
            canvas = prev_canvas

    return composited


def _needs_compositing(raw_frames):
    """Check whether any frame requires full-canvas compositing."""
    for f in raw_frames:
        if f.info.get('x_offset', 0) != 0 or f.info.get('y_offset', 0) != 0:
            return True
        if f.info.get('disposal', 1) in (2, 3):
            return True
    return False


def process_image(src_path, dst_path, target_width):
    """Resize a single image and save to dst_path. Returns (orig_w, orig_h, new_w, new_h)."""
    img = Image.open(src_path)
    orig_w, orig_h = img.size
    ext = os.path.splitext(src_path)[1].lower().lstrip('.')
    new_h = int(orig_h * target_width / orig_w)

    if ext in ANIMATED_FORMATS:
        # -------------------- Collect raw frames --------------------
        raw_frames = []
        durations = []
        has_transparency = False

        for frame in ImageSequence.Iterator(img):
            frame = frame.copy()
            raw_frames.append(frame)
            durations.append(frame.info.get('duration', 100))
            if _has_transparency(frame):
                has_transparency = True

        needs_full = _needs_compositing(raw_frames)

        # -------------------- Build canvas & resize --------------------
        if needs_full:
            # Compositing path: handles frame offsets and disposal
            composited = _composite_frames(img, raw_frames,
                                           needs_full, has_transparency)
            if has_transparency:
                frames = [_resize_with_alpha(cf, (target_width, new_h))
                          for cf in composited]
            else:
                frames = [cf.resize((target_width, new_h), Image.LANCZOS)
                          for cf in composited]
        elif has_transparency:
            # Simple path: full frames with transparency
            frames = [_resize_with_alpha(f, (target_width, new_h))
                      for f in raw_frames]
        else:
            # Simplest path: no transparency, no offsets
            frames = [f.resize((target_width, new_h), Image.LANCZOS)
                      for f in raw_frames]

        # -------------------- Quantize to palette --------------------
        frames = _quantize_palette(frames)

        # -------------------- Save --------------------
        save_kwargs = {
            'duration': durations,
            'loop': img.info.get('loop', 0),
            'disposal': 2,
        }

        if len(frames) == 1:
            save_kwargs['save_all'] = False
            frames[0].save(dst_path, format=img.format, **save_kwargs)
        else:
            save_kwargs['save_all'] = True
            save_kwargs['append_images'] = frames[1:]
            if ext == 'webp':
                save_kwargs.pop('disposal', None)
            frames[0].save(dst_path, format=img.format, **save_kwargs)

    else:
        # -------------------- Static image --------------------
        if _has_transparency(img):
            resized = _resize_with_alpha(img, (target_width, new_h))
        else:
            resized = img.resize((target_width, new_h), Image.LANCZOS)

        save_kwargs = {}
        if img.format == 'JPEG' and resized.mode not in ('RGB', 'L'):
            resized = resized.convert('RGB')
        # Preserve ICC profile if present
        if 'icc_profile' in img.info:
            save_kwargs['icc_profile'] = img.info['icc_profile']
        resized.save(dst_path, format=img.format, **save_kwargs)

    return orig_w, orig_h, target_width, new_h


def main():
    parser = argparse.ArgumentParser(
        description='Resize images to a target width with proportional height.')
    parser.add_argument('-i', '--input', required=True,
                        help='Input directory containing images')
    parser.add_argument('-o', '--output', default=None,
                        help='Output directory (default: overwrite in-place)')
    parser.add_argument('-w', '--width', type=int, default=160,
                        help='Target width in pixels (default: 160)')
    parser.add_argument('-f', '--formats', default='gif,png,jpg,jpeg,webp,bmp',
                        help='Comma-separated image formats (default: gif,png,jpg,jpeg,webp,bmp)')
    args = parser.parse_args()

    input_dir = os.path.abspath(args.input)
    output_dir = os.path.abspath(args.output) if args.output else None
    target_width = args.width
    formats = set(f.strip().lower().lstrip('.') for f in args.formats.split(','))

    # Validate formats
    invalid = formats - SUPPORTED_FORMATS
    if invalid:
        print(f'Warning: unsupported formats ignored: {invalid}')

    # Collect image files
    image_files = []
    for root, dirs, files in os.walk(input_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower().lstrip('.')
            if ext in formats:
                image_files.append(os.path.join(root, f))

    if not image_files:
        print(f'No matching images found in {input_dir}')
        return

    print(f'Found {len(image_files)} image(s) in {input_dir}')
    print(f'Target width: {target_width}px, Output: {output_dir or "(in-place)"}')
    print()

    resized = 0
    skipped = 0
    errors = []

    for src_path in image_files:
        rel_path = os.path.relpath(src_path, input_dir)
        dst_path = os.path.join(output_dir, rel_path) if output_dir else src_path

        # Ensure output subdirectories exist
        if output_dir:
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)

        try:
            img = Image.open(src_path)
            orig_w = img.size[0]
            if orig_w == target_width:
                print(f'  SKIP (already {target_width}px): {os.path.basename(src_path)}')
                skipped += 1
                continue

            ow, oh, nw, nh = process_image(src_path, dst_path, target_width)
            print(f'  OK {ow}x{oh} -> {nw}x{nh}: {os.path.basename(src_path)}')
            resized += 1
        except Exception as e:
            errors.append(f'{os.path.basename(src_path)}: {e}')
            print(f'  ERR: {os.path.basename(src_path)} - {e}')

    print(f'\nDone: {resized} resized, {skipped} skipped, {len(errors)} errors')
    for e in errors:
        print(f'  {e}')


if __name__ == '__main__':
    main()
