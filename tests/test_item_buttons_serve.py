"""The game's layouts served with the HUD's item buttons (host/prompts.c build_layouts): item_buttons/Common.blarc, which
nx2/item_buttons_layout.py writes with its stamp, is the base when the stamp is there and Item assignable buttons is on as the
game starts (hookshot_options.ini, item_buttons_on), with the button prompts' runs or without and with a prompts folder or
without, and the file a change of prompts while the game runs puts the bytes back from; with the row off, or without the stamp,
everything is as before.

build_layouts, layout_runs, setup, game_dir and the zstd writer are cut out of host/prompts.c into a fixture, with stand-ins
for the Win32 calls, the controls and the log, and run on made-up game folders, one per run (setup looks once per process):

- prompts/ alone, the Switch's places: prompts/Common.blarc.zs, the game's bytes (served all the same, for a change while the
  game runs); A and B swapped: the Talk ring's runs over prompts/Common.blarc, and the key as it always was (the places, then
  ring.bin); the live part's file prompts/Common.blarc;
- item_buttons/ alone: item_buttons/Common.blarc.zs, the base as it is, the key the stamp, no live part; without the stamp
  nothing; no folder at all nothing;
- both, A and B swapped: the ring's runs over item_buttons/Common.blarc, prompts/Common.blarc.zs not written, the live part's
  file item_buttons/Common.blarc; the Switch's places: the base with no runs;
- the cache: the same stamp keeps item_buttons/Common.blarc.zs, a new stamp writes it again;
- the row off (or not in the options file): item_buttons/ alone serves nothing, both serve prompts/ as without item_buttons/,
  and the log says why. The key read is the one the menu writes for the row (gpu/vk/vk_menu.cpp ini_key).

python -I -B tests/test_item_buttons_serve.py [--cc gcc]
"""
import argparse
import os
import re
import struct
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "gpu/vk/vk_api.h"
#define MAX_PATH 260
typedef long LONG;
typedef unsigned long DWORD;
#define INVALID_FILE_ATTRIBUTES ((DWORD)-1)
static LONG InterlockedCompareExchange(volatile LONG *p, LONG v, LONG cmp) { const LONG o = *p; if (o == cmp) *p = v; return o; }
static LONG InterlockedExchange(volatile LONG *p, LONG v) { const LONG o = *p; *p = v; return o; }
static void Sleep(DWORD ms) { (void)ms; }
static DWORD GetFileAttributesA(const char *path) { struct stat st; return stat(path, &st) ? INVALID_FILE_ATTRIBUTES : 0; }
static const char *exe;
static DWORD hos_game_path_a(char *out, DWORD cap) { snprintf(out, cap, "%s", exe); return (DWORD)strlen(out); }
static void hos_log(const char *fmt, ...) {
    va_list a;
    va_start(a, fmt);
    printf("log: "), vprintf(fmt, a), printf("\n");
    va_end(a);
}
static int swapped;   /* (the controls: the Switch's, or A and B swapped) */
static int hos_binding(int set, int button, int slot) {
    static const int pads[4] = {HOS_PAD_EAST, HOS_PAD_SOUTH, HOS_PAD_NORTH, HOS_PAD_WEST};
    (void)slot;
    if (set != HOS_BIND_PAD || button > HOS_SW_Y) return -1;
    return swapped && button < 2 ? pads[1 - button] : pads[button];
}
static int choose_face(const char *dir) { (void)dir; return 0; }
enum { PART_TEXTURES, PART_LAYOUTS, PART_FONT, PARTS };
static int served_part = -1;
static void part_served(int p, int face, const int *bind) { (void)face, (void)bind, served_part = p; }
@@CODE@@
int main(int argc, char **argv) {
    exe = argv[1];
    swapped = argc > 2 && !strcmp(argv[2], "swapped");
    char out[MAX_PATH] = "";
    const int ok = build_layouts(out, sizeof out);
    printf("served %d %s\n", ok, ok ? out : "-");
    printf("live %d %llu %s\n", served_part, (unsigned long long)lay_n, lay_n ? lay.path : "-");
    return 0;
}
"""


def block(text, marker):
    if text.count(marker) != 1:
        raise SystemExit("FAIL: host/prompts.c has %d of %r" % (text.count(marker), marker))
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def line(text, pattern):
    m = re.search(pattern, text, re.M)
    if not m:
        raise SystemExit("FAIL: host/prompts.c has no line like %r" % pattern)
    return m.group(0)


def span(text, pattern):
    m = re.search(pattern, text, re.M | re.S)
    if not m:
        raise SystemExit("FAIL: host/prompts.c has nothing like %r" % pattern)
    return m.group(0)


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def fnv(h, data):
    for c in data:
        h = ((h ^ c) * 0x100000001B3) & ((1 << 64) - 1)
    return h


def unframe(z):
    """a zstd frame of raw blocks (prompts.c zstd_head, zstd_block): its content"""
    check(z[:4] == bytes.fromhex("28b52ffd") and z[4] == 0x80, "not a frame as zstd_head makes it")
    size, = struct.unpack_from("<I", z, 6)
    at, out = 10, bytearray()
    while True:
        bh = int.from_bytes(z[at:at + 3], "little")
        check(bh >> 1 & 3 == 0, "a block that is not raw")
        out += z[at + 3:at + 3 + (bh >> 3)]
        at += 3 + (bh >> 3)
        if bh & 1:
            break
    check(len(out) == size and at == len(z), "the frame's size is not its content's")
    return bytes(out)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host" / "prompts.c").read_text(encoding="utf-8")
    code = "\n".join([
        line(src, r"^static const char \*const faces\[HOS_PROMPT_N\] = .*$"),
        block(src, "static int game_dir("), block(src, "static int item_buttons_on("),
        line(src, r"^static uint32_t rd32le\(.*$"), line(src, r"^static void wr32le\(.*$"),
        block(src, "static void zstd_head("), block(src, "static int zstd_block("),
        block(src, "static uint8_t *read_all("),
        line(src, r"^static volatile LONG setup_state;.*$"),
        block(src, "static int setup("), block(src, "static uint64_t fnv("),
        line(src, r"^typedef struct \{ uint32_t off, len, idx; const uint8_t \*data; \} Run;.*$"),
        block(src, "static int run_cmp("), block(src, "static int run_order("), block(src, "static void add_run("),
        block(src, "static int write_patched("), block(src, "static void ring_places("),
        line(src, r"^#define BINDS .*$"), block(src, "static int first_key("),
        block(src, "static void current_binds("), block(src, "static int in_runs("),
        span(src, r"typedef struct \{\n    char path\[MAX_PATH\];.*?\} Live;"),
        line(src, r"^static Live lay;.*$"),
        span(src, r"typedef struct \{\n    Run \*runs;.*?\} Layout;"),
        line(src, r"^static int layout_runs\(const char \*dir, int face, const int \*bind, Layout \*o\);$"),
        block(src, "static void layout_free("),
        line(src, r"^static Layout lay_start;.*$"), line(src, r"^static uint8_t lay_head\[32\];.*$"),
        line(src, r"^static uint64_t lay_n;.*$"),
        block(src, "static int build_layouts("),
        block(src, "static int layout_runs(const char *dir, int face, const int *bind, Layout *o) {"),
    ])
    base_prompts = bytes(range(256)) * 600   # (153,600 bytes: two 128 KB blocks)
    base_items = bytes(reversed(range(256))) * 600
    # ring.bin: one entry the swapped places choose (group A placed south: place 1), one they do not
    ring = b"HPRG" + struct.pack("<I", 2)
    ring += struct.pack("<BBBBI", 0, 0, 1, 0, 2) + struct.pack("<II", 100, 3) + b"abc" + struct.pack("<II", 131070, 4) + b"wxyz"
    ring += struct.pack("<BBBBI", 0, 0, 2, 0, 1) + struct.pack("<II", 20, 2) + b"no"

    def patched(base):
        b = bytearray(base)
        b[100:103], b[131070:131074] = b"abc", b"wxyz"
        return bytes(b)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        c, exe = tmp / "serve.c", tmp / "serve"
        c.write_text(FIXTURE.replace("@@CODE@@", code), encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-format-truncation", "-I", str(ROOT), str(c), "-o",
                        str(exe)], check=True)   # (paths cut at MAX_PATH, as prompts.c has them everywhere)

        def game(name, prompts=False, items=False, stamp=b"28 0123456789abcdef\n", option=1):
            d = tmp / name
            d.mkdir()
            lines = ["button_prompts=4", "vsync=1"] + (["item_assignable_buttons=%d" % option] if option is not None else [])
            (d / "hookshot_options.ini").write_text("\n".join(lines) + "\n")   # (the menu's options file: the row among others)
            if prompts:
                (d / "prompts").mkdir(parents=True)
                (d / "prompts" / "Common.blarc").write_bytes(base_prompts)
                (d / "prompts" / "ring.bin").write_bytes(ring)
            if items:
                (d / "item_buttons").mkdir(parents=True)
                (d / "item_buttons" / "Common.blarc").write_bytes(base_items)
                if stamp:
                    (d / "item_buttons" / "Common.blarc.stamp").write_bytes(stamp)
            d.mkdir(exist_ok=True)
            return d

        def serve(d, controls="switch"):
            r = subprocess.run([str(exe), os.path.join(str(d), "hookshot.exe"), controls], capture_output=True, text=True)
            check(r.returncode == 0, "the fixture failed: %r" % r.stderr)
            got = [ln for ln in r.stdout.splitlines() if ln.startswith("served ")]
            check(len(got) == 1, "the fixture said %r" % r.stdout)
            ok, path = got[0].split(" ", 2)[1:]
            live = [ln.split(" ", 3)[1:] for ln in r.stdout.splitlines() if ln.startswith("live ")]
            check(len(live) == 1, "the fixture said %r" % r.stdout)
            serve.live = (int(live[0][0]), int(live[0][1]), live[0][2])
            return int(ok), path, r.stdout

        place_switch, place_swapped = struct.pack("<4i", 0, 1, 2, 3), struct.pack("<4i", 1, 0, 2, 3)
        h0 = 0xCBF29CE484222325

        d = game("prompts-only", prompts=True)
        ok, path, _ = serve(d)
        check(ok and Path(path) == d / "prompts" / "Common.blarc.zs", "prompts/ with no runs: %s" % path)
        check(unframe(Path(path).read_bytes()) == base_prompts, "prompts/ with no runs: not the game's bytes")
        check(serve.live[:2] == (1, len(base_prompts)) and Path(serve.live[2]) == d / "prompts" / "Common.blarc",
              "prompts/ with no runs: the live part %r" % (serve.live,))
        d = game("prompts-swapped", prompts=True)
        ok, path, log = serve(d, "swapped")
        check(ok and Path(path) == d / "prompts" / "Common.blarc.zs", "prompts/ with runs: %s" % path)
        check(unframe(Path(path).read_bytes()) == patched(base_prompts), "prompts/ with runs: not the runs over its base")
        check((d / "prompts" / "Common.blarc.key").read_text() == "%016x" % fnv(fnv(h0, place_swapped), ring),
              "prompts/ with runs: the key is not the places then ring.bin")
        check("item buttons" not in log, "prompts/ alone logs the item buttons")
        check(serve.live[:2] == (1, len(base_prompts)) and Path(serve.live[2]) == d / "prompts" / "Common.blarc",
              "prompts/ with runs: the live part %r" % (serve.live,))

        d = game("items-only", items=True)
        ok, path, log = serve(d, "swapped")
        stamp = (d / "item_buttons" / "Common.blarc.stamp").read_bytes()
        check(ok and Path(path) == d / "item_buttons" / "Common.blarc.zs", "item_buttons/ alone: %s" % path)
        check(unframe(Path(path).read_bytes()) == base_items, "item_buttons/ alone: not its base as it is")
        check((d / "item_buttons" / "Common.blarc.key").read_text() == "%016x" % fnv(h0, stamp),
              "item_buttons/ alone: the key is not the stamp")
        check("item buttons" in log and "Talk ring" not in log, "item_buttons/ alone: the log %r" % log)
        check(serve.live == (-1, 0, "-"), "item_buttons/ alone: a live part %r (no prompts: no change while it runs)" %
              (serve.live,))
        Path(path).write_bytes(b"kept")   # (the same stamp: the file the key names is kept)
        check(serve(d, "swapped")[0] and Path(path).read_bytes() == b"kept", "the same stamp wrote the file again")
        (d / "item_buttons" / "Common.blarc").write_bytes(base_prompts)
        (d / "item_buttons" / "Common.blarc.stamp").write_bytes(b"28 fedcba9876543210\n")
        check(serve(d, "swapped")[0] and unframe(Path(path).read_bytes()) == base_prompts, "a new stamp kept the old file")

        # the row off as the game starts, or not in the file: the game's own layouts (prompts/ as without item_buttons/)
        for option in (0, None):
            d = game("items-off-%s" % option, items=True, option=option)
            ok, _, log = serve(d, "swapped")
            check(not ok and not (d / "item_buttons" / "Common.blarc.zs").exists(), "item_buttons/ served with the row %s" % option)
            check(option is None or "Item assignable buttons being off" in log, "the row off: the log %r" % log)
            d = game("both-off-%s" % option, prompts=True, items=True, option=option)
            ok, path, log = serve(d, "swapped")
            check(ok and Path(path) == d / "prompts" / "Common.blarc.zs" and
                  unframe(Path(path).read_bytes()) == patched(base_prompts), "both, the row off: not prompts/ with its runs")
            check(not (d / "item_buttons" / "Common.blarc.zs").exists(), "both, the row off: item_buttons/ written")
            check(serve.live[:2] == (1, len(base_prompts)) and Path(serve.live[2]) == d / "prompts" / "Common.blarc",
                  "both, the row off: the live part %r" % (serve.live,))
            check((d / "prompts" / "Common.blarc.key").read_text() == "%016x" % fnv(fnv(h0, place_swapped), ring),
                  "both, the row off: the key is not prompts/'s alone")
        menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
        row = re.search(r'\{TAB_CONTROLS, "([^"]+)", &opts\.item_buttons,', menu)
        check(row is not None and "&opts.item_buttons)" not in block(menu, "const char* ini_key("),
              "the menu's Item assignable buttons row is not found, or has a key of its own")
        key = row.group(1).lower().replace(" ", "_")
        check('"%s="' % key in block(src, "static int item_buttons_on("), "host/prompts.c reads another key than the menu's %s" % key)

        d = game("items-no-stamp", items=True, stamp=None)
        check(not serve(d)[0], "item_buttons/ without its stamp was served")
        check(not serve(game("nothing"))[0], "a game folder with neither was served")

        d = game("both", prompts=True, items=True)
        ok, path, log = serve(d, "swapped")
        check(ok and Path(path) == d / "item_buttons" / "Common.blarc.zs", "both, runs: %s" % path)
        check(unframe(Path(path).read_bytes()) == patched(base_items), "both, runs: not the ring's runs over item_buttons/")
        check(not (d / "prompts" / "Common.blarc.zs").exists(), "both, runs: prompts/Common.blarc.zs written")
        check("Talk ring" in log and "item buttons" in log, "both, runs: the log does not say both")
        check(serve.live[:2] == (1, len(base_items)) and Path(serve.live[2]) == d / "item_buttons" / "Common.blarc",
              "both, runs: the live part is not item_buttons/Common.blarc: %r" % (serve.live,))
        d = game("both-switch", prompts=True, items=True)
        ok, path, _ = serve(d)
        check(ok and unframe(Path(path).read_bytes()) == base_items, "both, no runs: not item_buttons/ as it is")
        check((d / "item_buttons" / "Common.blarc.key").read_text() == "%016x" % fnv(fnv(h0, place_switch),
              (d / "item_buttons" / "Common.blarc.stamp").read_bytes()), "both, no runs: the key")
    print("ok: the layouts' base is item_buttons/ with its stamp and the row on at the start, runs or none, prompts/ or none, "
          "and the live part's file; with the row off, or prompts/ alone, as before")


if __name__ == "__main__":
    main()
