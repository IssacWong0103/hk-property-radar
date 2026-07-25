"""Generate the PWA / home-screen icons (a simple HK skyline on brand blue).

Run once (or when rebranding):  python pipeline/make_icons.py
Writes PNGs into site/icons/.
"""
import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site", "icons")
TOP, BOT = (58, 138, 229), (24, 79, 149)   # brand blue gradient (#3a8ae5 -> #184f95)
WHITE = (252, 252, 251)


def draw_icon(size, maskable=False):
    img = Image.new("RGB", (size, size), BOT)
    d = ImageDraw.Draw(img, "RGBA")
    # vertical gradient background
    for y in range(size):
        t = y / size
        d.line([(0, y), (size, y)], fill=(
            int(TOP[0] + (BOT[0] - TOP[0]) * t),
            int(TOP[1] + (BOT[1] - TOP[1]) * t),
            int(TOP[2] + (BOT[2] - TOP[2]) * t)))
    # content safe zone (maskable icons get more padding so they survive masking)
    pad = size * (0.24 if maskable else 0.16)
    x0, y1 = pad, size - pad
    w = size - 2 * pad
    base = y1
    # a little skyline: (relative x, width, height) as fractions of w/h
    towers = [(0.02, 0.16, 0.42), (0.20, 0.20, 0.66), (0.43, 0.15, 0.52),
              (0.60, 0.18, 0.82), (0.80, 0.16, 0.58)]
    for rx, rw, rh in towers:
        bx = x0 + rx * w
        bw = rw * w
        bh = rh * (size - 2 * pad)
        d.rounded_rectangle([bx, base - bh, bx + bw, base], radius=max(2, size * 0.012), fill=WHITE)
        # windows
        step = bw / 3
        wy = base - bh + step * 0.5
        while wy < base - step * 0.4:
            for c in range(2):
                wx = bx + step * (0.5 + c)
                d.ellipse([wx - size*0.008, wy - size*0.008, wx + size*0.008, wy + size*0.008],
                          fill=(58, 138, 229, 200))
            wy += step
    if not maskable:
        # rounded-square mask for the whole icon
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=int(size * 0.22), fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask)
        return out
    return img.convert("RGBA")


def main():
    os.makedirs(OUT, exist_ok=True)
    draw_icon(512).save(os.path.join(OUT, "icon-512.png"))
    draw_icon(512).resize((192, 192), Image.LANCZOS).save(os.path.join(OUT, "icon-192.png"))
    draw_icon(180).save(os.path.join(OUT, "icon-180.png"))          # apple-touch
    draw_icon(512, maskable=True).save(os.path.join(OUT, "icon-maskable-512.png"))
    print("Icons written to", OUT)


if __name__ == "__main__":
    main()
