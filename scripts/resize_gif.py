"""
Resize images to a target width with proportional height scaling.
Supports GIF (preserving animation), PNG, JPG, WebP, BMP, and more.

Usage:
  python scripts/resize_gif.py -i resource/arc_cute_gif -w 160
  python scripts/resize_gif.py -i resource/arc_cute_gif -o output -w 320 -f gif,png,jpg
"""
import os
import argparse
from PIL import Image, ImageSequence

ANIMATED_FORMATS = {'gif', 'webp'}
SUPPORTED_FORMATS = {'gif', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tiff', 'ico'}


def process_image(src_path, dst_path, target_width):
    """Resize a single image and save to dst_path. Returns (orig_w, orig_h, new_w, new_h)."""
    img = Image.open(src_path)
    orig_w, orig_h = img.size
    ext = os.path.splitext(src_path)[1].lower().lstrip('.')
    new_h = int(orig_h * target_width / orig_w)

    # Handle animated formats (GIF, animated WebP)
    if ext in ANIMATED_FORMATS:
        frames = []
        durations = []
        for frame in ImageSequence.Iterator(img):
            frame = frame.copy()
            frame = frame.resize((target_width, new_h), Image.LANCZOS)
            frames.append(frame)
            durations.append(frame.info.get('duration', 100))

        if len(frames) == 1:
            frames[0].save(dst_path, format=img.format, save_all=False)
        else:
            kwargs = {
                'save_all': True,
                'append_images': frames[1:],
                'duration': durations,
                'loop': img.info.get('loop', 0),
                'disposal': 2,
            }
            if ext == 'webp':
                kwargs.pop('disposal', None)
            frames[0].save(dst_path, format=img.format, **kwargs)
    else:
        # Static image
        resized = img.resize((target_width, new_h), Image.LANCZOS)
        # Preserve original format; for JPEG, handle RGB conversion
        save_kwargs = {}
        if img.format == 'JPEG' and resized.mode not in ('RGB', 'L'):
            resized = resized.convert('RGB')
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
