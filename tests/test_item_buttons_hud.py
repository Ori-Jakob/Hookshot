"""The HUD's item buttons: where the four boxes go (host/oot_item_buttons_hud.c, the arrangement).

The file's arrangement part (no guest memory) is cut out and compiled with the controls' names from gpu/vk/vk_api.h and
the default controls from host/nn_hid.c, then checked:

- the group goes from the small diamond left of the ZR box (root (1285, 822), scale 0.2465: 15% under the first 0.29, its
  right edge where it was; alpha 0.5) to the large one in its place ((1560, 705), 0.55, alpha 1) in 8 frames at 60 while the
  hotkey is held, and back, eased (smoothstep: still at both ends); the translate is the group's parent's, N_All_00 at (0, 2);
- the small diamond stays clear of the ZR box and the large one on the screen;
- the hint's copy over the top box keeps the game's hint's size (scale 1 in root units) and its place over the box drawn
  (the top of its dark frame, measured on the screen, 142 above a box's centre at scale 1; the game's hint is 166 above
  its ZR box's centre at 0.85, so 45.3 over that top) at any scale of the group, and stays on the screen with its glyph;
- each face button sits where the pad has it (the input bound to it: right, below, left, above), the Switch's diamond with
  the default controls; four inputs that are not the four face positions, one each, give the Switch's diamond; the menu's
  guide lists them east, south, west, north by the same rule;
- a glyph takes the Xbox letter's colour (A green, B red, X blue, Y yellow, linear) for the pad input shown, on the Xbox
  prompts only; the cream on every other face, for an input that is no face button, and before the face is known.

The game's side (guest calls, read as text) is held to what the game does:
- a glyph's text goes on its T_Assign_00 pane itself (Pane::setTextBoxString), on the HUD and on the quick-switch menu's
  entries: the layout's setter by path (f_80a87d30) writes only text boxes whose text id is "@name", T_Assign_00's is "*";
  the menu's glyph follows makeGuideKeyIconMsg's answer, and is shown again each frame once the entry's Type hold (made as
  the menu opens) has hidden it;
- a count by ammunition (the bow's and the slingshot's rows) copies ShootableActor, a path, to the actor's name
  (f_802d5480) before asking the pouch's name of it, as refreshSelectItem does;
- the four boxes are out of the game's focus: each part's button has its input off through UniteButton's own setter
  (setButtonInputEnable does not reach a part's button) at bind and whenever it comes on, and its B_Hit_00 hidden;
- the hints' glyphs are makeGuideKeyIconMsg's L or R on their panes: the hotkey over the diamond, the other shoulder button
  over the ZR box, the game's own R put back with the feature off; the group's alpha is the arrangement's times the game's;
- the menus' guides (the quick-switch menu's; the pause menu's on its Items page, in an alignment pane of its own) put
  makeGuideKeyIconMsg's glyphs (the hotkey, then the faces in the pad's order) on their parts' panes, and are hidden with the
  feature off; a layout without the parts leaves a guide alone for that screen; the glyphs' cream is the hotkey's glyph's
  (never coloured); the pause menu's row lines the group up again the frame after it is shown or a glyph in it changes, and
  the room the group takes there (its bounds' width and the row's margin) is told to the mouse (the "Back" prompt's box);
- the pause menu: its screen stamps the filter's context and takes an assignment on the Items page alone, by the quick-switch
  menu's rules, with its slot's flash; the tab bar shows ZL and ZR on its tabs with the feature on, L and R otherwise; the
  Items page's face items are State 2 with a blue ramp, the item on ZR left gold, undone off; the carousel's cells are blue
  at frame 0 alone, frame 0's colours read and put back;
- the Items page's glyphs: each slot's part (nx2/item_buttons_layout.py's name) looked up with the slot, its cream read
  before any is coloured; face button k's glyph (makeGuideKeyIconMsg 1 + k, in the carousel's colour) on a slot whose item
  is on k, the item on ZR too, at its box's top right corner by the shape the slot's ItemPattern picks (compiled alone:
  every place on the slot's picture, one place a shape, the plain square's for a frame the page does not use), hidden on
  every other slot and with the feature off;
- the control guide (UICtrlGuideScreen, through the same hook): while an item used with the hotkey is out, an open entry
  whose T_Icon_00 shows ZR's glyph gets the combo (makeGuideKeyIconMsg's glyphs, in guest memory of the host's own) through
  Pane::setTextBoxString, and the game's ZR glyph back otherwise. The combo is compiled with the glyphs stood in: "ZR, L + A"
  with the prompts' comma and plus, ZR, a gap of 12 spaces, the hotkey and the face button without them;
- a screen destroyed (hook 10) is forgotten by the guides, the tab bar, the carousel's cells, the Items page's slots and
  the pause menu's stamp.

python -I -B tests/test_item_buttons_hud.py [--cc gcc]
"""
import re
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


FIXTURE = r'''
#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s\n", __LINE__, #x); fails++; } } while (0)
static int fails;
static int near(float a, float b) { return fabsf(a - b) < 1e-3f; }
static int at(const float x[4], const float y[4], int k, float wx, float wy) { return near(x[k], wx) && near(y[k], wy); }
static float srgb(float l) { return l <= 0.0031308f ? l * 12.92f : 1.055f * powf(l, 1.0f / 2.4f) - 0.055f; }
int main(void) {
    const int64_t frame = 16666667;   /* (60 a second) */
    /* the easing: still at both ends, half way at the middle, rising throughout */
    CHECK(hud_ease(0.0f) == 0.0f && hud_ease(1.0f) == 1.0f && near(hud_ease(0.5f), 0.5f));
    CHECK(hud_ease(-1.0f) == 0.0f && hud_ease(2.0f) == 1.0f && hud_ease(NAN) == 0.0f);
    CHECK(hud_ease(0.05f) < 0.01f && hud_ease(0.95f) > 0.99f);
    for (int i = 1; i <= 100; i++) CHECK(hud_ease(i / 100.0f) > hud_ease((i - 1) / 100.0f));
    /* t: 0 to 1 in 8 frames while large, back in 8 */
    float t = 0.0f;
    for (int i = 0; i < 4; i++) t = hud_advance(t, 1, frame);
    CHECK(near(t, 0.5f));
    for (int i = 0; i < 4; i++) t = hud_advance(t, 1, frame);
    CHECK(t == 1.0f);
    CHECK(hud_advance(t, 1, frame) == 1.0f);
    t = hud_advance(t, 0, 2 * frame);
    CHECK(near(t, 0.75f));
    CHECK(hud_advance(t, 0, 0) == t && hud_advance(t, 1, -frame) == t);   /* (no time: no step) */
    CHECK(hud_advance(t, 0, 10000000000LL) == 0.0f && hud_advance(0.0f, 1, 10000000000LL) == 1.0f);   /* (the HUD paused a while) */
    CHECK(hud_advance(NAN, 0, frame) == 0.0f && hud_advance(5.0f, 1, frame) == 1.0f);
    /* the group: small and half faded at 0, large and whole at 1, between at 0.5, in N_All_00's units (it sits at (0, 2)) */
    float x, y, s, a;
    hud_place(0.0f, &x, &y, &s, &a);
    CHECK(near(x, 1285.0f) && near(y + 2.0f, 822.0f) && near(s, 0.2465f) && near(a, 0.5f));
    CHECK(near(s, 0.29f * 0.85f));   /* (15% smaller than the first arrangement's) */
    {   /* (small: its right edge, a box's half past a box's step, left of the ZR box's, 1464.5, as at 0.29; root units) */
        CHECK(x + s * (380.0f + 190.0f) < 1464.5f && fabsf(x + s * 570.0f - (1260.0f + 0.29f * 570.0f)) < 1.0f);
    }
    hud_place(1.0f, &x, &y, &s, &a);
    CHECK(near(x, 1560.0f) && near(y + 2.0f, 705.0f) && near(s, 0.55f) && a == 1.0f);
    CHECK(y + 2.0f + s * (380.0f + 190.0f) <= 1080.0f && x + s * (380.0f + 190.0f) <= 1920.0f);   /* (large: on the screen) */
    hud_place(0.5f, &x, &y, &s, &a);
    CHECK(near(x, 1422.5f) && near(y + 2.0f, 763.5f) && near(s, 0.39825f) && near(a, 0.75f));
    /* the hint over the top box: the game's hint's size (scale 1 in root units) and its place over the box drawn at any
       scale: 166 - 0.85 * 142 = 45.3 over the drawn top (142 over a box's centre at scale 1), in root units */
    for (int i = 0; i <= 4; i++) {
        float hy, hs;
        hud_place(i / 4.0f, &x, &y, &s, &a);
        hud_hint(s, &hy, &hs);
        CHECK(near(hs * s, 1.0f));
        CHECK(fabsf(s * hy - (s * (380.0f + 142.0f) + 45.3f)) < 0.01f);   /* (root: the top box's drawn top + 45.3) */
        CHECK(y + 2.0f + s * hy + 24.0f <= 1080.0f - 10.0f);   /* (on the screen, its glyph's top half too: about 24) */
    }
    {   /* (the ZR box's own: 166 over a box of scale 0.85's centre, as the game's layout has it) */
        float hy, hs;
        hud_hint(0.85f, &hy, &hs);
        CHECK(fabsf(0.85f * (hy - 380.0f) - 166.0f) < 0.01f);
    }
    /* the guide's face buttons, east, south, west, north: by the controls, the Switch's when they are not the four faces */
    int order[4];
    int defaults[4] = {pad_default[0], pad_default[1], pad_default[2], pad_default[3]};
    CHECK(hud_faces(defaults, order) == 1 && order[0] == 0 && order[1] == 1 && order[2] == 3 && order[3] == 2);   /* A B Y X */
    int lettered[4] = {HOS_PAD_SOUTH, HOS_PAD_EAST, HOS_PAD_WEST, HOS_PAD_NORTH};   /* (A on the bottom: an Xbox pad's) */
    CHECK(hud_faces(lettered, order) == 1 && order[0] == 1 && order[1] == 0 && order[2] == 2 && order[3] == 3);   /* B A X Y */
    int double_east[4] = {HOS_PAD_EAST, HOS_PAD_EAST, HOS_PAD_NORTH, HOS_PAD_WEST};
    CHECK(hud_faces(double_east, order) == 0 && order[0] == 0 && order[1] == 1 && order[2] == 3 && order[3] == 2);
    /* the diamond: the default controls (host/nn_hid.c) are the Switch's */
    float dx[4], dy[4];
    int pad[4] = {pad_default[0], pad_default[1], pad_default[2], pad_default[3]};
    CHECK(hud_diamond(pad, dx, dy) == 1);
    CHECK(at(dx, dy, 0, 380, 0) && at(dx, dy, 1, 0, -380) && at(dx, dy, 2, 0, 380) && at(dx, dy, 3, -380, 0));
    /* A on the bottom face button, B on the right, X on the left, Y on the top (an Xbox pad's lettering) */
    int xbox[4] = {HOS_PAD_SOUTH, HOS_PAD_EAST, HOS_PAD_WEST, HOS_PAD_NORTH};
    CHECK(hud_diamond(xbox, dx, dy) == 1);
    CHECK(at(dx, dy, 0, 0, -380) && at(dx, dy, 1, 380, 0) && at(dx, dy, 2, -380, 0) && at(dx, dy, 3, 0, 380));
    /* A and B swapped only */
    int swapped[4] = {HOS_PAD_SOUTH, HOS_PAD_EAST, HOS_PAD_NORTH, HOS_PAD_WEST};
    CHECK(hud_diamond(swapped, dx, dy) == 1);
    CHECK(at(dx, dy, 0, 0, -380) && at(dx, dy, 1, 380, 0) && at(dx, dy, 2, 0, 380) && at(dx, dy, 3, -380, 0));
    /* not the four face positions, one each: the Switch's diamond */
    int twice[4] = {HOS_PAD_EAST, HOS_PAD_EAST, HOS_PAD_NORTH, HOS_PAD_WEST};
    int unbound[4] = {HOS_PAD_EAST, -1, HOS_PAD_NORTH, HOS_PAD_WEST};
    int shoulder[4] = {HOS_PAD_EAST, HOS_PAD_SOUTH, HOS_PAD_LSHOULDER, HOS_PAD_WEST};
    int *odd[3] = {twice, unbound, shoulder};
    for (int i = 0; i < 3; i++) {
        CHECK(hud_diamond(odd[i], dx, dy) == 0);
        CHECK(at(dx, dy, 0, 380, 0) && at(dx, dy, 1, 0, -380) && at(dx, dy, 2, 0, 380) && at(dx, dy, 3, -380, 0));
    }
    /* the glyphs' colours: the Xbox letters' on the Xbox face, by the pad input shown (linear, from the sRGB shades) */
    float rgba[4];
    const float green[3] = {0.42f, 0.76f, 0.29f}, red[3] = {0.91f, 0.28f, 0.25f}, blue[3] = {0.24f, 0.56f, 0.87f},
                yellow[3] = {0.96f, 0.77f, 0.09f};
    const float *want[4] = {green, red, blue, yellow};   /* (HOS_PAD_SOUTH A, EAST B, WEST X, NORTH Y) */
    for (int p = HOS_PAD_SOUTH; p <= HOS_PAD_NORTH; p++) {
        CHECK(hud_tint(HOS_PROMPT_XBOX, p, rgba) == 1 && rgba[3] == 1.0f);
        for (int i = 0; i < 3; i++) CHECK(fabsf(srgb(rgba[i]) - want[p][i]) < 1e-3f && rgba[i] <= want[p][i]);
    }
    CHECK(hud_tint(HOS_PROMPT_XBOX, HOS_PAD_SOUTH, rgba) && rgba[1] > rgba[0] && rgba[1] > rgba[2]);   /* (A green) */
    CHECK(hud_tint(HOS_PROMPT_XBOX, HOS_PAD_EAST, rgba) && rgba[0] > rgba[1] && rgba[0] > rgba[2]);    /* (B red) */
    CHECK(hud_tint(HOS_PROMPT_XBOX, HOS_PAD_WEST, rgba) && rgba[2] > rgba[0] && rgba[2] > rgba[1]);    /* (X blue) */
    CHECK(hud_tint(HOS_PROMPT_XBOX, HOS_PAD_NORTH, rgba) && rgba[0] > rgba[2] && rgba[1] > rgba[2]);   /* (Y yellow) */
    /* the game's cream on every other face, and for an input that is not a face button or none */
    const int others[4] = {HOS_PROMPT_SWITCH, HOS_PROMPT_PS4, HOS_PROMPT_PS5, HOS_PROMPT_STEAMDECK};
    for (int f = 0; f < 4; f++)
        for (int p = HOS_PAD_SOUTH; p <= HOS_PAD_NORTH; p++) CHECK(hud_tint(others[f], p, rgba) == 0);
    CHECK(hud_tint(-1, HOS_PAD_SOUTH, rgba) == 0 && hud_tint(HOS_PROMPT_N, HOS_PAD_SOUTH, rgba) == 0);   /* (not decided yet) */
    CHECK(hud_tint(HOS_PROMPT_XBOX, -1, rgba) == 0 && hud_tint(HOS_PROMPT_XBOX, HOS_PAD_LSHOULDER, rgba) == 0);
    CHECK(hud_tint(HOS_PROMPT_XBOX, HOS_PAD_BACK, rgba) == 0 && hud_tint(HOS_PROMPT_XBOX, HOS_PAD_RTRIGGER, rgba) == 0);
    if (!fails) printf("PASS: the item buttons' group eases between its two places, sizes and alphas, its hint over it at the "
                       "game's hint's size; the diamond and the guide's glyphs follow the pad; the glyphs take the Xbox colours "
                       "on its face only\n");
    return fails != 0;
}
'''


def function(text, name):
    """a C function's body by its name (the line that defines it to its closing brace)"""
    m = re.search(r"^[^\n;]*\b%s\([^;{]*\)\s*\{" % re.escape(name), text, re.M)
    if not m:
        raise SystemExit("FAIL: no function %s" % name)
    return block(text, m.group(0))


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def game_side(hud, core):
    """the guest calls of the fixes, read as text"""
    define = dict(re.findall(r"#define (F_\w+) (0x[0-9a-f]+)ULL", hud))
    check(define.get("F_PANE_TEXT") == "0x80459520", "the HUD's glyph text is not set with Pane::setTextBoxString")
    check(define.get("F_INPUT") == "0x837927c0", "the boxes' input is not switched off with UniteButton's own setter")
    check(define.get("F_ACTOR") == "0x802d5480" and define.get("F_AMMO") == "0x80a865a0", "the ammunition's calls changed")
    for text, name in ((hud, "oot_item_buttons_hud.c"), (core, "oot_item_buttons.c")):
        check("0x80a87d30" not in text and "0x80f42330" not in text,
              "%s calls the layout's text setter by path or setButtonInputEnable, which miss the parts" % name)
    glyphs = function(hud, "set_glyphs")
    check("put_key(c, h, h->glyph[k], 1 + k)" in glyphs, "set_glyphs does not put the message on the glyph's pane")
    count = function(hud, "box_count")
    shot, ammo = count.find("CALL(c, F_ACTOR, h->scratch + SC_SHOT, b->row + ROW_SHOOTABLE)"), count.find(
        "CALL(c, F_AMMO, h->scratch + SC_AMMO, h->scratch + SC_SHOT)")
    check(0 <= shot < ammo, "box_count does not cut ShootableActor to the actor's name before asking the pouch's")
    check(re.search(r"#define BUTTON_VTABLE 0x84c416e8ULL", hud) and "BUTTON_VTABLE" in function(hud, "part_button"),
          "part_button does not keep to UniteButtons")
    check("BUTTON_INPUT_ON" in function(hud, "input_off"), "input_off calls the setter whatever the button's flags")
    bind, frame = function(hud, "hos_oot_ib_hud_init"), function(hud, "hud_frame")
    check("input_off(c, h->button[k] = part_button(screen, layout[k]))" in bind, "the bind does not switch the inputs off")
    check(re.search(r"CALL\(c, F_VISIBLE, h->hit\[k\], 0\)", bind) and "h->strings[S_HIT]" in bind,
          "the bind does not hide each part's B_Hit_00")
    check("input_off(c, h->button[k])" in frame and "pane_shown(c, h->hit[k], 0)" in frame,
          "the HUD's frame does not keep the inputs off and B_Hit_00 hidden")
    glyph = function(core, "ib_glyph")
    check(re.search(r"if \(\(\w+ = ib_guest\(c, 0x80a8ae50ULL|if \(ib_guest\(c, 0x80a8ae50ULL", glyph) and "0x80459520ULL" in glyph,
          "the menu's glyph does not follow makeGuideKeyIconMsg's answer onto the pane itself")
    check("ib_glyph_white" in glyph and "ib_glyph_colour" in glyph, "the menu's glyph is not coloured or given its cream back")
    check("ib_glyphs_kept(c, row);" in function(core, "ib_shortcut_locked"), "the menu's glyphs are not kept shown")
    # the hints: makeGuideKeyIconMsg's L (5) or R (7) on the text panes themselves; the game's own R put back when off
    check(re.search(r"KEY_L = 5, KEY_R = 7", hud) and re.search(r"CALL\(c, F_KEY_TEXT, rec, \(uint64_t\)key\)", function(hud, "put_key"))
          and "CALL(c, F_PANE_TEXT, pane, rec)" in function(hud, "put_key"), "a hint's glyph is not the game's message on its pane")
    hints = function(hud, "set_hints")
    check("hot_r ? KEY_R : KEY_L" in hints and "on && hot_r ? KEY_L : h->hint_set ? KEY_R : 0" in hints,
          "the hints do not show the hotkey over the diamond and the other shoulder button over the ZR box")
    check("set_hints(c, h, 0);" in frame and "set_hints(c, h, 1);" in frame, "the HUD's frame does not keep the hints")
    check("alpha * fade" in frame and "hud_hint(scale, &hint_y, &hint_scale)" in frame,
          "the group's alpha or the hint's place is not the arrangement's")
    # the menus' guides: their parts found by name, the glyphs from makeGuideKeyIconMsg on the panes, shown only while on
    guide = function(core, "ib_guide")
    check("ib_put_key(c, g->icon[k], keys[k])" in guide and "ib_face_order(order)" in guide and
          "IB_KEY_R : IB_KEY_L" in guide, "the guide's glyphs are not the hotkey's and the faces' in the pad's order")
    check(re.search(r"0x80a8ae50ULL", function(core, "ib_put_key")) and "0x80459520ULL" in function(core, "ib_put_key"),
          "the guide's glyph does not go through makeGuideKeyIconMsg onto its pane")
    check(re.search(r"if \(!on\) \{\s*ib_show\(c, g->group, 0\);\s*for \(int k = 0; k < IB_GUIDES; k\+\+\) "
                    r"ib_show\(c, g->part\[k\], 0\);", guide), "the guide is not hidden with the feature off")
    check("g->missing = 1;" in guide and "!= screen || g->missing) return;" in guide,
          "a guide looks for its parts again every frame on a layout without them")
    check("ib_show(c, g->group, 1);" in guide and "found = (g->group = ib_guest(c, 0x8045e300ULL" in guide,
          "the pause menu's guide is not shown and hidden with its alignment pane")
    check("if (g->group && g->relay && --g->relay == 0) ib_show(c, g->group, 0), ib_show(c, g->group, 1);" in guide and
          "g->shown = 1, g->relay = 2;" in guide and "g->keys[k] = keys[k], g->relay = 2;" in guide and "% 30" not in guide,
          "the pause menu's row is not asked to line the group up again the frame after it is shown or a glyph changes "
          "(and only then)")
    check("g->coloured = ib_glyph_white(c, g->icon[0], NULL, g->cream);" in guide,
          "the guide's cream is not read from the hotkey's glyph (never coloured), so a looked-up-again guide can take the "
          "east glyph's Xbox colour for it")
    overlay_fn = function(core, "ib_overlay_locked")
    check("ib_peek(ib_pd.group + 0x9c, 4)" in overlay_fn and "room = (int)(w + 0.5f) + IB_FOOTER_MARGIN;" in overlay_fn and
          "__atomic_store_n(&ib_footer_room, room, __ATOMIC_RELEASE);" in overlay_fn and
          re.search(r"IB_FOOTER_MARGIN = 90\b", core) and "int ib_pause_footer_shift(void)" in core,
          "the pause menu's Assign guide's room in its row (its bounds' width and the row's margin) is not told to the mouse")
    check("ib_guide(c, &ib_gd, screen, on, now - last_ns > IB_LIVE_NS, IB_WORD_MENU, 0," in function(core, "ib_shortcut_locked"),
          "the quick-switch menu's guide is not its screen's, shown while on")
    overlay = function(core, "ib_overlay_locked")
    check("ib_guide(c, &ib_pd, ov, on && tabs == 1 && preset == IB_PRESET_ITEMS, 0, IB_WORD_PAUSE, 1," in overlay and
          re.search(r"IB_PRESET_ITEMS = 5\b", core) and re.search(r"ib_peek\(ov \+ 0x350, 4\)", overlay) and
          re.search(r"ib_peek\(ov \+ 0x354, 4\)", overlay),
          "the pause menu's guide is not shown on its Items page alone (the overlay's tabs 1, preset 5)")
    words = re.search(r"ib_words\[IB_WORDS\] = \{([^}]*)\}", core)
    check(words and [w.strip() for w in words.group(1).split(",")] == ['"      Assign"', '" +"', '"Assign"'],
          "the guides' words are not the quick-switch menu's spaced Assign, the plus, the pause menu's Assign")
    # the pause menu's tab glyphs: ZL and ZR (makeGuideKeyIconMsg 6 and 8) while its tabs are up with the feature on, L and R
    # (5 and 7) otherwise, on T_BtnL_00 and T_BtnR_00, set only when the pane's text differs (by the buttons its codes show:
    # tests/test_item_buttons_live_prompts.py)
    tabs = function(core, "ib_tab_glyphs")
    check("{IB_KEY_L, IB_KEY_R, IB_KEY_ZL, IB_KEY_ZR}" in tabs and "const int want = zl ? 2 + i : i" in tabs and
          re.search(r"IB_KEY_ZL = 6\b", core) and re.search(r"IB_KEY_ZR = 8\b", core) and
          "ib_put_key(c, pane, keys[want]);" in tabs and "ib_same_glyph((const uint8_t *)GP(text), len, ib_tabs.key[want], ib_tabs.len[want])" in tabs and
          '"T_BtnL_00", "T_BtnR_00"' in core and "ib_tab_glyphs(c, ov, on && tabs == 1);" in overlay,
          "the tab bar's glyphs are not ZL and ZR on the pause menu's tabs alone, the game's L and R otherwise")
    # the pause menu's screen and the overlay are handled after their updates; the filter's stamp is the pause menu's
    screen_hook = function(core, "hos_oot_ib_screen")
    check(re.search(r"#define IB_PLUS_VTABLE 0x84c0baa8ULL", core) and re.search(r"#define IB_OVERLAY_VTABLE 0x84c08aa0ULL", core)
          and "else if (vt == IB_PLUS_VTABLE) ib_pause(c, screen);" in screen_hook and
          "else if (vt == IB_OVERLAY_VTABLE) ib_overlay(c, screen);" in screen_hook,
          "the pause menu's screen or the screen over it is not handled after its update")
    pause = function(core, "ib_pause_locked")
    check("on && (st == 1 || st == 2) ? now : 0" in pause and "ib_load32(&ib_pause_req)" in pause and
          "ib_pause_assign(c, s, slot, (int)(r & 0xf));" in pause and "(uint32_t)ib_peek(ui + 0x530, 4) == IB_PAGE_ITEMS" in pause,
          "the pause menu does not stamp its context, or takes an assignment off the Items page")
    check("ib_chosen(c, screen, ib_peek(slot + 0x30, 8));" in function(core, "ib_pause_assign") and
          "ib_put(ib_age(c), k," in function(core, "ib_pause_assign") and "ib_put(ib_age(c), k," in function(core, "ib_assign"),
          "the menus do not assign by the same rules, or the pause menu's slot does not flash")
    # the light blue: the Items page's ramp on State 2, the carousel's colours at frame 0; the item on ZR left gold
    tint = function(core, "ib_items_tint")
    check("const int k = on && item >= 0 && item < IB_ITEMS && (frame == 1 || frame == 2) ? ib_button_of(age, item) : -1;"
          in tint and "if (k >= 0 && item != zr) {" in tint and
          "0x802f2d90ULL" in tint and "memcpy(ramp, ib_page.gold, 64)" in tint and
          "to = frame == 2 && item != zr ? 1.0f : 0.0f;" in tint,
          "the Items page's light blue is not State 2 with a blue ramp on face items alone, or not undone")
    # the Items page's glyphs: each slot's own part found (the parts pane itself, its glyph by path), face button k's glyph
    # (makeGuideKeyIconMsg 1 + k, coloured as the carousel's) on a slot whose item is on k (the item on ZR too), placed by the
    # slot's ItemPattern, hidden on every other slot and with the feature off
    layout = (ROOT / "nx2" / "item_buttons_layout.py").read_text(encoding="utf-8")
    badge = re.search(r'^SLOT, SLOT_TOP, BADGE, BADGE_PART = "(\w+)", "(\w+)", "(\w+)", "(\w+)"$', layout, re.M)
    check(badge and badge.group(4) == "PaGuideKey_00" and
          re.search(r'"%s",\s*"%s/T_Icon_00"' % (badge.group(3), badge.group(3)), core),
          "the host does not look for the slots' glyph part by the generator's name, or its glyph by the part's path")
    check("ib_badge(c, i, slot, k);" in tint and "ib_page.key[i] = 0, ib_page.slot[i] = slot;" in tint and
          "ib_guest(c, 0x8045e300ULL, 2, a, 0, NULL)" in tint and "ib_guest(c, 0x8045e1e0ULL, 2, b, 0, NULL)" in tint and
          "ib_page.cream_known = ib_glyph_white(c, ib_page.glyph[i], NULL, ib_page.cream);" in tint,
          "the Items page's slots' glyph parts are not looked up with the slots, or their cream not read first")
    marks = function(core, "ib_badge")
    check("ib_put_key(c, glyph, 1 + k)" in marks and "ib_glyph_colour(k, rgba) ? rgba : ib_page.cream" in marks and
          "ib_show(c, badge, 0), ib_page.key[i] = 0;" in marks and "ib_show(c, badge, 1);" in marks and
          "ib_badge_at(ib_frame(ib_peek(slot + 0x60, 8)), &x, &y);" in marks and "0x8022a3e0ULL" in marks,
          "a slot's glyph is not its face button's, coloured, placed by its ItemPattern, and hidden otherwise")
    check("ib_page.tinted || ib_page.badges)) ib_items_tint(c, s, page, on);" in function(core, "ib_pause_locked"),
          "the Items page's glyphs are not hidden once the feature is off")
    cells = function(core, "ib_cells_tint")
    check("if (frame || !ib_cells.base_known) continue;" in cells and "ib_cells.zero[i] >= 2 && !blue" in cells and
          "ib_colour(c, ib_cells.bg[i], 0, ib_cells.base[0])" in cells,
          "the carousel's light blue is not at frame 0 alone, or frame 0's colours not read and put back")
    # the control guide: ZR's entries get the combo while a hotkey item is out, the game's glyph back after
    check(re.search(r"#define IB_CTRL_GUIDE_VTABLE 0x84c05318ULL", core) and
          "else if (vt == IB_CTRL_GUIDE_VTABLE) ib_ctrl_guide(c, screen);" in function(core, "hos_oot_ib_screen"),
          "the control guide's screen is not handled after its update")
    check(re.search(r"#define IB_T_ICON 0x83e16a47ULL", core) and "0x80a8ae50ULL" in function(core, "ib_key_text"),
          "the control guide's glyphs are not makeGuideKeyIconMsg's on T_Icon_00")
    combos = function(core, "ib_combos")
    check("ib_key_text(c, IB_KEY_ZR, zr)" in combos and "ib_key_text(c, 1 + k, face[k])" in combos and
          "hos_sys_alloc(" in combos, "the combos are not ZR's, the hotkey's and the face's glyphs in memory of their own")
    tick = function(core, "ib_ctrl_guide_locked")
    check("ib_entry(want != 0, open, mine," in tick and "0x80459520ULL" in tick and
          "todo < 0 && ib_put_key(c, pane, IB_KEY_ZR)" in tick and "(uint32_t)o == ib_load32(&ib_answer)" in tick,
          "the control guide does not put the combo on the entries ib_entry picks (tests/test_item_buttons_filter.py), or "
          "the game's glyph back")
    gone = function(core, "ib_screen_gone")
    check("&ib_gd.screen" in gone and "&ib_pd.screen" in gone and "&ib_cg.screen" in gone and "&ib_tabs.screen" in gone and
          "&ib_cells.screen" in gone and "&ib_page.screen" in gone and "&ib_footer_room, 0" in gone and
          "&ib_plus" in gone and "ib_screen_gone(screen);" in function(hud, "hos_oot_ib_screen_gone"),
          "a destroyed screen's panes are kept by a guide, the tab bar, the carousel's cells or the Items page's slots, or the "
          "pause menu's stamp outlives its screen")
    check("__atomic_load_n(&ib_cells.screen, __ATOMIC_ACQUIRE) != screen" in cells and
          "__atomic_load_n(&ib_page.screen, __ATOMIC_ACQUIRE) != screen" in tint and
          "ib_items_tint(c, s, page, on);" in function(core, "ib_pause_locked"),
          "the carousel's cells or the Items page's slots are not looked up again for a screen of their own")
    print("PASS: the glyphs' text, the hints' and the guides' (the control guide's combo too), the ammunition's name and the "
          "boxes' input go through the calls that reach them")


COMBOS = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct Ctx { int unused; } Ctx;
enum { IB_A, IB_B, IB_X, IB_Y, IB_BUTTONS };
static uint8_t mem[0x1000];
#define GP(a) ((void *)(mem + ((uint64_t)(a) - 0x100000)))
#define HOS_WRITTEN(p, n) ((void)(p), (void)(n))
static uint64_t hos_sys_alloc(uint64_t size, uint64_t align) { (void)align; return size <= sizeof mem ? 0x100000 : 0; }
static int marks;   /* (the font served has the comma and the plus) */
int hos_prompts_punctuation(void) { return marks; }
static struct { uint64_t mem; char zr[8]; int zr_len; } ib_cg;
/* (makeGuideKeyIconMsg's glyph of key k: U+E03F + k, three bytes) */
static int ib_key_text(Ctx *c, int key, char out[8]) { (void)c; out[0] = (char)0xEE, out[1] = (char)0x80, out[2] = (char)(0xBF + key); return 3; }
%s
%s
#define CHECK(x) do { if (!(x)) { printf("FAIL line %%d: %%s\n", __LINE__, #x); fails++; } } while (0)
static int fails;
/* record i's text: {char *, int, s64 -1} and the text after it */
static int text_is(int i, const char *want, int n) {
    const uint64_t rec = 0x100000 + (uint64_t)(IB_COMBO_ROOM * i);
    uint64_t at; int32_t len; int64_t end;
    memcpy(&at, GP(rec), 8), memcpy(&len, GP(rec + 8), 4), memcpy(&end, GP(rec + 0x10), 8);
    return at == rec + 0x18 && len == n && end == -1 && !memcmp(GP(at), want, (size_t)n);
}
#define G(k) "\xEE\x80" k
int main(void) {
    Ctx c;
    marks = 1;   /* "ZR, L + A": the comma and the plus between the glyphs, each with its word spaces in it */
    CHECK(ib_combos(&c) == 1);
    CHECK(text_is(0, G("\xC7") "," G("\xC4") "+" G("\xC0"), 11));                     /* ZR, L + A */
    CHECK(text_is(IB_BUTTONS + IB_Y, G("\xC7") "," G("\xC6") "+" G("\xC3"), 11));     /* ZR, R + Y */
    CHECK(ib_cg.zr_len == 3 && !memcmp(ib_cg.zr, G("\xC7"), 3));
    memset(mem, 0, sizeof mem), ib_cg.mem = 0, marks = 0;   /* the game's font, or prompts made before the marks: a gap */
    CHECK(ib_combos(&c) == 1);
    CHECK(text_is(IB_X, G("\xC7") "            " G("\xC4") G("\xC2"), 21));              /* ZR  L X */
    if (!fails) printf("PASS: the control guide's combo is ZR, the comma, the hotkey, the plus, the face button with the "
                       "prompts' marks, and ZR, a gap, the hotkey, the face button without\n");
    return fails != 0;
}
'''


BADGES = r'''
#include <stdio.h>
%s
#define CHECK(x) do { if (!(x)) { printf("FAIL line %%d: %%s\n", __LINE__, #x); fails++; } } while (0)
static int fails;
/* the place of pattern p's glyph is pattern q's */
static int same(int p, int q) {
    float x, y, u, v;
    ib_badge_at(p, &x, &y), ib_badge_at(q, &u, &v);
    return x == u && y == v;
}
int main(void) {
    for (int p = 0; p < IB_PATTERNS; p++) {   /* the top right of the slot's 700-unit picture, the glyph (102 at 1.25) in it */
        float x, y;
        ib_badge_at(p, &x, &y);
        CHECK(x > 40 && y > 40 && x + 64 < 350 && y + 64 < 350);
    }
    for (int p = 10; p <= 22; p++) CHECK(same(p, 9));   /* the plain squares */
    CHECK(same(5, 4) && same(7, 6) && same(25, 24) && same(26, 24) && same(27, 24) && same(34, 33));   /* one shape each */
    for (int p = 29; p <= 31; p++) CHECK(same(p, 28));   /* the arrows' bars */
    CHECK(!same(23, 9) && !same(8, 6) && !same(24, 32));   /* the bottles, the pointed hexagons, the bow's and the hammer's */
    CHECK(same(-1, 9) && same(IB_PATTERNS, 9));   /* a frame the page does not use: the plain square's */
    if (!fails) printf("PASS: a slot's glyph sits on its box's top right corner, by the shape its ItemPattern picks\n");
    return fails != 0;
}
'''


def badges(core, cc, tmp):
    """the Items page's glyphs' places, compiled alone"""
    count = re.search(r"^enum \{ IB_PATTERNS = 36, IB_SHAPES = 14 \};$", core, re.M)
    check(count, "the slots' shapes' enum is not where it was")
    place = function(core, "ib_badge_at")
    for guest in ("ib_peek", "GP(", "ib_guest", "recomp_"):
        check(guest not in place, "ib_badge_at reads guest memory")
    c = Path(tmp) / "badges.c"
    exe = Path(tmp) / "badges.exe"
    c.write_text(BADGES % (count.group(0) + "\n" + place), encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
    r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    print(r.stdout, end="")
    if r.returncode:
        raise SystemExit("test_item_buttons_hud: the glyphs' places failed")


def combos(core, cc, tmp):
    """the control guide's combos, compiled with makeGuideKeyIconMsg and the guest memory stood in"""
    keys = re.search(r"^enum \{ IB_KEY_ZR = 8,[^\n]*", core, re.M)
    guides = re.search(r"^enum \{ IB_GUIDES = 5, IB_KEY_L = 5,[^\n]*", core, re.M)
    check(keys and guides, "the keys' enums are not where they were")
    c = Path(tmp) / "combos.c"
    exe = Path(tmp) / "combos.exe"
    c.write_text(COMBOS % (guides.group(0) + "\n" + keys.group(0), function(core, "ib_combos")), encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
    r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    print(r.stdout, end="")
    if r.returncode:
        raise SystemExit("test_item_buttons_hud: the combos failed")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host" / "oot_item_buttons_hud.c").read_text(encoding="utf-8")
    core = (ROOT / "host" / "oot_item_buttons.c").read_text(encoding="utf-8")
    game_side(src, core)
    with tempfile.TemporaryDirectory(prefix="item-buttons-combos-") as tmp:
        combos(core, a.cc, tmp)
        badges(core, a.cc, tmp)
    start = src.index("/* ---- the arrangement")
    end = src.index("/* ---- the game's side", start)
    arrangement = src[start:end]
    if "GP(" in arrangement or "Ctx" in arrangement or "ib_" in arrangement:
        raise SystemExit("FAIL: the arrangement part reaches into the game")
    api = (ROOT / "gpu" / "vk" / "vk_api.h").read_text(encoding="utf-8")
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    head = "#include <math.h>\n#include <stdint.h>\n#include <stdio.h>\n"
    head += block(api, "enum { HOS_SW_A") + ";\n" + block(api, "enum { HOS_PAD_SOUTH") + ";\n"
    head += block(api, "enum { HOS_PROMPT_SWITCH") + ";\n"
    head += block(hid, "static const signed char pad_default[HOS_SW_N]") + ";\n"
    with tempfile.TemporaryDirectory(prefix="item-buttons-hud-") as tmp:
        c = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture.exe"
        c.write_text(head + arrangement + FIXTURE, encoding="utf-8")
        subprocess.run([a.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe), "-lm"], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        print(r.stdout, end="")
        if r.returncode:
            print(r.stderr, end="")
            raise SystemExit("test_item_buttons_hud: failed")


if __name__ == "__main__":
    main()
