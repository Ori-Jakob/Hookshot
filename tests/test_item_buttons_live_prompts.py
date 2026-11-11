"""The item buttons' glyph checks after a change of button prompts while the game runs (host/oot_item_buttons.c ib_same_glyph,
host/prompts.c hos_prompts_game_code). The control guide tells ZR's entries by their text, and the pause menu's tab bar sets its
glyphs only when the pane's text differs; after a live change the prompts rewrite every text's button codes to codes of their
own for the face and the pad input (text_code). A pane's text is still the key's glyph when its codes show the same buttons.

text_code and hos_prompts_game_code are cut out of host/prompts.c, ib_code3 and ib_same_glyph out of host/oot_item_buttons.c,
and run on each face with some buttons bound elsewhere: each Switch button's and d-pad icon's code, rewritten, is its own
glyph and no other's; texts around the codes (the guide's combo with its comma and plus) compare byte for byte; a length or
a byte that differs is not the same; a code no prompt rewrites (a letter's, a face's pad icon) is compared as it is. Also that
the control guide and the tab bar compare by ib_same_glyph.

python -I -B tests/test_item_buttons_live_prompts.py [--cc gcc]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "gpu/vk/vk_api.h"
@@PROMPTS@@
@@BUTTONS@@
static int fails;
#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s\n", __LINE__, #x); fails++; } } while (0)
static int put(char *t, unsigned c) {   /* (UTF-8, three bytes) */
    t[0] = (char)(0xE0 | c >> 12), t[1] = (char)(0x80 | (c >> 6 & 0x3F)), t[2] = (char)(0x80 | (c & 0x3F));
    return 3;
}
static int same(const char *s, int n, const char *k, int kn) { return ib_same_glyph((const uint8_t *)s, n, k, kn); }
int main(void) {
    int bind[HOS_SW_N];
    for (int b = 0; b < HOS_SW_N; b++) bind[b] = -1;
    bind[HOS_SW_A] = HOS_PAD_SOUTH, bind[HOS_SW_ZR] = HOS_PAD_LSHOULDER, bind[HOS_SW_L] = HOS_PAD_RTRIGGER;
    for (int face = 0; face < HOS_PROMPT_N; face++) {
        for (int b = 0; b < HOS_SW_N; b++) {
            char game[3], now[3], other[3];
            const int c = text_code(switch_code[b], face, bind);
            put(game, switch_code[b]), put(now, (unsigned)c), put(other, switch_code[(b + 1) % HOS_SW_N]);
            CHECK(c >= 0 && (unsigned)c != switch_code[b]);
            CHECK(hos_prompts_game_code((unsigned)c) == switch_code[b]);
            CHECK(same(now, 3, game, 3) && same(game, 3, game, 3));
            CHECK(!same(now, 3, other, 3) && !same(other, 3, game, 3));
            /* (rewritten again: another face's code of the same button) */
            char again[3];
            put(again, (unsigned)text_code((unsigned)c, (face + 1) % HOS_PROMPT_N, bind));
            CHECK(same(again, 3, game, 3) && same(again, 3, now, 3));
        }
        for (int k = 0; k < 3; k++) {
            char game[3], now[3];
            const int c = text_code(static_code[k], face, bind);
            put(game, static_code[k]), put(now, (unsigned)c);
            CHECK(hos_prompts_game_code((unsigned)c) == static_code[k] && same(now, 3, game, 3));
            CHECK(!same(now, 3, game, 2));
        }
        /* the guide's combo: ZR, the hotkey L + A; the same combo with every code rewritten is the same text */
        char combo[16], live[16];
        int n = 0, m = 0;
        n += put(combo + n, switch_code[HOS_SW_ZR]), combo[n++] = ',';
        n += put(combo + n, switch_code[HOS_SW_L]), combo[n++] = '+';
        n += put(combo + n, switch_code[HOS_SW_A]);
        m += put(live + m, (unsigned)text_code(switch_code[HOS_SW_ZR], face, bind)), live[m++] = ',';
        m += put(live + m, (unsigned)text_code(switch_code[HOS_SW_L], face, bind)), live[m++] = '+';
        m += put(live + m, (unsigned)text_code(switch_code[HOS_SW_A], face, bind));
        CHECK(n == m && same(live, m, combo, n));
        live[3] = ' ';
        CHECK(!same(live, m, combo, n));   /* (a byte between the codes differs) */
        CHECK(!same(live, m - 3, combo, n) && !same(combo, n, combo, n - 1));
    }
    /* codes no prompt rewrites: compared as they are */
    char a[3], b[3];
    put(a, 0xE048), put(b, 0xE048);
    CHECK(hos_prompts_game_code(0xE048) == 0xE048 && same(a, 3, b, 3));
    put(b, 0xE04A);
    CHECK(!same(a, 3, b, 3));
    put(a, 0xF700), put(b, 0xF700 + 32);   /* (the Switch's and the Xbox face's south pad icons: not a text's codes) */
    CHECK(hos_prompts_game_code(0xF700) == 0xF700 && !same(a, 3, b, 3));
    CHECK(same("ab", 2, "ab", 2) && !same("ab", 2, "ac", 2) && same("", 0, "", 0));
    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""


def block(text, marker, where):
    if text.count(marker) != 1:
        raise SystemExit("FAIL: %s has %d of %r" % (where, text.count(marker), marker))
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    prompts = (ROOT / "host" / "prompts.c").read_text(encoding="utf-8")
    buttons = (ROOT / "host" / "oot_item_buttons.c").read_text(encoding="utf-8")
    defines = [re.search(r"^#define %s .*$" % name, prompts, re.M) for name in ("PAD_BASE", "FACE_CODES", "STATIC_AT", "BIND_BASE")]
    check(all(defines), "host/prompts.c lacks PAD_BASE, FACE_CODES, STATIC_AT or BIND_BASE")
    code = "\n".join([d.group(0) for d in defines] + [
        re.search(r"static const uint16_t switch_code\[HOS_SW_N\] = \{[^}]*\};", prompts).group(0),
        re.search(r"static const unsigned char switch_pad\[HOS_SW_N\] = \{[^}]*\};", prompts).group(0),
        re.search(r"static const uint16_t static_code\[3\] = \{[^}]*\};", prompts).group(0),
        block(prompts, "static int text_code(", "host/prompts.c"),
        block(prompts, "unsigned hos_prompts_game_code(", "host/prompts.c"),
    ])
    mine = "\n".join([block(buttons, "static unsigned ib_code3(", "host/oot_item_buttons.c"),
                      block(buttons, "static int ib_same_glyph(", "host/oot_item_buttons.c")])
    for guest in ("ib_peek", "GP(", "ib_guest", "recomp_"):
        check(guest not in mine, "ib_same_glyph reads guest memory")
    # the control guide's ZR entries and the tab bar's glyphs compare by it
    guide = block(buttons, "static void ib_ctrl_guide_locked(", "host/oot_item_buttons.c")
    check("ib_same_glyph((const uint8_t *)GP(text), len, ib_cg.zr, ib_cg.zr_len)" in guide,
          "the control guide does not tell ZR's entries by ib_same_glyph: after a live change of prompts no combo shows")
    tabs = block(buttons, "static void ib_tab_glyphs(", "host/oot_item_buttons.c")
    check("ib_same_glyph((const uint8_t *)GP(text), len, ib_tabs.key[want], ib_tabs.len[want])" in tabs,
          "the tab bar does not compare its glyphs by ib_same_glyph: after a live change of prompts it sets them each frame")
    check("memcmp(GP(text)" not in guide and "memcmp(GP(text)" not in tabs, "a glyph still compared byte for byte")
    with tempfile.TemporaryDirectory() as tmp:
        c, exe = Path(tmp) / "live.c", Path(tmp) / "live"
        c.write_text(HARNESS.replace("@@PROMPTS@@", code).replace("@@BUTTONS@@", mine), encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I", str(ROOT), str(c), "-o",
                        str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        check(r.returncode == 0 and "PASS" in r.stdout, r.stdout + r.stderr)
    print("ok: a key's glyph is still its own after the prompts rewrite it, on every face, and no other's; the control guide "
          "and the tab bar compare by it")


if __name__ == "__main__":
    main()
