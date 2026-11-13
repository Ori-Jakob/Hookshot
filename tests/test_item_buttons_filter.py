"""The item buttons' controller filter (host/oot_item_buttons.c, ib_step): what the game is given of the hotkey, the face
buttons and ZR at each read of the controller.

The step is compiled alone (it reads no guest memory) with the header's constants, and fed reads of the buttons in the
three places it knows (play, the quick-switch menu, anywhere else) with the ZR modes the game side sets. Pinned here: off
it passes everything; the hotkey is hidden in play and in the menu and seen elsewhere, and one held when they end stays
hidden until it is let go; a face button pressed under the hotkey is taken (hidden) until it is let go, also when the
hotkey goes first, and one already down when the hotkey went down keeps going to the game; a press taken in play is a use
request and one in the menu an assign request (while the list takes one), each with its own sequence number; in the pause
menu L and R are hidden as well (its pages turn with ZL and ZR) until each is let go, and a face button under the hotkey is
taken on every page and an assign request of the pause menu's own while its Items page takes one; ZR: normal
passes it, hold hides it, face k presents it while k is taken and for at least three reads after a short tap, real
presents the real ZR and a press hidden earlier for at least three reads, a real ZR press is hidden in those and counted,
and a ZR held from before it was hidden is never given back; while face k's item is out (the game side says so: drawn
with the hotkey) the real ZR is presented in face k as well and not counted (it acts on that item, the use goes on), a
real ZR still down when the item goes is hidden until let go, one hidden or held from before the item came out is not
given to it, and out means nothing in the other modes; all of that in play only: elsewhere ZR is the game's as pressed,
uncounted, and nothing owed comes back with play. The edges are the filter's own: a read repeated (the game reads twice
the frame a pause starts) makes no second request.

What the filter is told is out, and what the control guide does with it, is compiled alone the same way: hook 3's reads of
Link's hands (ib_in_hand: the bow by its sub action, the hookshot aimed or in flight but not by its in-use item alone, the
boomerang, the stick and the hammer in use) and a bomb's latch (ib_bomb: from the frame the lift takes it, before it
leaves the pouch, while it is carried, gone when it is thrown or set down), so a use whose last bomb is lifted does not
end; and the guide's choice per entry (ib_entry: the combo on an open or opening ZR entry, the wanted one in place of
another of ours, the game's ZR back on a closing one or once nothing is out, other keys left).
python -I -B tests/test_item_buttons_filter.py   (needs a C compiler)
"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    while text[end] in ";\n":
        end += 1
        if text[end - 1] == "\n":
            break
    return text[start:end]


def between(text, first, last):
    """from the line that holds first to the end of the block that starts at last"""
    start = text.rindex("\n", 0, text.index(first)) + 1
    return text[start:text.index(last)] + block(text, last)


def header_constants():
    head = (ROOT / "host" / "oot_item_buttons.h").read_text(encoding="utf-8")
    lines = [block(head, "enum { IB_A"), block(head, "enum { IB_ADULT")]
    for name in ("IB_NONE", "IB_ITEMS"):
        lines += re.findall(r"^#define " + name + r"\b[^\n]*", head, re.M)
    return "\n".join(lines) + "\n"


PRELUDE = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
"""

MAIN = r"""
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
enum { A = 1 << 0, B = 1 << 1, X = 1 << 2, Y = 1 << 3, L = 1 << 6, R = 1 << 7, ZL = 1 << 8, ZR = 1 << 9 };
static IbFilter f;
static IbPoll p;
static uint32_t mode_seq;
static void set_mode(int mode, int button) { p.mode = ++mode_seq << 8 | (uint32_t)mode << 4 | (uint32_t)button; }
static uint64_t poll_(uint64_t buttons) { p.buttons = buttons; return ib_step(&f, &p); }
static void fresh(int context) {
    memset(&f, 0, sizeof f), memset(&p, 0, sizeof p);
    p.enabled = 1, p.hotkey = IB_BIT_L, p.context = context, p.can_use = 1, p.usable = 1;
    set_mode(IB_ZR_NORMAL, 0);
}
static unsigned seq(uint32_t request) { return request >> 4; }
static int button(uint32_t request) { return (int)(request & 0xf); }

int main(void) {
    /* off: everything as pressed, whatever the context */
    fresh(IB_CTX_PLAY), p.enabled = 0;
    CHECK(poll_(L | A | ZR) == (L | A | ZR));
    CHECK(f.use == 0 && f.taken == 0);
    /* turned off: the state forgotten, the sequence numbers kept (the hooks remember the last they saw) */
    fresh(IB_CTX_PLAY);
    CHECK(poll_(L) == 0 && poll_(L | A) == 0 && seq(f.use) == 1);
    p.enabled = 0;
    CHECK(poll_(L | A) == (L | A) && !f.taken && !f.hidden && seq(f.use) == 1);

    /* the hotkey: hidden in play and in the menu, the game's elsewhere; the other shoulder button always the game's */
    fresh(IB_CTX_PLAY);
    CHECK(poll_(L) == 0 && poll_(0) == 0);
    p.context = IB_CTX_MENU;
    CHECK(poll_(L) == 0 && poll_(0) == 0);
    p.context = IB_CTX_NONE;
    CHECK(poll_(L) == L && poll_(0) == 0);
    p.context = IB_CTX_PLAY;
    CHECK(poll_(R) == R && poll_(L | R) == R);
    p.hotkey = IB_BIT_R;
    poll_(0);
    CHECK(poll_(L | R) == L);
    /* held when play ends: hidden until it is let go (the pause menu sees no new press) */
    fresh(IB_CTX_PLAY);
    CHECK(poll_(L) == 0);
    p.context = IB_CTX_NONE;
    CHECK(poll_(L) == 0 && poll_(L) == 0 && poll_(0) == 0 && poll_(L) == L);
    /* pressed elsewhere, still held when play starts: hidden from then on, and after play too until let go */
    fresh(IB_CTX_NONE);
    CHECK(poll_(L) == L);
    p.context = IB_CTX_PLAY;
    CHECK(poll_(L) == 0);
    p.context = IB_CTX_NONE;
    CHECK(poll_(L) == 0 && poll_(0) == 0 && poll_(L) == L);

    /* a face button pressed under the hotkey is taken until it is let go, the hotkey let go first */
    fresh(IB_CTX_PLAY);
    poll_(L);
    CHECK(poll_(L | A) == 0 && f.taken == 1 && seq(f.use) == 1 && button(f.use) == IB_A);
    CHECK(poll_(A) == 0 && poll_(A) == 0);
    CHECK(poll_(0) == 0 && poll_(A) == A && seq(f.use) == 1);   /* (pressed again without it: the game's) */
    /* ... and when play ends meanwhile */
    fresh(IB_CTX_PLAY);
    poll_(L);
    CHECK(poll_(L | B) == 0);
    p.context = IB_CTX_NONE;
    CHECK(poll_(L | B) == 0 && poll_(B) == 0 && poll_(0) == 0 && poll_(B) == B);
    /* the hotkey and the face button in one read: taken */
    fresh(IB_CTX_PLAY);
    CHECK(poll_(L | X) == 0 && seq(f.use) == 1 && button(f.use) == IB_X);
    /* a face button already down when the hotkey goes down keeps going to the game (a dash, a dive, a charge) */
    fresh(IB_CTX_PLAY);
    CHECK(poll_(Y) == Y && poll_(Y | L) == Y && f.use == 0);
    CHECK(poll_(Y | L | A) == Y && button(f.use) == IB_A);
    CHECK(poll_(L) == 0 && poll_(Y | L) == 0 && button(f.use) == IB_Y && seq(f.use) == 2);   /* (Y pressed anew: taken) */
    /* the hotkey elsewhere: nothing taken, no request */
    fresh(IB_CTX_NONE);
    CHECK(poll_(L) == L && poll_(L | A) == (L | A) && f.use == 0 && f.assign == 0);
    /* the hotkey's place: large in play only */
    fresh(IB_CTX_PLAY);
    poll_(L);
    CHECK(f.large);
    p.context = IB_CTX_MENU;
    poll_(L);
    CHECK(!f.large);

    /* requests: in play a use, while nothing keeps the player from an item; in the menu an assign, while its list takes
       one. Each its own sequence; the latest wins */
    fresh(IB_CTX_PLAY);
    poll_(L), poll_(L | A), poll_(L), poll_(L | X);
    CHECK(seq(f.use) == 2 && button(f.use) == IB_X && f.assign == 0);
    p.can_use = 0;
    poll_(L);
    CHECK(poll_(L | B) == 0 && seq(f.use) == 2);   /* (taken, not used) */
    p.context = IB_CTX_MENU;
    poll_(L);
    CHECK(poll_(L | Y) == 0 && seq(f.assign) == 1 && button(f.assign) == IB_Y && seq(f.use) == 2);
    p.usable = 0;
    poll_(L);
    CHECK(poll_(L | A) == 0 && seq(f.assign) == 1);   /* (the list scrolling: hidden, so B and Y do not cancel or sort) */
    p.usable = 1;
    poll_(L);
    CHECK(poll_(L | A | B) == 0 && seq(f.assign) == 3 && button(f.assign) == IB_B);
    /* the pause menu: the hotkey hidden and L and R both (its pages turn with ZL and ZR), each until it is let go; ZL and ZR
       the game's; the hotkey held there is no large arrangement */
    fresh(IB_CTX_PAUSE);
    CHECK(poll_(L) == 0 && poll_(R) == 0 && poll_(L | R) == 0 && poll_(0) == 0 && !f.large);
    CHECK(poll_(ZL) == ZL && poll_(ZL | ZR) == (ZL | ZR) && poll_(0) == 0);
    p.hotkey = IB_BIT_R;
    CHECK(poll_(L) == 0 && poll_(0) == 0 && poll_(R) == 0);
    /* a shoulder button held as the pause menu closes: hidden until let go (no quick-switch press in play, no tab of the
       Minus panel) */
    fresh(IB_CTX_PAUSE);
    CHECK(poll_(R) == 0);
    p.context = IB_CTX_PLAY;
    CHECK(poll_(R) == 0 && poll_(0) == 0 && poll_(R) == R);
    fresh(IB_CTX_PAUSE);
    CHECK(poll_(R) == 0);
    p.context = IB_CTX_NONE;
    CHECK(poll_(R) == 0 && poll_(0) == 0 && poll_(R) == R && poll_(L) == L);
    /* a face button under the hotkey: taken on every page; a request of the pause menu's own (not the quick-switch menu's)
       only while its Items page takes one; A without the hotkey is the game's */
    fresh(IB_CTX_PAUSE);
    poll_(L);
    CHECK(poll_(L | X) == 0 && seq(f.pause) == 1 && button(f.pause) == IB_X && f.assign == 0 && f.use == 0);
    CHECK(poll_(L | X) == 0 && poll_(L) == 0 && poll_(0) == 0 && poll_(A) == A && seq(f.pause) == 1);
    p.usable = 0;
    poll_(0), poll_(L);
    CHECK(poll_(L | B) == 0 && poll_(B) == 0 && seq(f.pause) == 1);
    fresh(IB_CTX_MENU);
    poll_(L);
    CHECK(poll_(L | Y) == 0 && seq(f.assign) == 1 && f.pause == 0);
    /* turned off in it: everything the game's, the pause menu's sequence kept */
    fresh(IB_CTX_PAUSE);
    poll_(L), poll_(L | A);
    p.enabled = 0;
    CHECK(poll_(L | R) == (L | R) && seq(f.pause) == 1 && !f.hidden);
    /* ZR there: the game's as pressed (the next page), uncounted, in any mode */
    fresh(IB_CTX_PAUSE);
    set_mode(IB_ZR_HOLD, 0);
    CHECK(poll_(ZR) == ZR && poll_(0) == 0 && f.zr_presses == 0);

    /* the edges are the filter's own: a read repeated, as the game reads twice the frame a pause starts */
    fresh(IB_CTX_PLAY);
    poll_(L), poll_(L | A), poll_(L | A), poll_(L | A);
    CHECK(seq(f.use) == 1);
    /* the sequence goes round past 0 (0 is "none yet") */
    fresh(IB_CTX_PLAY);
    f.use = 0x0fffffffu << 4 | IB_B;
    poll_(L), poll_(L | A);
    CHECK(seq(f.use) == 1 && button(f.use) == IB_A);

    /* ZR, normal: the real one */
    fresh(IB_CTX_PLAY);
    CHECK(poll_(ZR) == ZR && poll_(ZR) == ZR && poll_(0) == 0 && f.zr_presses == 1);
    /* hold: hidden, nothing presented; the press counted */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_HOLD, 0);
    CHECK(poll_(ZR) == 0 && poll_(ZR) == 0 && poll_(0) == 0 && f.zr_presses == 1);
    /* face A: presented while A is taken; the hotkey let go meanwhile changes nothing; then the report */
    fresh(IB_CTX_PLAY);
    poll_(L), poll_(L | A);
    set_mode(IB_ZR_FACE, IB_A);
    CHECK(poll_(L | A) == ZR && f.shown == 1 && !f.released);
    for (int i = 0; i < 5; i++) CHECK(poll_(A) == ZR);
    CHECK(poll_(0) == 0 && f.shown == 6 && f.released && f.mode == p.mode);
    CHECK(poll_(0) == 0 && f.released);
    /* face B after a short tap (let go before the item was ready): ZR for three reads, a press and a release */
    fresh(IB_CTX_PLAY);
    poll_(L), poll_(L | B), poll_(L);
    set_mode(IB_ZR_FACE, IB_B);
    CHECK(poll_(L) == ZR && poll_(L) == ZR && poll_(L) == ZR && !f.released);
    CHECK(poll_(L) == 0 && f.shown == 3 && f.released);
    /* face A: A pressed without the hotkey is the game's A, no ZR; a real ZR press is hidden and counted */
    CHECK(poll_(0) == 0);
    set_mode(IB_ZR_FACE, IB_A);
    poll_(0), poll_(0), poll_(0);
    CHECK(poll_(A) == A && poll_(0) == 0);
    CHECK(poll_(ZR) == 0 && f.zr_presses == 1 && poll_(ZR) == 0 && poll_(0) == 0);
    /* the same mode set again (the button pressed again): a new report, ZR owed again */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_FACE, IB_X);
    poll_(0), poll_(0), poll_(0), poll_(0);
    CHECK(f.released);
    set_mode(IB_ZR_FACE, IB_X);
    CHECK(poll_(0) == ZR && !f.released && f.shown == 1);

    /* a real ZR press in face mode, the use ended at once: hidden through hold, given in real for three reads */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_FACE, IB_Y);
    poll_(0), poll_(0), poll_(0), poll_(0);
    CHECK(poll_(ZR) == 0 && f.zr_presses == 1);
    set_mode(IB_ZR_HOLD, 0);
    CHECK(poll_(0) == 0 && poll_(0) == 0);
    set_mode(IB_ZR_REAL, 0);
    CHECK(poll_(0) == ZR && poll_(0) == ZR && poll_(0) == ZR && !f.released);
    CHECK(poll_(0) == 0 && f.released && f.shown == 3);
    set_mode(IB_ZR_NORMAL, 0);
    CHECK(poll_(0) == 0 && poll_(ZR) == ZR);
    /* ... still held when real comes: presented while held, then let go */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_HOLD, 0);
    CHECK(poll_(ZR) == 0);
    set_mode(IB_ZR_REAL, 0);
    for (int i = 0; i < 6; i++) CHECK(poll_(ZR) == ZR);
    CHECK(poll_(0) == 0 && f.released);
    /* real with nothing owed: released at once */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_REAL, 0);
    CHECK(poll_(0) == 0 && f.released);
    /* the same press given back by normal (the item in use was ZR's own) */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_FACE, IB_A);
    poll_(0), poll_(0), poll_(0);
    CHECK(poll_(ZR) == 0);
    set_mode(IB_ZR_NORMAL, 0);
    CHECK(poll_(ZR) == ZR && poll_(0) == ZR && poll_(0) == ZR && poll_(0) == 0);
    /* an owed press not given back in time is dropped */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_HOLD, 0);
    poll_(ZR), poll_(0);
    for (int i = 0; i < IB_ZR_OWED_POLLS; i++) poll_(0);
    set_mode(IB_ZR_REAL, 0);
    CHECK(poll_(0) == 0);

    /* normal with another item answered for ZR: a real press hidden from its first read, counted, given back after */
    fresh(IB_CTX_PLAY);
    p.guard = 1;
    CHECK(poll_(ZR) == 0 && f.zr_presses == 1);
    p.guard = 0;
    CHECK(poll_(ZR) == ZR);
    /* a ZR held from before it was hidden is never given back (it would be a new press of the slot's item) */
    fresh(IB_CTX_PLAY);
    CHECK(poll_(ZR) == ZR);
    set_mode(IB_ZR_HOLD, 0);
    CHECK(poll_(ZR) == 0);
    set_mode(IB_ZR_NORMAL, 0);
    CHECK(poll_(ZR) == 0 && poll_(ZR) == 0 && poll_(0) == 0 && poll_(ZR) == ZR && f.zr_presses == 2);
    fresh(IB_CTX_PLAY);
    CHECK(poll_(ZR) == ZR);
    p.guard = 1;
    CHECK(poll_(ZR) == 0);
    p.guard = 0;
    CHECK(poll_(ZR) == 0);
    /* out of play (an event, the pause menu: Link may not run to end a use) ZR is the game's as pressed in every mode,
       its presses are not counted, and nothing owed comes back with play (no second drink after the event) */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_FACE, IB_A);
    CHECK(poll_(0) == ZR);
    p.context = IB_CTX_NONE;
    CHECK(poll_(0) == 0 && f.released);
    CHECK(poll_(ZR) == ZR && poll_(0) == 0 && f.zr_presses == 0);
    set_mode(IB_ZR_HOLD, 0);
    CHECK(poll_(ZR) == ZR && poll_(0) == 0);
    p.context = IB_CTX_MENU;
    CHECK(poll_(ZR) == ZR && poll_(0) == 0 && f.zr_presses == 0);
    p.context = IB_CTX_PLAY;
    CHECK(poll_(0) == 0 && poll_(ZR) == 0 && f.zr_presses == 1);   /* (play again: hold again) */
    fresh(IB_CTX_NONE);
    set_mode(IB_ZR_FACE, IB_B);   /* (set out of play) */
    CHECK(poll_(0) == 0);
    p.context = IB_CTX_PLAY;
    CHECK(poll_(0) == 0);
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_HOLD, 0);
    CHECK(poll_(ZR) == 0);   /* (hidden, owed) */
    p.context = IB_CTX_NONE;
    CHECK(poll_(0) == 0);
    p.context = IB_CTX_PLAY;
    set_mode(IB_ZR_REAL, 0);
    CHECK(poll_(0) == 0 && f.released);
    /* a ZR held into play while ZR is hidden there is not the game's until let go */
    fresh(IB_CTX_NONE);
    set_mode(IB_ZR_FACE, IB_A);
    CHECK(poll_(ZR) == ZR);
    p.context = IB_CTX_PLAY;
    set_mode(IB_ZR_NORMAL, 0);
    p.guard = 1;
    CHECK(poll_(ZR) == 0);
    p.guard = 0;
    CHECK(poll_(ZR) == 0 && poll_(0) == 0 && poll_(ZR) == ZR);
    /* face X's item out (drawn with the hotkey): the real ZR is the player's for it, presented and uncounted (the bow
       shoots, the use goes on), each press; with the face button held too, either let go first */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_FACE, IB_X);
    poll_(0), poll_(0), poll_(0), poll_(0);   /* (the first three reads' ZR over) */
    p.out = 1;
    CHECK(poll_(ZR) == ZR && f.zr_presses == 0 && !f.released);
    for (int i = 0; i < 5; i++) CHECK(poll_(ZR) == ZR);
    CHECK(poll_(0) == 0 && f.released && f.zr_presses == 0);
    CHECK(poll_(ZR) == ZR && poll_(0) == 0 && f.zr_presses == 0);
    poll_(L);
    CHECK(poll_(L | X) == ZR && poll_(X | ZR) == ZR && poll_(ZR) == ZR && poll_(0) == 0);
    CHECK(poll_(ZR) == ZR && poll_(X | ZR) == (X | ZR) && poll_(X) == X && poll_(0) == 0);   /* (X alone: the game's X) */
    poll_(L);
    CHECK(poll_(L | X) == ZR && poll_(X | ZR) == ZR && poll_(X) == ZR && poll_(0) == 0 && f.zr_presses == 0);
    /* the item put away with the real ZR down: hidden until let go (it would act on the item again), then as before */
    CHECK(poll_(ZR) == ZR);
    p.out = 0;
    CHECK(poll_(ZR) == 0 && poll_(ZR) == 0 && f.zr_presses == 0 && f.released);
    CHECK(poll_(0) == 0 && poll_(ZR) == 0 && f.zr_presses == 1);   /* (pressed anew, nothing out: hidden and counted) */
    /* out means nothing in the other modes */
    fresh(IB_CTX_PLAY);
    p.out = 1;
    set_mode(IB_ZR_HOLD, 0);
    CHECK(poll_(ZR) == 0 && poll_(0) == 0 && f.zr_presses == 1);
    set_mode(IB_ZR_NORMAL, 0);
    p.guard = 1;
    CHECK(poll_(ZR) == 0 && f.zr_presses == 2);
    /* a ZR hidden at its press (it ended the use) or held from before ZR was hidden is not given to the item out */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_FACE, IB_A);
    poll_(0), poll_(0), poll_(0), poll_(0);
    CHECK(poll_(ZR) == 0 && f.zr_presses == 1);
    p.out = 1;
    CHECK(poll_(ZR) == 0 && poll_(0) == 0 && poll_(ZR) == ZR && f.zr_presses == 1);
    fresh(IB_CTX_PLAY);
    CHECK(poll_(ZR) == ZR && f.zr_presses == 1);
    set_mode(IB_ZR_FACE, IB_A);
    poll_(ZR), poll_(ZR), poll_(ZR);   /* (the mode's own first three reads) */
    p.out = 1;
    CHECK(poll_(ZR) == 0 && poll_(ZR) == 0 && poll_(0) == 0 && poll_(ZR) == ZR && f.zr_presses == 1);
    /* out of play the real ZR is the game's as pressed, out or not */
    p.context = IB_CTX_NONE;
    CHECK(poll_(0) == 0 && poll_(ZR) == ZR && f.zr_presses == 1);

    /* the other buttons pass in every mode */
    fresh(IB_CTX_PLAY);
    set_mode(IB_ZR_FACE, IB_A);
    CHECK((poll_(R | (1 << 8) | (1 << 12)) & ~(uint64_t)ZR) == (R | (1 << 8) | (1 << 12)));

    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""

OUT_MAIN = r"""
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
enum { STICK = 0, NUT = 1, BOMB = 2, BOOMERANG = 3, SLING = 4, HOOK = 5, LONG = 6, HAMMER = 7, CHU = 9, BOTTLE = 14,
       BOW = 30, FIRE = 46 };
enum { NONE = -1, FLIGHT = 5, THROW = 0x79, DRINK = 0xee, AIM = 6, LIFT = 0x2b, SHEATHED = 0x3a, SHOOT = 0x3b, HOLD = 0xed };
static int bomb, gone;
/* hook 3's order: the latch first, then the item gone only while it is not out (the pouch's count read as owned) */
static int frame(int item, int sub, int using_item, unsigned lift, int owned) {
    bomb = ib_bomb(bomb, item, sub, using_item, lift);
    const int out = bomb || ib_in_hand(item, NONE, sub, using_item);
    if (!out && !owned) gone = 1;
    return out;
}

int main(void) {
    /* the bow, the arrows, the slingshot: the Bow sub action (the item stays in use after it, put away or not) */
    CHECK(ib_in_hand(BOW, NONE, SHOOT, BOW) && ib_in_hand(FIRE, NONE, SHOOT, FIRE) && ib_in_hand(SLING, NONE, SHOOT, SLING));
    CHECK(!ib_in_hand(BOW, NONE, SHEATHED, BOW) && !ib_in_hand(BOW, NONE, NONE, BOW) && !ib_in_hand(SLING, NONE, NONE, NONE));
    /* the hookshot: aimed, or in flight; in use alone (only a put-away clears it) is not out */
    CHECK(ib_in_hand(HOOK, NONE, AIM, HOOK) && ib_in_hand(HOOK, FLIGHT, NONE, HOOK) && ib_in_hand(LONG, NONE, AIM, LONG));
    CHECK(!ib_in_hand(HOOK, NONE, NONE, HOOK) && !ib_in_hand(HOOK, NONE, SHEATHED, HOOK) && !ib_in_hand(LONG, NONE, NONE, LONG));
    /* the boomerang: aimed (HoldItem) or in use (thrown, caught: its own actions clear it) */
    CHECK(ib_in_hand(BOOMERANG, NONE, HOLD, NONE) && ib_in_hand(BOOMERANG, THROW, NONE, BOOMERANG));
    CHECK(!ib_in_hand(BOOMERANG, NONE, NONE, NONE));
    /* the stick and the hammer: in use */
    CHECK(ib_in_hand(STICK, NONE, NONE, STICK) && ib_in_hand(HAMMER, NONE, NONE, HAMMER) && !ib_in_hand(HAMMER, NONE, NONE, NONE));
    /* another item's action or item is not this one's */
    CHECK(!ib_in_hand(HOOK, NONE, SHOOT, BOW) && !ib_in_hand(BOW, NONE, AIM, HOOK) && !ib_in_hand(STICK, NONE, NONE, HAMMER));
    CHECK(!ib_in_hand(BOW, FLIGHT, NONE, NONE));
    /* bombs, bottles, nuts: never by these reads */
    CHECK(!ib_in_hand(BOMB, NONE, LIFT, BOMB) && !ib_in_hand(BOTTLE, DRINK, NONE, BOTTLE) && !ib_in_hand(NUT, THROW, NONE, NUT));

    /* the last bomb lifted: out from the frame the lift takes it, so its leaving the pouch ends nothing; carried; thrown */
    bomb = gone = 0;
    CHECK(!frame(BOMB, NONE, NONE, 0, 1));
    CHECK(frame(BOMB, LIFT, BOMB, 0, 1) && bomb == 1);   /* (the lift's first state: the bomb in use) */
    CHECK(frame(BOMB, LIFT, BOMB, 0, 0) && bomb == 1);   /* (taken in hand: out of the pouch) */
    CHECK(frame(BOMB, LIFT, NONE, 2, 0) && bomb == 2 && frame(BOMB, LIFT, NONE, 3, 0) && bomb == 2);
    CHECK(!gone);
    CHECK(!frame(BOMB, LIFT, NONE, 0, 0) && bomb == 0 && gone);   /* (thrown: none left, the use ends) */
    /* set down: the lift's sub action over */
    bomb = gone = 0;
    frame(CHU, LIFT, CHU, 0, 1), frame(CHU, LIFT, NONE, 3, 1);
    CHECK(bomb == 2 && !frame(CHU, NONE, NONE, 0, 1) && bomb == 0 && !gone);
    /* thrown with more left, the next one lifted at once */
    bomb = 0;
    frame(BOMB, LIFT, BOMB, 0, 1), frame(BOMB, LIFT, NONE, 2, 1), frame(BOMB, LIFT, NONE, 0, 1);
    CHECK(bomb == 0 && frame(BOMB, LIFT, BOMB, 0, 1) && bomb == 1);
    /* a lift that did not take the bomb (its sub action over before carrying): let go */
    bomb = 0;
    frame(BOMB, LIFT, BOMB, 0, 1);
    CHECK(!frame(BOMB, NONE, NONE, 0, 1) && bomb == 0);
    /* another item's use never latches, whatever is lifted */
    bomb = 0;
    CHECK(!frame(BOW, LIFT, BOW, 0, 1) && !frame(BOW, LIFT, NONE, 2, 1) && bomb == 0);
    /* a bow out with its last arrow shot stays the use's; put away, the use ends */
    bomb = gone = 0;
    CHECK(frame(BOW, SHOOT, BOW, 0, 0) && !gone && !frame(BOW, NONE, BOW, 0, 0) && gone);

    /* the control guide's entries (want, open: 1 opening 2 open 3 closing 0 closed, mine, wanted, zr) */
    CHECK(ib_entry(1, 2, 0, 0, 1) == 1 && ib_entry(1, 1, 0, 0, 1) == 1);   /* ZR's glyph: the combo */
    CHECK(ib_entry(1, 2, 0, 0, 0) == 0);                                   /* another key's: left */
    CHECK(ib_entry(1, 2, 1, 1, 0) == 0);                                   /* the combo wanted there already */
    CHECK(ib_entry(1, 2, 1, 0, 0) == 1);                                   /* another of ours (hotkey, face changed) */
    CHECK(ib_entry(1, 3, 1, 1, 0) == -1 && ib_entry(1, 0, 1, 0, 0) == -1); /* closing or closed: ZR's glyph back */
    CHECK(ib_entry(1, 3, 0, 0, 1) == 0 && ib_entry(1, 0, 0, 0, 1) == 0);   /* the game's ZR closing: left */
    CHECK(ib_entry(0, 2, 1, 0, 0) == -1 && ib_entry(0, 2, 0, 0, 1) == 0);  /* nothing out: ours back, the game's left */

    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""


def compile_and_run(case, text, prefix):
    compiler = shutil.which("gcc") or shutil.which("clang")
    if not compiler:
        case.skipTest("no C compiler")
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        tmp = Path(tmp)
        (tmp / "t.c").write_text(text, encoding="utf-8")
        binary = tmp / ("t.exe" if sys.platform == "win32" else "t")
        build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                                str(tmp / "t.c"), "-o", str(binary)], text=True, capture_output=True)
        case.assertEqual(build.returncode, 0, build.stderr)
        run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
        case.assertEqual(run.returncode, 0, run.stdout + run.stderr)


class ItemButtonsFilterTests(unittest.TestCase):
    def test_filter(self):
        source = (ROOT / "host" / "oot_item_buttons.c").read_text(encoding="utf-8")
        step = between(source, "enum { IB_CTX_NONE", "static uint64_t ib_step(")
        self.assertNotIn("ib_peek", step, "the filter's step reads guest memory")
        self.assertNotIn("recomp_", step, "the filter's step reads guest memory")
        wrapper = block(source, "uint64_t hos_oot_ib_filter(")
        self.assertIn("ib_step(&f, &p)", wrapper, "the filter's wrapper does not run the step")
        self.assertRegex(wrapper, r"if \(in_pause\)\s*p\.context = IB_CTX_PAUSE, p\.usable = __atomic_load_n\(&ib_pause_usable,",
                         "the pause menu's context does not come first, with its Items page's usable")
        self.assertIn("__atomic_store_n(&ib_pause_req, f.pause,", wrapper, "the pause menu's requests are not published")
        compile_and_run(self, PRELUDE + header_constants() + step + MAIN, "hookshot-item-buttons-filter-")

    def test_out(self):
        source = (ROOT / "host" / "oot_item_buttons.c").read_text(encoding="utf-8")
        parts = [block(source, "static int " + name + "(") for name in ("ib_bow", "ib_in_hand", "ib_bomb", "ib_entry")]
        for part in parts:
            for guest in ("ib_peek", "recomp_", "GP(", "ib_guest"):
                self.assertNotIn(guest, part, "a step checked alone reads guest memory")
        locked = block(source, "static void ib_player_locked(")
        latch = "ib_use.bomb = ib_bomb(ib_use.bomb, ib_use.item, sub_verb, using_item, lift);"
        gone = "if (!held && !ib_item_owned(c, ib_use.item, ib_scratch(c))) {"
        self.assertIn(latch, locked, "hook 3 does not keep the bomb's latch")
        self.assertIn(gone, locked, "hook 3 ends a use for its item gone while it is out")
        self.assertLess(locked.index(latch), locked.index(gone), "hook 3 asks the pouch before the bomb's latch")
        self.assertIn("(ib_use.bomb || ib_in_hand(ib_use.item, verb, sub_verb, using_item))", locked.split(gone)[0],
                      "hook 3's item out is not the latch or the hands")
        self.assertRegex(locked, r"const int out = ib_use\.phase == IB_ACTIVE && !event && \(ib_use\.bomb \|\| "
                                 r"ib_in_hand\(ib_use\.item, verb, sub_verb, using_item\)\);",
                         "the item out told to the filter and the guide is not the latch or the hands")
        tick = block(source, "static void ib_ctrl_guide_locked(")
        self.assertIn("ib_entry(want != 0, open, mine, text == want + 0x18, zr)", tick,
                      "the control guide does not choose by ib_entry")
        compile_and_run(self, PRELUDE + "\n".join(parts) + OUT_MAIN, "hookshot-item-buttons-out-")


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
