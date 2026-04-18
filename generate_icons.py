"""
Generate all PWA icons for Taxman256.
Run: venv\Scripts\python.exe generate_icons.py
Requires: pip install Pillow cairosvg  OR  pip install Pillow (uses fallback)
"""
import os, struct, zlib, math

ICONS_DIR = os.path.join(os.path.dirname(__file__), 'static', 'icons')
os.makedirs(ICONS_DIR, exist_ok=True)

SIZES = [72, 96, 128, 144, 152, 192, 384, 512]

def make_png(size, path, maskable=False):
    """Generate a simple PNG programmatically — no external deps needed."""
    # Draw a Taxman256 icon: blue rounded square + gold calculator symbol
    # We'll create raw RGBA pixel data
    img = bytearray(size * size * 4)

    cx, cy = size // 2, size // 2
    r_outer = size // 2
    r_inner = int(size * 0.44)  # rounded rect radius approximation
    pad = int(size * 0.1) if maskable else 0

    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            nx, ny = x - cx, y - cy

            # Background: deep blue rounded square
            in_bg = (abs(nx) < r_outer - pad and abs(ny) < r_outer - pad)
            corner_r = int(size * 0.22)
            # Rounded corners
            if abs(nx) > r_outer - pad - corner_r and abs(ny) > r_outer - pad - corner_r:
                dist = math.sqrt((abs(nx) - (r_outer - pad - corner_r))**2 +
                                 (abs(ny) - (r_outer - pad - corner_r))**2)
                in_bg = dist < corner_r

            if not in_bg:
                img[idx:idx+4] = [0, 0, 0, 0]
                continue

            # Default: blue background
            img[idx:idx+4] = [26, 60, 110, 255]

            # Gold calculator body (inner rounded rect)
            bx = int(size * 0.23)
            by_top = int(size * 0.19)
            by_bot = int(size * 0.81)
            bw = size - 2 * bx
            if bx < x < size - bx and by_top < y < by_bot:
                img[idx:idx+4] = [200, 149, 42, 255]

            # Dark screen area
            sx1, sy1 = int(size * 0.28), int(size * 0.24)
            sx2, sy2 = int(size * 0.72), int(size * 0.42)
            if sx1 < x < sx2 and sy1 < y < sy2:
                img[idx:idx+4] = [15, 36, 68, 255]

            # Button grid (3x4 dark buttons)
            btn_cols = [int(size * 0.28), int(size * 0.42), int(size * 0.56)]
            btn_rows = [int(size * 0.45), int(size * 0.55), int(size * 0.65), int(size * 0.75)]
            btn_w = int(size * 0.10)
            btn_h = int(size * 0.07)
            for brow in btn_rows:
                for bcol in btn_cols:
                    if bcol < x < bcol + btn_w and brow < y < brow + btn_h:
                        img[idx:idx+4] = [15, 36, 68, 255]

            # Green equals button (right side)
            if int(size * 0.68) < x < int(size * 0.72) and int(size * 0.55) < y < int(size * 0.82):
                img[idx:idx+4] = [39, 174, 96, 255]

    # Encode as PNG
    def png_chunk(name, data):
        c = zlib.crc32(name + data) & 0xffffffff
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', c)

    raw_rows = b''
    for y in range(size):
        raw_rows += b'\x00'  # filter type none
        raw_rows += bytes(img[y*size*4:(y+1)*size*4])

    compressed = zlib.compress(raw_rows, 9)

    png = (
        b'\x89PNG\r\n\x1a\n' +
        png_chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)) +
        png_chunk(b'IDAT', compressed) +
        png_chunk(b'IEND', b'')
    )

    with open(path, 'wb') as f:
        f.write(png)
    print(f'  Created: {os.path.basename(path)} ({size}x{size})')

print('Generating Taxman256 PWA icons...')
for s in SIZES:
    make_png(s, os.path.join(ICONS_DIR, f'icon-{s}.png'))

# Maskable versions (192 and 512 with safe-zone padding)
make_png(192, os.path.join(ICONS_DIR, 'icon-maskable-192.png'), maskable=True)
make_png(512, os.path.join(ICONS_DIR, 'icon-maskable-512.png'), maskable=True)

# Placeholder screenshots (solid color with text — browsers accept these)
def make_screenshot(w, h, path):
    img = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            idx = (y * w + x) * 4
            img[idx:idx+4] = [26, 60, 110, 255]

    def png_chunk(name, data):
        c = zlib.crc32(name + data) & 0xffffffff
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', c)

    raw_rows = b''
    for y in range(h):
        raw_rows += b'\x00'
        raw_rows += bytes(img[y*w*4:(y+1)*w*4])

    compressed = zlib.compress(raw_rows, 9)
    png = (
        b'\x89PNG\r\n\x1a\n' +
        png_chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) +
        png_chunk(b'IDAT', compressed) +
        png_chunk(b'IEND', b'')
    )
    with open(path, 'wb') as f:
        f.write(png)
    print(f'  Created: {os.path.basename(path)} ({w}x{h})')

make_screenshot(1280, 720,  os.path.join(ICONS_DIR, 'screenshot-wide.png'))
make_screenshot(390,  844,  os.path.join(ICONS_DIR, 'screenshot-mobile.png'))

print('Done! All icons generated.')
