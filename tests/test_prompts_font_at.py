"""Game-free: where the game keeps the button prompts' font, found from FreeType's glyph render (host/prompts.c
hos_prompts_glyph), so a change while the game runs reaches the icons in texts.

The game hands FreeType every font decrypted at the stream's start, with the file's length (its 8-byte header counted) as
the stream's size: the game's own fonts and the prompts' alike. hos_prompts_glyph is compiled with the font's record and a
guest window holding a glyph slot, its face and the face's stream, and is to find the font:

- at the stream's start, its size the file's (the game's way);
- at the stream's start, its size the font's alone (the file's less the header);
- behind its 8-byte header, its size the file's;

and not to take another font of the same size (a face then not looked at again), one of another size, or a stream not
readable yet (looked at again, and found once it is).

python -I -B tests/test_prompts_font_at.py [--cc gcc]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static void hos_log(const char *fmt, ...) { (void)fmt; }
enum { WINDOW = 1 << 20 };
static uint8_t window[WINDOW];    /* (guest addresses: offsets into it, from 0x1000) */
static uint64_t readable = WINDOW;   /* (guest memory past it is not mapped) */
static void *hos_guest_range(uint64_t a, uint64_t n) {
    return a >= 0x1000 && a < readable && n <= readable - a ? window + a : NULL;
}
%(font)s
%(glyph)s

static int fails;
#define CHECK(x, what) do { if (!(x)) { printf("FAIL: %%s\n", what); fails++; } } while (0)
enum { N = 4096 };                 /* (the font file's length, its 8-byte header counted) */
static uint64_t next_face = 0x2000;
static void put64(uint64_t a, uint64_t v) { memcpy(window + a, &v, 8); }
/* a glyph slot of a new face whose stream starts at base with size bytes; the slot's address */
static uint64_t slot_of(uint64_t base, uint64_t size) {
    const uint64_t face = next_face, stream = face + 0x400, slot = face + 0x800;
    next_face += 0x1000;
    put64(slot + 8, face), put64(face + 192, stream), put64(stream, base), put64(stream + 8, size);
    return slot;
}
static void font_bytes(uint64_t at) { for (int i = 0; i < N - 8; i++) window[at + i] = (uint8_t)(i * 7 + 3); }
static void reset(void) {
    font.at = 0, font.n = N;
    for (int i = 0; i < 64; i++) font.head[i] = (uint8_t)(i * 7 + 3);
}
int main(void) {
    /* the game's way: the font at the stream's start, its size the file's */
    reset();
    font_bytes(0x40000);
    hos_prompts_glyph(slot_of(0x40000, N));
    CHECK(font.at == 0x40000, "the font at the stream's start with the file's length as its size: not found");
    /* at the stream's start, its size the font's alone */
    reset();
    font_bytes(0x50000);
    hos_prompts_glyph(slot_of(0x50000, N - 8));
    CHECK(font.at == 0x50000, "the font at the stream's start with its own length as its size: not found");
    /* behind its 8-byte header, its size the file's */
    reset();
    memset(window + 0x60000, 0xAA, 8);
    font_bytes(0x60008);
    hos_prompts_glyph(slot_of(0x60000, N));
    CHECK(font.at == 0x60008, "the font behind its header: not found");
    /* another font of that size: not taken, and its face not looked at again */
    reset();
    memset(window + 0x70000, 0x55, N);
    const uint64_t other = slot_of(0x70000, N);
    hos_prompts_glyph(other);
    CHECK(font.at == 0, "another font of the font's size taken");
    font_bytes(0x70000);
    hos_prompts_glyph(other);
    CHECK(font.at == 0, "a face found to be another font looked at again");
    /* another size */
    reset();
    font_bytes(0x80000);
    hos_prompts_glyph(slot_of(0x80000, N + 16));
    CHECK(font.at == 0, "a font of another size taken");
    /* not readable yet: looked at again, found once it is */
    reset();
    font_bytes(0x90000);
    const uint64_t late = slot_of(0x90000, N);
    readable = 0x90000 + 100;
    hos_prompts_glyph(late);
    CHECK(font.at == 0, "a font not readable taken");
    readable = WINDOW;
    hos_prompts_glyph(late);
    CHECK(font.at == 0x90000, "a font not readable at first not looked at again");
    if (!fails) printf("PASS\n");
    return fails != 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host" / "prompts.c").read_text(encoding="utf-8")
    font = re.search(r"static struct \{\n    volatile uint64_t at;.*?\} font;", src, re.S)
    check(font is not None, "host/prompts.c has no font record")
    glyph = block(src, "void hos_prompts_glyph(uint64_t slot) {")
    with tempfile.TemporaryDirectory() as tmp:
        c, exe = Path(tmp) / "font_at.c", Path(tmp) / "font_at"
        c.write_text(HARNESS % {"font": font.group(0), "glyph": glyph}, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        if r.returncode or "PASS" not in r.stdout:
            raise SystemExit((r.stdout + r.stderr).strip() or "FAIL: the harness failed")
    print("ok: the font is found at its stream's start (the game's way, the file's length or its own as the size) or behind "
          "its header; another font, another size or a stream not readable yet is not taken")


if __name__ == "__main__":
    main()
