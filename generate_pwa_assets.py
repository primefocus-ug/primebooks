#!/usr/bin/env python3
"""
generate_pwa_assets.py
══════════════════════════════════════════════════════════════════════
Generates every missing PWA image asset from your existing favicon files.

Run from your project root:
    python generate_pwa_assets.py

Or from the favicon directory:
    python generate_pwa_assets.py --favicon-dir static/favicon

Requirements:
    pip install Pillow

What it generates:
    static/favicon/
        apple-touch-icon.png          (180×180)  — already exists, verified
        apple-touch-icon-167x167.png  (167×167)  — iPad Retina
        apple-touch-icon-152x152.png  (152×152)  — iPad
        apple-touch-icon-120x120.png  (120×120)  — iPhone fallback
        web-app-manifest-192x192.png  (192×192)  — Android / maskable
        web-app-manifest-512x512.png  (512×512)  — Android / maskable

    static/favicon/splash/
        apple-splash-*.png  (14 device sizes, portrait)

    static/images/pwa/
        screenshot-desktop.png   (1280×720)  — install prompt wide
        screenshot-mobile.png    (390×844)   — install prompt narrow
══════════════════════════════════════════════════════════════════════
"""

import argparse
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── CLI args ──────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description='Generate PWA assets for PrimeBooks')
parser.add_argument(
    '--favicon-dir',
    default='static/favicon',
    help='Path to your favicon directory (default: static/favicon)',
)
parser.add_argument(
    '--static-dir',
    default='static',
    help='Path to your static root (default: static)',
)
args = parser.parse_args()

FAVICON_DIR    = Path(args.favicon_dir)
STATIC_DIR     = Path(args.static_dir)
SPLASH_DIR     = FAVICON_DIR / 'splash'
SCREENSHOT_DIR = STATIC_DIR / 'images' / 'pwa'

# Create output directories
SPLASH_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# ── Source images ─────────────────────────────────────────────────────
SOURCE_LARGE = FAVICON_DIR / 'web-app-manifest-512x512.png'   # best quality source
SOURCE_ICON  = FAVICON_DIR / 'apple-touch-icon.png'            # 180×180 iOS icon
SOURCE_SMALL = FAVICON_DIR / 'favicon-96x96.png'               # fallback if above missing

# Pick the best available source
if SOURCE_LARGE.exists():
    SOURCE = SOURCE_LARGE
    print(f'✓ Using source: {SOURCE_LARGE}')
elif SOURCE_ICON.exists():
    SOURCE = SOURCE_ICON
    print(f'✓ Using source: {SOURCE_ICON}')
elif SOURCE_SMALL.exists():
    SOURCE = SOURCE_SMALL
    print(f'✓ Using source: {SOURCE_SMALL}')
else:
    print('✗ ERROR: No source image found. Expected one of:')
    print(f'    {SOURCE_LARGE}')
    print(f'    {SOURCE_ICON}')
    print(f'    {SOURCE_SMALL}')
    sys.exit(1)

# Load source as RGBA for clean resizing
src = Image.open(SOURCE).convert('RGBA')
print(f'  Source size: {src.size[0]}×{src.size[1]}')


# ── Helper: resize with high-quality Lanczos and paste onto solid background ──

def make_icon(size: int, dest: Path, bg_color=(255, 255, 255, 255), force=False):
    """
    Create a square icon at `size`×`size` pixels.
    Pastes the source image centred on a solid background.
    iOS requires no transparency — background defaults to white.
    """
    if dest.exists() and not force:
        print(f'  ↷ Skip (exists): {dest.name}')
        return

    canvas = Image.new('RGBA', (size, size), bg_color)
    icon   = src.copy()
    icon.thumbnail((size, size), Image.LANCZOS)

    # Centre the icon
    offset_x = (size - icon.width)  // 2
    offset_y = (size - icon.height) // 2
    canvas.paste(icon, (offset_x, offset_y), icon)

    # Save as RGB PNG (no transparency — required for apple-touch-icon)
    canvas.convert('RGB').save(dest, 'PNG', optimize=True)
    print(f'  ✓ {dest.name} ({size}×{size})')


# ── 1. Apple touch icons ──────────────────────────────────────────────

print('\n── Apple Touch Icons ──')

make_icon(180, FAVICON_DIR / 'apple-touch-icon.png',         force=True)  # refresh/verify
make_icon(167, FAVICON_DIR / 'apple-touch-icon-167x167.png')
make_icon(152, FAVICON_DIR / 'apple-touch-icon-152x152.png')
make_icon(120, FAVICON_DIR / 'apple-touch-icon-120x120.png')


# ── 2. Android manifest icons ─────────────────────────────────────────
# These are regenerated to ensure both 'any' and 'maskable' use
# the same clean image (maskable icons need the logo within 80%
# safe zone — we centre it in 80% of the canvas).

print('\n── Android Manifest Icons ──')

def make_manifest_icon(size: int, dest: Path):
    """
    Creates a manifest icon with the logo scaled to 80% of canvas
    (safe zone for maskable icons) on a white background.
    """
    if dest.exists():
        print(f'  ↷ Skip (exists): {dest.name}')
        return

    canvas   = Image.new('RGBA', (size, size), (255, 255, 255, 255))
    safe     = int(size * 0.80)   # 80% safe zone for maskable
    icon     = src.copy()
    icon.thumbnail((safe, safe), Image.LANCZOS)
    offset_x = (size - icon.width)  // 2
    offset_y = (size - icon.height) // 2
    canvas.paste(icon, (offset_x, offset_y), icon)
    canvas.convert('RGB').save(dest, 'PNG', optimize=True)
    print(f'  ✓ {dest.name} ({size}×{size}, 80% safe zone)')

make_manifest_icon(192, FAVICON_DIR / 'web-app-manifest-192x192.png')
make_manifest_icon(512, FAVICON_DIR / 'web-app-manifest-512x512.png')


# ── 3. iOS Splash screens ─────────────────────────────────────────────
# Each splash is a full-screen image for a specific device.
# Logo centred on a solid background matching your brand colour.

print('\n── iOS Splash Screens ──')

# Your brand background colour for splash screens
# Change this to match your app's launch screen colour
SPLASH_BG    = (249, 250, 251)   # #f9fafb — your light theme background
SPLASH_BG_RGB = SPLASH_BG

# How large the logo appears on the splash (% of shortest dimension)
LOGO_SCALE = 0.30

# (width, height, filename_suffix)
SPLASH_SIZES = [
    # iPhones
    (1320, 2868, 'apple-splash-1320-2868.png'),   # iPhone 16 Pro Max
    (1206, 2622, 'apple-splash-1206-2622.png'),   # iPhone 16 Pro
    (1290, 2796, 'apple-splash-1290-2796.png'),   # iPhone 16 Plus / 15 Plus / 14 Pro Max
    (1179, 2556, 'apple-splash-1179-2556.png'),   # iPhone 16 / 15 / 14 Pro
    (1284, 2778, 'apple-splash-1284-2778.png'),   # iPhone 14 Plus / 13 Pro Max
    (1170, 2532, 'apple-splash-1170-2532.png'),   # iPhone 14 / 13 Pro / 13 / 12
    (1125, 2436, 'apple-splash-1125-2436.png'),   # iPhone 13 mini / 12 mini / X / XS
    (1242, 2688, 'apple-splash-1242-2688.png'),   # iPhone 11 Pro Max / XS Max
    ( 828, 1792, 'apple-splash-828-1792.png'),    # iPhone 11 / XR
    (1242, 2208, 'apple-splash-1242-2208.png'),   # iPhone 8 Plus / 7 Plus
    ( 750, 1334, 'apple-splash-750-1334.png'),    # iPhone 8 / 7 / SE
    # iPads
    (2048, 2732, 'apple-splash-2048-2732.png'),   # iPad Pro 12.9"
    (1668, 2388, 'apple-splash-1668-2388.png'),   # iPad Pro 11" / Air 11"
    (1640, 2360, 'apple-splash-1640-2360.png'),   # iPad Air 10.9" / iPad 10.9"
    (1488, 2266, 'apple-splash-1488-2266.png'),   # iPad Mini 6th gen
]

for w, h, filename in SPLASH_SIZES:
    dest = SPLASH_DIR / filename
    if dest.exists():
        print(f'  ↷ Skip (exists): {filename}')
        continue

    canvas = Image.new('RGB', (w, h), SPLASH_BG_RGB)

    # Scale logo to LOGO_SCALE × shortest dimension
    logo_size = int(min(w, h) * LOGO_SCALE)
    logo = src.copy()
    logo.thumbnail((logo_size, logo_size), Image.LANCZOS)

    # Centre logo
    offset_x = (w - logo.width)  // 2
    offset_y = (h - logo.height) // 2

    # Paste with alpha mask
    canvas.paste(logo, (offset_x, offset_y), logo)

    canvas.save(dest, 'PNG', optimize=True)
    print(f'  ✓ {filename} ({w}×{h})')


# ── 4. Install prompt screenshots ─────────────────────────────────────
# Chrome on Android shows these in the "Add to Home Screen" bottom sheet.
# We generate simple branded placeholders — replace with real screenshots
# once your app is running.

print('\n── PWA Install Screenshots (placeholders) ──')

def make_screenshot(width: int, height: int, dest: Path, label: str):
    if dest.exists():
        print(f'  ↷ Skip (exists): {dest.name}')
        return

    canvas = Image.new('RGB', (width, height), (37, 99, 235))   # #2563eb primary blue

    # Place logo top-centre
    logo_size = int(min(width, height) * 0.18)
    logo = src.copy().convert('RGBA')
    logo.thumbnail((logo_size, logo_size), Image.LANCZOS)

    # Create white version of logo for contrast on blue bg
    white_canvas = Image.new('RGBA', logo.size, (255, 255, 255, 255))
    white_canvas.paste(logo, (0, 0), logo)

    logo_x = (width  - white_canvas.width)  // 2
    logo_y = int(height * 0.35)
    canvas.paste(white_canvas, (logo_x, logo_y))

    # Add app name text if font is available
    draw = ImageDraw.Draw(canvas)
    try:
        font_large = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 48)
        font_small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 28)
    except (IOError, OSError):
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # "PrimeBooks" title
    title = 'PrimeBooks'
    bbox  = draw.textbbox((0, 0), title, font=font_large)
    tw    = bbox[2] - bbox[0]
    tx    = (width - tw) // 2
    ty    = logo_y + white_canvas.height + 40
    draw.text((tx, ty), title, font=font_large, fill=(255, 255, 255))

    # Subtitle
    subtitle = 'Modern Business Management'
    bbox2    = draw.textbbox((0, 0), subtitle, font=font_small)
    sw       = bbox2[2] - bbox2[0]
    sx       = (width - sw) // 2
    sy       = ty + 65
    draw.text((sx, sy), subtitle, font=font_small, fill=(191, 219, 254))  # blue-200

    canvas.save(dest, 'PNG', optimize=True)
    print(f'  ✓ {dest.name} ({width}×{height}) — replace with a real screenshot later')

make_screenshot(1280,  720, SCREENSHOT_DIR / 'screenshot-desktop.png', 'Desktop')
make_screenshot( 390,  844, SCREENSHOT_DIR / 'screenshot-mobile.png',  'Mobile')


# ── Summary ───────────────────────────────────────────────────────────

print('\n' + '═' * 60)
print('✅  PWA asset generation complete!')
print('═' * 60)
print(f'\nFavicon dir:    {FAVICON_DIR.resolve()}')
print(f'Splash dir:     {SPLASH_DIR.resolve()}')
print(f'Screenshot dir: {SCREENSHOT_DIR.resolve()}')
print("""
Next steps:
  1. Run collectstatic:
       python manage.py collectstatic --noinput

  2. Replace the placeholder screenshots in static/images/pwa/
     with real app screenshots once your app is running.

  3. In base.html <head>, add the tags from pwa_head_tags.html
     (the other file delivered with this script).

  4. Test iOS install:
     - Open your site in Safari on iPhone
     - Tap Share → Add to Home Screen
     - Should show your icon and "PrimeBooks" name correctly

  5. Test Android install:
     - Open in Chrome → three-dot menu → Add to Home Screen
     - Or wait for the automatic install banner

  6. Verify with Lighthouse:
       Lighthouse → PWA audit in Chrome DevTools
""")