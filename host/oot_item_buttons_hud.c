/* (hookshot) Item assignable buttons, the HUD's part (host/oot_item_buttons.h): the items on A, B, X and Y in a small,
   half-faded diamond left of the ZR box, grown into the ZR box's place at full alpha while the hotkey is held, each with its
   button's glyph; over it the hint the game shows over its ZR box, with the hotkey's glyph, and over the ZR box the other
   shoulder button's.

   The HUD layout nx2/item_buttons_layout.py writes at build time has a hidden group N_ItemButtons_00 (the last child of
   N_All_00) holding four parts of the ZR box's own kind (PaItemBtn_00): Pa_ItemButtonA_00, B, X and Y, then a copy of the
   game's hint (N_Shortcut_00: four dots and a glyph), N_ItemButtonsHint_00 with its glyph T_ItemButtonsHint_00. The
   game's HUD is UIPlayerStatusScreen (vtable 0x84c0b710); the four are driven as it drives its ZR box, each with a
   control of the game's own class (ItemBtn, vtable 0x84c01400). nx2/oot_patches.py has the game call here (the supported
   build only):
   - hos_oot_ib_hud_init, at the head of the HUD's initLayout (f_83415d20; x0 the screen, x1 its heap). The controls are
     made here or never: the screen's frame heap is cut down to what it holds once the screen's init has returned. There
     is no constructor to call, so each is written field by field as initLayout writes the ZR box's, linked into the
     screen's control list and bound with ItemBtn::init (f_8045efe0, type 1: the HUD look). Each part brings a button
     (a UniteButton) into the screen's button controller, which the game's focus would take while the group is shown
     (the box cursor would run through the play, and the menus' mouse take the HUD for a menu): it takes a button only
     with its input on and its hit pane shown, so each part's button has its input off, as openParts switches the ZR
     box's off, and its B_Hit_00 (a pane nothing draws) hidden; both are kept so. Bound with the feature on or off. A
     layout without the parts (the game's own, a mod's) leaves all of it off;
   - ib_hud_tick, each frame after the HUD's own update (Screen::calc f_802f1380, through hos_oot_ib_screen): the group is
     shown while the feature is on and the game shows its right-hand group (IsItemVisible's frame, N_ScaleR_00's alpha),
     small or large; the ZR box (its parent-side pane Pa_SelectItem_00) and the L / R hint (N_Shortcut_00) fade out as it
     grows, through alphas no animation and no code of the game writes. The hint's copy keeps the game's hint's size over
     the top box whatever the group's scale; the glyphs of the two hints go on their text panes as the boxes' do (the
     game's own, R, is put back with the feature off). A box shows its button's item with its count as the HUD's
     refreshSelectItem (f_80a95770) shows the ZR item, greyed as the HUD greys its own box; its glyph, shown in the large
     arrangement, in the Xbox pad's colour for its letter with the Xbox prompts;
   - hos_oot_ib_screen_gone, at the head of ScreenBase::~ScreenBase (f_80aa2ad0): the screen's pointers are forgotten
     (and at the next bind of the same screen), and those the core file keeps of it (ib_screen_gone).
   Every pointer is checked before it is followed. Anything not as expected leaves the HUD part off for that screen, said
   once in the log. */
#include "oot_item_buttons.h"
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "../gpu/vk/vk_api.h"   /* (HOS_SW_*, HOS_PAD_*, HOS_BIND_PAD) */

int hos_binding(int set, int button, int slot);   /* nn_hid.c */
int hos_prompts_face(void);                       /* prompts.c */

/* ---- the arrangement (no guest memory: tests/test_item_buttons_hud.py compiles this part alone). In the root layout's
   units: 3840 x 2160, the origin at the centre, y up. The four parts are 380-unit boxes at scale 1 in the group, at 380
   from its centre; the group is moved, scaled and faded. t: 0 small, 1 large */
#define HUD_SPAN_NS 133333333LL   /* (small to large, or back: 8 frames at 60) */
#define HUD_STEP 380.0f           /* (a part's distance from the group's centre, in the group's units) */
#define HUD_PARENT_Y 2.0f         /* (N_All_00, the group's parent, sits at (0, 2)) */
#define HUD_REST_ALPHA 0.5f       /* (the small arrangement's alpha; the large one's 1) */
/* The box as seen reaches this far above a box's centre at scale 1: the top of its dark frame, measured on the screen
   against the ZR box at both of the group's scales (a few units under the edge of the frame's texture, SelectItemBase_00 from
   row 29 of its 253 on the 380-unit pane, 147); the game's hint over its ZR box (N_Shortcut_00, scale 1 in root units, 166
   above the centre of the box at scale 0.85) is centred this far above that top, in root units */
#define HUD_BOX_TOP 142.0f
#define HUD_HINT_OVER (166.0f - 0.85f * HUD_BOX_TOP)
/* x, y, scale: the small diamond (its right edge where it was at 0.29, 1425 left of the ZR box's 1464.5) and the large one
   (its hint's glyph under the screen's top edge) */
static const float hud_small[3] = {1285.0f, 822.0f, 0.2465f}, hud_large[3] = {1560.0f, 705.0f, 0.55f};

/* t a frame on: toward 1 while large, else toward 0, the whole way in HUD_SPAN_NS */
static float hud_advance(float t, int large, int64_t dt_ns) {
    if (!(t >= 0.0f)) t = 0.0f;   /* (NaN too) */
    if (t > 1.0f) t = 1.0f;
    if (dt_ns <= 0) return t;
    const float step = dt_ns >= HUD_SPAN_NS ? 1.0f : (float)dt_ns / (float)HUD_SPAN_NS;
    t += large ? step : -step;
    return t < 0.0f ? 0.0f : t > 1.0f ? 1.0f : t;
}

/* A glyph's colour for a face button whose pad input is pad (HOS_PAD_*) on the prompts' face (HOS_PROMPT_*): on the Xbox
   face its letters' own, A green, B red, X blue, Y yellow (bright shades, for a disc on a dark box), into rgba as the
   layout's colours are (linear); 0 for the game's cream (any other face or input) */
static int hud_tint(int face, int pad, float rgba[4]) {
    static const float xbox[4][3] = {   /* (sRGB, by pad: south A, east B, west X, north Y) */
        {0.42f, 0.76f, 0.29f}, {0.91f, 0.28f, 0.25f}, {0.24f, 0.56f, 0.87f}, {0.96f, 0.77f, 0.09f}};
    if (face != HOS_PROMPT_XBOX || pad < HOS_PAD_SOUTH || pad > HOS_PAD_NORTH) return 0;
    for (int i = 0; i < 3; i++) {
        const float s = xbox[pad][i];
        rgba[i] = s <= 0.04045f ? s / 12.92f : powf((s + 0.055f) / 1.055f, 2.4f);
    }
    rgba[3] = 1.0f;
    return 1;
}

/* t eased (smoothstep): what the place, the scale and the fades go by */
static float hud_ease(float t) {
    if (!(t > 0.0f)) return 0.0f;
    if (t >= 1.0f) return 1.0f;
    return t * t * (3.0f - 2.0f * t);
}

/* the group's translate (N_All_00's units), scale and alpha (before the game's right-hand group's) at an eased t */
static void hud_place(float e, float *x, float *y, float *scale, float *alpha) {
    *x = hud_small[0] + (hud_large[0] - hud_small[0]) * e;
    *y = hud_small[1] + (hud_large[1] - hud_small[1]) * e - HUD_PARENT_Y;
    *scale = hud_small[2] + (hud_large[2] - hud_small[2]) * e;
    *alpha = HUD_REST_ALPHA + (1.0f - HUD_REST_ALPHA) * e;
}

/* The hint's place over the top box and its scale, in the group's units for the group's scale: the game's hint's size and
   its gap over the box drawn, whatever the group's scale */
static void hud_hint(float scale, float *y, float *hint_scale) {
    if (!(scale > 0.01f)) scale = 0.01f;
    *y = HUD_STEP + HUD_BOX_TOP + HUD_HINT_OVER / scale;
    *hint_scale = 1.0f / scale;
}

/* The Switch's face buttons (IB_A..IB_Y, as HOS_SW_A..) whose glyphs go in the quick-switch menu's guide, in the pad's east,
   south, west, north order: pad[k] the gamepad input bound to button k; unless the four are the four face positions, one
   each, the Switch's own (A east, B south, Y west, X north). 1 when the pad's */
static int hud_faces(const int pad[4], int order[4]) {
    static const int where[4] = {HOS_PAD_EAST, HOS_PAD_SOUTH, HOS_PAD_WEST, HOS_PAD_NORTH}, switch_order[4] = {0, 1, 3, 2};
    int ok = 1;
    for (int i = 0; i < 4; i++) {
        order[i] = -1;
        for (int k = 0; k < 4; k++)
            if (pad[k] == where[i]) ok &= order[i] < 0, order[i] = k;
        ok &= order[i] >= 0;
    }
    for (int i = 0; i < 4 && !ok; i++) order[i] = switch_order[i];
    return ok;
}

/* Each face button's place in the diamond (the group's units) where the pad has it: pad[k] the gamepad input (HOS_PAD_*)
   bound to the Switch's A, B, X, Y. Unless the four are the four face positions, one each, the Switch's own: A right,
   B below, X above, Y left. 1 when the pad's */
static int hud_diamond(const int pad[4], float x[4], float y[4]) {
    static const int switch_pad[4] = {HOS_PAD_EAST, HOS_PAD_SOUTH, HOS_PAD_NORTH, HOS_PAD_WEST};
    int seen = 0, ok = 1;
    for (int k = 0; k < 4; k++) {
        const int p = pad[k];
        const int bit = p == HOS_PAD_EAST ? 1 : p == HOS_PAD_SOUTH ? 2 : p == HOS_PAD_WEST ? 4 : p == HOS_PAD_NORTH ? 8 : 0;
        if (!bit || (seen & bit)) ok = 0;
        seen |= bit;
    }
    for (int k = 0; k < 4; k++) {
        const int p = ok ? pad[k] : switch_pad[k];
        x[k] = p == HOS_PAD_EAST ? HUD_STEP : p == HOS_PAD_WEST ? -HUD_STEP : 0.0f;
        y[k] = p == HOS_PAD_NORTH ? HUD_STEP : p == HOS_PAD_SOUTH ? -HUD_STEP : 0.0f;
    }
    return ok;
}

/* ---- the game's side */

#define HUD_VTABLE 0x84c0b710ULL         /* UIPlayerStatusScreen */
#define ITEMBTN_VTABLE 0x84c01400ULL     /* game::ui::ItemBtn */
#define ITEMBTN_VTABLE_GOT 0x84cacb78ULL /* (where initLayout reads it from, less 16) */
#define BUTTON_VTABLE 0x84c416e8ULL      /* engine::ui::UniteButton: what a part brings into the screen's button controller */
#define FRAME_HEAP_VTABLE 0x84c17400ULL  /* the screens' heaps (sead::FrameHeap: +0xb0 the free space's start, +0xb8 its end) */
#define ANIM_NULL 0x84df2270ULL          /* LayoutAnim::sNull: what findAnim gives for a name the layout lacks */
#define POUCH_MGR 0x84e98e28ULL          /* PouchMgr::sInstance */
#define UI_STATE 0x84e9cfa8ULL           /* (+0x58c: bit 4 clear, the HUD greys its item box) */
#define S_PA_SELECT_ITEM 0x83dd4d58ULL   /* "Pa_SelectItem_00" in the executable */
#define S_T_ASSIGN 0x83deee49ULL         /* "T_Assign_00" */

#define F_NEW 0x8005ebe0ULL          /* operator new(size, heap, alignment) */
#define F_FIND_PANE 0x8045e300ULL    /* LayoutInstance::findPane(instance, name): the pane itself (a part's parent-side one) */
#define F_BTN_INIT 0x8045efe0ULL     /* ItemBtn::init(control, heap, type) */
#define F_INPUT 0x837927c0ULL        /* UniteButton::setInputEnable(button, on), its slot +0x70: bit 4 of its flags */
#define F_TEXT_EMPTY 0x80a86f70ULL   /* a string record emptied */
#define F_KEY_TEXT 0x80a8ae50ULL     /* makeGuideKeyIconMsg(record, key: 1 A, 2 B, 3 X, 4 Y, 5 L, 7 R): 1 when the message is
                                        there; its text is the message system's, which the pane keeps a pointer to */
#define F_PANE_TEXT 0x80459520ULL    /* Pane::setTextBoxString(pane, record): any text box's (the layout's setter, by path,
                                        takes only those whose text id is "@name"; T_Assign_00's is "*", a message label) */
#define F_COLORS 0x8045b700ULL       /* Pane::getMaterialColors(pane): its colours (+0x10 the white, 4 floats), 0 none */
#define F_WHITE 0x8155db90ULL        /* MaterialColors::setWhiteColor(colors; s0..s3): a text pane's glyph colour */
#define F_VISIBLE 0x8022aea0ULL      /* Pane::setVisible(pane, on) */
#define F_ALPHA 0x802f8ac0ULL        /* Pane::setAlpha(pane; s0) */
#define F_TRANSLATE 0x8022a3e0ULL    /* Pane::setTranslate(pane; s0 x, s1 y, s2 z) */
#define F_SCALE 0x80b49b20ULL        /* Pane::setScale(pane; s0 x, s1 y, s2 z) */
#define F_SET_ITEM 0x80a95ef0ULL     /* ItemBtn::setItem(control, name, item, reset alpha, pouch icon, mini game, no bounce) */
#define F_STOCK 0x80a95df0ULL        /* ItemBtn::setStockNum(control, count, most, full) */
#define F_STOCK_SHOWN 0x833dcdd0ULL  /* ItemBtn::setStockNumVisible(control, on) */
#define F_INVALID 0x80f40400ULL      /* ItemBtn::setInvalid(control, on): greyed */
#define F_ROW 0x805aed10ULL          /* PouchActorInfoTable::find(name): the actor's row, or 0 */
#define F_CATEGORY 0x8015fdd0ULL     /* a PouchCategory to its number (int *out, name): 1 when known; 1 Bow */
#define F_ACTOR 0x802d5480ULL        /* an actor's name from its path (record out, name): "Work/Actor/X.engine__..gyml" X */
#define F_AMMO 0x80a865a0ULL         /* the pouch's name of an actor (record out, name) */
#define F_COUNT 0x805b63e0ULL        /* PouchMgr::getContentNum(mgr, name, direct, mini game) */
#define F_COUNT_MAX 0x805b5cf0ULL    /* PouchMgr::getContentMaxNum(mgr, name, mini game, bool *) */
#define F_COUNT_FULL 0x80a94910ULL   /* PouchMgr::isContentNumMax(mgr, name) */
static const uint64_t functions[] = {F_NEW, F_FIND_PANE, F_BTN_INIT, F_INPUT, F_TEXT_EMPTY, F_KEY_TEXT, F_PANE_TEXT,
                                     F_COLORS, F_WHITE, F_VISIBLE, F_ALPHA, F_TRANSLATE, F_SCALE, F_SET_ITEM, F_STOCK,
                                     F_STOCK_SHOWN, F_INVALID, F_ROW, F_CATEGORY, F_ACTOR, F_AMMO, F_COUNT, F_COUNT_MAX,
                                     F_COUNT_FULL};

/* the screen (+0x28 its body layout, +0x38 its button controller, +0x168 its heap, +0x1a6 1 opening 2 open 3 closing,
   +0x2c0 the IsItemVisible animation); its two control lists, closed and open: the head, the count, the node's offset in
   a control */
enum { SCREEN_BODY = 0x28, SCREEN_BUTTONS = 0x38, SCREEN_HEAP = 0x168, SCREEN_OPEN = 0x1a6, SCREEN_ITEM_VISIBLE = 0x2c0 };
static const int list_head[2] = {0x150, 0x138}, list_count[2] = {0x160, 0x148}, list_node[2] = {0x164, 0x14c};
/* a layout (+0x28 its screen, +0x3a its open state, +0x80 its instance); an instance's child parts (+0x128 the list's
   end, +0x130 its first; a node: +8 the next, +0x148 the part's name, +0xb0 its layout) */
enum { LAYOUT_SCREEN = 0x28, LAYOUT_OPEN = 0x3a, LAYOUT_INSTANCE = 0x80 };
enum { PARTS_END = 0x128, PARTS_FIRST = 0x130, NODE_NEXT = 8, NODE_NAME = 0x148, NODE_LAYOUT = 0xb0 };
/* a pane: scale +0x60, translate +0x6c, alpha +0x74, bit 0 of +0xa8 shown; its colours' white at +0x10 */
enum { PANE_SCALE = 0x60, PANE_TRANSLATE = 0x6c, PANE_ALPHA = 0x74, PANE_FLAGS = 0xa8, COLORS_WHITE = 0x10 };
/* an ItemBtn: +0x60 its Type animation, +0x80 its icon control (ItemBtn::init's) */
enum { CTRL_SIZE = 0x110, CTRL_TYPE_ANIM = 0x60, CTRL_ICON = 0x80 };
/* the button controller: a list at +0x08 (its first +0x10) of buttons linked at their +0x08; a button: +0x20 its layout,
   +0x40 its flags (bit 4 input on) */
enum { BUTTONS_LIST = 0x08, BUTTON_NODE = 0x08, BUTTON_LAYOUT = 0x20, BUTTON_FLAGS = 0x40, BUTTON_INPUT_ON = 0x10 };
/* a PouchActorInfo row: +0x70 PouchCategory, +0x98 ShootableActor, +0xfa PouchStockable */
enum { ROW_CATEGORY = 0x70, ROW_SHOOTABLE = 0x98, ROW_STOCKABLE = 0xfa };
/* (what one control takes of the heap with what ItemBtn::init makes for it: its icon control and two texture replacers;
   and what the game's own controls, made after these, are left at the least) */
#define CTRL_HEAP (CTRL_SIZE + 0x40 + 2 * (0x58 + 0x40 + 0xe8 + 0x60))
#define HEAP_SPARE 0x100000

/* The scratch block, from the screen's heap at bind */
enum {
    SC_SLOT = 0x00,     /* a name slot: the address of one of the game's strings (ib_item_name, ib_item_owned) */
    SC_INT = 0x08,      /* an int the game writes */
    SC_TEXT = 0x10,     /* a string record {char *, int, s64} (0x18): a glyph's text */
    SC_NAME = 0x30,     /* a name record {char *at, int size 0x40; the text at +0x10}: the item's actor */
    SC_SHOT = 0x80,     /* the same: the actor it shoots */
    SC_AMMO = 0xd0,     /* the same: its ammunition's in the pouch */
    SC_STRINGS = 0x120, /* the pane names the executable does not have */
    SC_SIZE = 0x220
};
#define NAME_ROOM 0x40
enum { KEY_L = 5, KEY_R = 7 };   /* (makeGuideKeyIconMsg's keys of the shoulder buttons) */
static const char *const part_names[IB_BUTTONS] = {"Pa_ItemButtonA_00", "Pa_ItemButtonB_00", "Pa_ItemButtonX_00",
                                                   "Pa_ItemButtonY_00"};
/* (the strings in the block, S_PART + k the parts'): the group, the right-hand group, the game's hint over the ZR box and its
   glyph, the hint's copy over the diamond and its glyph, a part's icon group and its hit pane */
enum { S_GROUP, S_SCALE_R, S_HINT, S_HINT_KEY, S_MY_HINT, S_MY_HINT_KEY, S_ITEM, S_HIT, S_PART };
static const char *const pane_names[S_PART] = {"N_ItemButtons_00", "N_ScaleR_00", "N_Shortcut_00", "T_ShortCut_00",
                                               "N_ItemButtonsHint_00", "T_ItemButtonsHint_00", "N_Item_00", "B_Hit_00"};

typedef struct {
    int item;           /* shown: IB_NONE empty */
    int want, owned;    /* the button's item, and whether the pouch has it (-1 not asked yet) */
    char name[NAME_ROOM];   /* the actor its icon and count go by */
    uint64_t row;       /* its PouchActorInfo row (0 none: no count) */
    int ammo, stock;    /* its count is its ammunition's (PouchCategory Bow), or its own (PouchStockable) */
    int counted, num, full, greyed;   /* as last set */
} Box;

typedef struct {
    uint64_t scratch, group, scale_r, hint, zr;
    uint64_t hint_key, my_hint, my_hint_key;   /* (the game's hint's glyph; the copy over the diamond and its glyph, 0: none) */
    int hint_set, my_hint_set;                 /* (the key put on each glyph: 0 none yet, the game's own text on the first) */
    uint64_t strings[S_PART + IB_BUTTONS];
    uint64_t ctrl[IB_BUTTONS], layout[IB_BUTTONS], part[IB_BUTTONS], glyph[IB_BUTTONS], icons[IB_BUTTONS], hit[IB_BUTTONS];
    uint64_t button[IB_BUTTONS];   /* (the part's button, part_button) */
    float glyph_alpha[IB_BUTTONS], cream[IB_BUTTONS][4];   /* (cream: the glyph's colour in the layout) */
    int glyphs;         /* bits: the glyph's text set (the message may not be there at bind: again later) */
    int coloured;       /* bits: the glyph's pane has colours (cream read) */
    Box box[IB_BUTTONS];
    float t;
    int64_t last_ns;
    int off, quiet;     /* quiet: the next item shown without the game's bounce (the first after bind or on) */
    unsigned ticks;
} Hud;

/* Two, so a screen made before the last is destroyed has one; a slot is the screen's once its screen is set (last), and
   busy while a bind or a frame uses it (bind and frame never wait for it: they take the other one, or pass a frame) */
typedef struct { uint64_t screen; int busy; Hud h; } Slot;
static Slot slots[2];

static int take(Slot *s) {
    int idle = 0;
    return __atomic_compare_exchange_n(&s->busy, &idle, 1, 0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED);
}
static void give(Slot *s) { __atomic_store_n(&s->busy, 0, __ATOMIC_RELEASE); }

/* a guest read of a pointer the game's objects hold: 0 unless it is in the guest's space (not the null page) */
static int peek(uint64_t a, void *dst, size_t n) {
    const void *p = a >= 0x100000 ? hos_guest_range(a, n) : NULL;
    if (!p) return 0;
    memcpy(dst, p, n);
    return 1;
}
static uint64_t peek64(uint64_t a) {
    uint64_t v = 0;
    return peek(a, &v, 8) ? v : 0;
}
static uint8_t peek8(uint64_t a) {
    uint8_t v = 0;
    return peek(a, &v, 1) ? v : 0;
}
static int readable(uint64_t a, uint64_t n) { return a >= 0x100000 && hos_guest_range(a, n); }
/* a C string at a into out (cap bytes with its NUL); 0 if it is not there whole */
static int text_at(uint64_t a, char *out, size_t cap) {
    for (size_t i = 0; i < cap; i++) {
        if (!peek(a + i, &out[i], 1)) break;
        if (!out[i]) return 1;
    }
    out[0] = 0;
    return 0;
}

static uint64_t guest(Ctx *c, uint64_t fn, int n, const uint64_t *x) { return ib_guest(c, fn, n, x, 0, NULL); }
#define CALL(c, fn, ...) guest((c), (fn), (int)(sizeof((uint64_t[]){__VA_ARGS__}) / sizeof(uint64_t)), (const uint64_t[]){__VA_ARGS__})

/* the pane setters, called only when the pane differs (each is a call into the game, and a held change marks the
   layout to be worked out again) */
static void pane_shown(Ctx *c, uint64_t pane, int on) {
    uint32_t flags;
    if (pane && peek(pane + PANE_FLAGS, &flags, 4) && (int)(flags & 1) != !!on) CALL(c, F_VISIBLE, pane, !!on);
}
static void pane_alpha(Ctx *c, uint64_t pane, float a) {
    float now;
    if (pane && peek(pane + PANE_ALPHA, &now, 4) && now != a) ib_guest(c, F_ALPHA, 1, &pane, 1, &a);
}
static void pane_at(Ctx *c, uint64_t pane, float x, float y) {
    float now[2];
    const float s[3] = {x, y, 0.0f};
    if (pane && peek(pane + PANE_TRANSLATE, now, 8) && (now[0] != x || now[1] != y)) ib_guest(c, F_TRANSLATE, 1, &pane, 3, s);
}
static void pane_scale(Ctx *c, uint64_t pane, float scale) {
    float now[2];
    const float s[3] = {scale, scale, 1.0f};
    if (pane && peek(pane + PANE_SCALE, now, 8) && (now[0] != scale || now[1] != scale)) ib_guest(c, F_SCALE, 1, &pane, 3, s);
}

/* ---- the log: each reason once */
enum { SAID_NO_PARTS = 1, SAID_PARTS = 2, SAID_GAME = 4, SAID_HEAP = 8, SAID_SLOT = 16, SAID_ALLOC = 32, SAID_PANE = 64,
       SAID_INIT = 128, SAID_GLYPH = 256, SAID_HINT = 512 };
static unsigned said, binds;
static int first_time(unsigned what) { return !(__atomic_fetch_or(&said, what, __ATOMIC_RELAXED) & what); }

/* the child part named name of an instance, as initLayout finds the ZR box's: its layout, or 0 */
static uint64_t child_parts(uint64_t inst, const char *name) {
    const uint64_t end = inst + PARTS_END;
    uint64_t node = peek64(inst + PARTS_FIRST);
    for (int n = 0; node && node != end && n < 512; n++, node = peek64(node + NODE_NEXT)) {
        char got[40];
        if (text_at(peek64(node + NODE_NAME), got, sizeof got) && !strcmp(got, name)) return peek64(node + NODE_LAYOUT);
    }
    return 0;
}

/* The button a part's layout brought into the screen's button controller, found as ItemBtn::init finds it (its +0xe0), or
   0. (GamePartsControl::setButtonInputEnable, f_80f42330, does not reach it: for a button of a part (flags bit 13) it
   compares the layout's +0x30, not the layout, with the control's) */
static uint64_t part_button(uint64_t screen, uint64_t layout) {
    const uint64_t controller = peek64(screen + SCREEN_BUTTONS), head = controller + BUTTONS_LIST;
    uint64_t node = controller && layout ? peek64(head + 8) : 0;
    for (int n = 0; node && node != head && n < 256; n++, node = peek64(node + 8)) {
        const uint64_t button = node - BUTTON_NODE;
        if (peek64(button + BUTTON_LAYOUT) == layout) return peek64(button) == BUTTON_VTABLE ? button : 0;
    }
    return 0;
}

/* A part's button with its input off, as openParts switches the ZR box's off each time the HUD opens: the game's focus
   (and its pointer) take a button only with its input on */
static void input_off(Ctx *c, uint64_t button) {
    uint32_t flags;
    if (button && peek(button + BUTTON_FLAGS, &flags, 4) && (flags & BUTTON_INPUT_ON)) CALL(c, F_INPUT, button, 0);
}

/* a name record at the scratch block's off holding text */
static void put_name(Ctx *c, Hud *h, int off, const char *text) {
    const uint64_t rec = h->scratch + (uint64_t)off;
    char *p = GP(rec + 0x10);
    size_t n = strlen(text);
    if (n > NAME_ROOM - 1) n = NAME_ROOM - 1;
    memcpy(p, text, n);
    memset(p + n, 0, NAME_ROOM - n);
    HOS_WRITTEN(p, NAME_ROOM);
    recomp_store64(c, rec, rec + 0x10);
    recomp_store32(c, rec + 8, NAME_ROOM);
}

/* A control for a part's layout, as initLayout makes the ZR box's: the parts control (its screen, its layout, open as
   the layout is, at the back of the screen's list for that), then the ItemBtn's own fields. 0 if the heap gave none */
static uint64_t make_control(Ctx *c, uint64_t heap, uint64_t screen, uint64_t layout) {
    const int open = peek8(layout + LAYOUT_OPEN) != 0;
    int32_t node_at = -1;
    peek(screen + (uint64_t)list_node[open], &node_at, 4);
    const uint64_t head = screen + (uint64_t)list_head[open], count = screen + (uint64_t)list_count[open];
    if (node_at < 0 || node_at > CTRL_SIZE - 16 || !readable(head, 8) || !readable(count, 4)) return 0;
    const uint64_t btn = CALL(c, F_NEW, CTRL_SIZE, heap, 8);
    uint8_t *p = btn ? (uint8_t *)hos_guest_range(btn, CTRL_SIZE) : NULL;
    if (!p || btn < 0x100000) return 0;
    memset(p, 0, CTRL_SIZE);
    HOS_WRITTEN(p, CTRL_SIZE);
    recomp_store64(c, btn + 0x18, screen);
    recomp_store64(c, btn + 0x20, layout);
    recomp_store16(c, btn + 0x28, 0x100);
    recomp_store8(c, btn + 0x2a, (uint64_t)open);
    const uint64_t node = btn + (uint64_t)node_at, last = peek64(head);
    recomp_store64(c, head, node);
    recomp_store64(c, node, last);
    recomp_store64(c, node + 8, head);
    if (last && readable(last + 8, 8)) recomp_store64(c, last + 8, node);
    recomp_store32(c, count, recomp_load32(c, count) + 1);
    recomp_store64(c, btn, ITEMBTN_VTABLE);
    recomp_store64(c, btn + 0x88, btn + 0x94);    /* its name: a 0x40-byte buffer at +0x94 */
    recomp_store32(c, btn + 0x90, 0x40);
    recomp_store32(c, btn + 0xd8, 0xffffffffu);   /* no item */
    recomp_store64(c, btn + 0xf0, btn + 0x100);   /* its count's text: 16 bytes at +0x100 */
    recomp_store64(c, btn + 0xf8, 0x1000000000ULL);
    return btn;
}

/* a button's glyph (makeGuideKeyIconMsg's message for key) on a text pane itself; 0 when the message is not there (yet) */
static int put_key(Ctx *c, Hud *h, uint64_t pane, int key) {
    const uint64_t rec = h->scratch + SC_TEXT;
    CALL(c, F_TEXT_EMPTY, rec);
    if (!(CALL(c, F_KEY_TEXT, rec, (uint64_t)key) & 1)) return 0;
    CALL(c, F_PANE_TEXT, pane, rec);
    return 1;
}

/* the glyphs not set yet: key 1 + k (A, B, X, Y) on each part's T_Assign_00, the message setAssignKey makes */
static void set_glyphs(Ctx *c, Hud *h) {
    for (int k = 0; k < IB_BUTTONS; k++)
        if (!(h->glyphs >> k & 1) && put_key(c, h, h->glyph[k], 1 + k)) h->glyphs |= 1 << k;
}

/* The hints' glyphs for the feature as it is: over the diamond the hotkey's, over the ZR box the other shoulder button's (the
   game's own text there is R: it is written only once the hotkey is R, and R put back after) */
static void set_hints(Ctx *c, Hud *h, int on) {
    const int hot_r = ib_hotkey() == IB_HOTKEY_R;
    const int mine = hot_r ? KEY_R : KEY_L, zr = on && hot_r ? KEY_L : h->hint_set ? KEY_R : 0;
    if (on && h->my_hint_key && h->my_hint_set != mine && put_key(c, h, h->my_hint_key, mine)) h->my_hint_set = mine;
    if (zr && h->hint_set != zr && put_key(c, h, h->hint_key, zr)) h->hint_set = zr;
}

/* A text pane's glyph colour (MaterialColors' white, as the layout's colours: linear rgba): into was when it is wanted, and
   set to rgba unless it is that already (each set walks the pane tree up). 0 when the pane has no colours */
int ib_glyph_white(Ctx *c, uint64_t pane, const float rgba[4], float was[4]) {
    const uint64_t colors = pane ? CALL(c, F_COLORS, pane) : 0;
    float now[4];
    if (!colors || !peek(colors + COLORS_WHITE, now, sizeof now)) return 0;
    if (was) memcpy(was, now, sizeof now);
    if (rgba && memcmp(now, rgba, sizeof now)) ib_guest(c, F_WHITE, 1, &colors, 4, rgba);
    return 1;
}

/* glyph k's colour now: 1 and rgba with the Xbox prompts (the colour of the pad input on its button), 0 the cream */
int ib_glyph_colour(int k, float rgba[4]) {
    return k >= 0 && k < IB_BUTTONS && hud_tint(hos_prompts_face(), hos_binding(HOS_BIND_PAD, HOS_SW_A + k, 0), rgba);
}

void ib_face_order(int order[IB_BUTTONS]) {
    int pad[IB_BUTTONS];
    for (int k = 0; k < IB_BUTTONS; k++) pad[k] = hos_binding(HOS_BIND_PAD, HOS_SW_A + k, 0);
    hud_faces(pad, order);
}

void hos_oot_ib_hud_init(Ctx *c, uint64_t screen, uint64_t heap) {
    if (!c || !screen) return;
    for (int j = 0; j < 2; j++) {   /* (the same screen bound before: made again, or a new one where a gone one was) */
        uint64_t was = screen;
        __atomic_compare_exchange_n(&slots[j].screen, &was, 0, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED);
    }
    const uint64_t body = peek64(screen + SCREEN_BODY), inst = body ? peek64(body + LAYOUT_INSTANCE) : 0;
    if (peek64(screen) != HUD_VTABLE || !inst) {
        if (first_time(SAID_GAME)) hos_log("item buttons: the HUD screen %#llx is not as expected: no item buttons on the HUD",
                                           (unsigned long long)screen);
        return;
    }
    uint64_t layout[IB_BUTTONS];
    int found = 0;
    for (int k = 0; k < IB_BUTTONS; k++) found += (layout[k] = child_parts(inst, part_names[k])) != 0;
    if (!found) {
        if (first_time(SAID_NO_PARTS))
            hos_log("item buttons: the HUD layout has no item buttons (the game's own, or a mod's): none on the HUD");
        return;
    }
    const char *why = NULL;
    unsigned what = 0;
    Slot *slot = NULL;
    Hud *h = NULL;
    if (found < IB_BUTTONS) why = "the HUD layout has some of the item buttons only", what = SAID_PARTS;
    for (int k = 0; !why && k < IB_BUTTONS; k++)   /* (ItemBtn::init's own search for the icon part has no end test) */
        if (peek64(layout[k] + LAYOUT_SCREEN) != screen || !child_parts(peek64(layout[k] + LAYOUT_INSTANCE), "Pa_ReplaceIcon_00"))
            why = "an item button in the HUD layout is not of the ZR box's kind", what = SAID_PARTS;
    for (size_t i = 0; !why && i < sizeof functions / sizeof *functions; i++)
        if (!a64_lookup(functions[i])) why = "a function of the game is missing", what = SAID_GAME;
    if (!why && (peek64(ITEMBTN_VTABLE_GOT) + 16 != ITEMBTN_VTABLE || !peek64(screen + SCREEN_BUTTONS)))
        why = "the game's item box class is not where it should be", what = SAID_GAME;
    const uint64_t room = peek64(heap + 0xb8) - peek64(heap + 0xb0);
    if (!why && (peek64(screen + SCREEN_HEAP) != heap || peek64(heap) != FRAME_HEAP_VTABLE ||
                 peek64(heap + 0xb0) > peek64(heap + 0xb8) || room < SC_SIZE + IB_BUTTONS * CTRL_HEAP + HEAP_SPARE))
        why = "the HUD screen's heap is not a frame heap with room for the item buttons", what = SAID_HEAP;
    for (int pass = 0; !why && !slot && pass < 2; pass++)   /* (a free slot, else the other screen's) */
        for (int j = 0; !slot && j < 2; j++)
            if ((pass || !__atomic_load_n(&slots[j].screen, __ATOMIC_ACQUIRE)) && take(&slots[j])) slot = &slots[j];
    if (!why && !slot) why = "both of the HUD part's places are in use", what = SAID_SLOT;
    if (!why) {
        __atomic_store_n(&slot->screen, 0, __ATOMIC_RELEASE);
        h = &slot->h;
        memset(h, 0, sizeof *h);
        h->scratch = CALL(c, F_NEW, SC_SIZE, heap, 8);
        if (h->scratch < 0x100000 || !hos_guest_range(h->scratch, SC_SIZE))
            why = "the HUD screen's heap gave no memory", what = SAID_ALLOC;
    }
    if (!why) {
        uint8_t *p = GP(h->scratch);
        memset(p, 0, SC_SIZE);
        uint64_t at = h->scratch + SC_STRINGS;
        for (int i = 0; i < S_PART + IB_BUTTONS; i++) {
            const char *s = i < S_PART ? pane_names[i] : part_names[i - S_PART];
            memcpy(GP(at), s, strlen(s) + 1);
            h->strings[i] = at, at += strlen(s) + 1;
        }
        HOS_WRITTEN(p, SC_SIZE);
        put_name(c, h, SC_NAME, "");
        put_name(c, h, SC_AMMO, "");
        h->group = CALL(c, F_FIND_PANE, inst, h->strings[S_GROUP]);
        h->scale_r = CALL(c, F_FIND_PANE, inst, h->strings[S_SCALE_R]);
        h->hint = CALL(c, F_FIND_PANE, inst, h->strings[S_HINT]);
        h->hint_key = CALL(c, F_FIND_PANE, inst, h->strings[S_HINT_KEY]);
        h->zr = CALL(c, F_FIND_PANE, inst, S_PA_SELECT_ITEM);
        h->my_hint = CALL(c, F_FIND_PANE, inst, h->strings[S_MY_HINT]);
        h->my_hint_key = h->my_hint ? CALL(c, F_FIND_PANE, inst, h->strings[S_MY_HINT_KEY]) : 0;
        if (!h->group) why = "the HUD layout has no N_ItemButtons_00";
        else if (!h->scale_r || !h->hint || !h->hint_key || !h->zr)
            why = "the HUD layout lacks N_ScaleR_00, N_Shortcut_00, T_ShortCut_00 or Pa_SelectItem_00";
        if (!h->my_hint_key) h->my_hint = 0;   /* (a layout without the hint's copy: the boxes alone) */
        for (int k = 0; !why && k < IB_BUTTONS; k++) {
            const uint64_t pinst = peek64(layout[k] + LAYOUT_INSTANCE);
            h->layout[k] = layout[k];
            h->part[k] = CALL(c, F_FIND_PANE, inst, h->strings[S_PART + k]);
            h->glyph[k] = CALL(c, F_FIND_PANE, pinst, S_T_ASSIGN);
            h->icons[k] = CALL(c, F_FIND_PANE, pinst, h->strings[S_ITEM]);
            h->hit[k] = CALL(c, F_FIND_PANE, pinst, h->strings[S_HIT]);
            if (!h->part[k] || !h->glyph[k] || !h->icons[k] || !h->hit[k])
                why = "an item button lacks its pane, T_Assign_00, N_Item_00 or B_Hit_00";
        }
        if (why) what = SAID_PANE;
    }
    for (int k = 0; !why && k < IB_BUTTONS; k++) {
        h->ctrl[k] = make_control(c, heap, screen, layout[k]);
        if (!h->ctrl[k]) {
            why = "the HUD screen's heap gave no memory", what = SAID_ALLOC;
            break;
        }
        CALL(c, F_BTN_INIT, h->ctrl[k], heap, 1);
        const uint64_t type = peek64(h->ctrl[k] + CTRL_TYPE_ANIM);
        if (!peek64(h->ctrl[k] + CTRL_ICON) || !type || type == ANIM_NULL)
            why = "an item button came out of ItemBtn::init without its icon or its animations", what = SAID_INIT;
        input_off(c, h->button[k] = part_button(screen, layout[k]));
    }
    if (why) {
        for (int k = 0; k < IB_BUTTONS; k++) input_off(c, part_button(screen, layout[k]));
        if (first_time(what))
            hos_log("item buttons: %s (HUD screen %#llx, %llu bytes free): no item buttons on the HUD", why,
                    (unsigned long long)screen, (unsigned long long)room);
        if (slot) give(slot);
        return;
    }
    for (int k = 0; k < IB_BUTTONS; k++) {   /* each starts empty, its glyph hidden until the large arrangement */
        float a = 0.0f;
        peek(h->glyph[k] + PANE_ALPHA, &a, 4);
        h->glyph_alpha[k] = a > 0.0f && a <= 1.0f ? a : 0.8f;   /* (the file's 0.8) */
        if (ib_glyph_white(c, h->glyph[k], NULL, h->cream[k])) h->coloured |= 1 << k;
        CALL(c, F_VISIBLE, h->hit[k], 0);
        CALL(c, F_VISIBLE, h->icons[k], 0);
        CALL(c, F_STOCK_SHOWN, h->ctrl[k], 0);
        CALL(c, F_INVALID, h->ctrl[k], 0);
        Box *b = &h->box[k];
        b->item = b->want = IB_NONE, b->owned = -1;
    }
    set_glyphs(c, h);
    if (h->glyphs != 0xf && first_time(SAID_GLYPH)) hos_log("item buttons: the glyphs' messages are not there yet: set later");
    if (!h->my_hint && first_time(SAID_HINT)) hos_log("item buttons: the HUD layout has no hint over the item buttons");
    h->quiet = 1;
    __atomic_store_n(&slot->screen, screen, __ATOMIC_RELEASE);
    give(slot);
    if (__atomic_fetch_add(&binds, 1, __ATOMIC_RELAXED) < 8)
        hos_log("item buttons: the HUD's four boxes bound (HUD screen %#llx, %llu bytes of its heap free before)",
                (unsigned long long)screen, (unsigned long long)room);
}

void hos_oot_ib_screen_gone(uint64_t screen) {
    if (!screen) return;
    ib_screen_gone(screen);
    for (int j = 0; j < 2; j++) {
        uint64_t was = screen;
        __atomic_compare_exchange_n(&slots[j].screen, &was, 0, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED);
    }
}

/* ---- the boxes */
static int is_bottle(int item) { return (item >= 14 && item <= 17) || item == 50; }

/* the actor ib_item_name gives an item, into out (NAME_ROOM); 0 if none */
static int item_name(Ctx *c, Hud *h, int item, char *out) {
    out[0] = 0;
    return ib_item_name(c, item, h->scratch + SC_SLOT) && text_at(peek64(h->scratch + SC_SLOT), out, NAME_ROOM) && out[0];
}

static void box_empty(Ctx *c, Hud *h, int k) {
    Box *b = &h->box[k];
    if (b->item == IB_NONE) return;
    pane_shown(c, h->icons[k], 0);
    CALL(c, F_STOCK_SHOWN, h->ctrl[k], 0);
    CALL(c, F_INVALID, h->ctrl[k], 0);
    b->item = IB_NONE, b->name[0] = 0, b->row = 0, b->counted = 0, b->greyed = 0;
}

/* The count as refreshSelectItem shows the ZR item's: none for a bottle or an actor with no row; for the rows of
   PouchCategory Bow (the bow, the slingshot, the magic arrows) its ammunition's: ShootableActor, a path, cut to the
   actor's name, then as the pouch names it; else its own if it is PouchStockable */
static void box_count(Ctx *c, Hud *h, int k) {
    Box *b = &h->box[k];
    const uint64_t mgr = peek64(POUCH_MGR);
    uint64_t src = 0;
    if (mgr && b->row && b->ammo && peek64(b->row + ROW_SHOOTABLE)) {
        put_name(c, h, SC_SHOT, "");
        CALL(c, F_ACTOR, h->scratch + SC_SHOT, b->row + ROW_SHOOTABLE);
        put_name(c, h, SC_AMMO, "");
        CALL(c, F_AMMO, h->scratch + SC_AMMO, h->scratch + SC_SHOT);
        src = h->scratch + SC_AMMO;
    } else if (mgr && b->row && b->stock) {
        put_name(c, h, SC_NAME, b->name);
        src = h->scratch + SC_NAME;
    }
    if (src) {
        const int num = (int)(int32_t)CALL(c, F_COUNT, mgr, src, 1, 0);
        const uint64_t most = (uint32_t)CALL(c, F_COUNT_MAX, mgr, src, 0, 0);
        const int full = (int)(CALL(c, F_COUNT_FULL, mgr, src) & 1);
        if (!b->counted || num != b->num || full != b->full)
            CALL(c, F_STOCK, h->ctrl[k], (uint32_t)num, most, (uint64_t)full), b->num = num, b->full = full;
    }
    if ((src != 0) != b->counted) CALL(c, F_STOCK_SHOWN, h->ctrl[k], src != 0), b->counted = src != 0;
}

/* Box k: the item on its button at this age, if the pouch has it, else empty. The name is asked each frame for a bottle
   (its content changes it), otherwise when the item changes and on slow frames; setItem only when one of them changed
   (each call sends two texture requests), with the ZR slot pinned to the item meanwhile (the bow family's icon goes by
   the ZR item); ownership and the count on slow frames */
static void box_frame(Ctx *c, Hud *h, int k, int age, int slow, int greyed) {
    Box *b = &h->box[k];
    int e = ib_assignment(age, k);
    if (e < 0 || e >= IB_ITEMS) e = IB_NONE;
    if (e != b->want) b->want = e, b->owned = -1;
    if (e == IB_NONE) {
        box_empty(c, h, k);
        return;
    }
    if (slow || b->owned < 0) b->owned = ib_item_owned(c, e, h->scratch + SC_SLOT) ? 1 : 0;
    char name[NAME_ROOM];
    if (!b->owned) {
        box_empty(c, h, k);
        return;
    }
    if (e == b->item && !is_bottle(e) && !slow) memcpy(name, b->name, sizeof name);
    else if (!item_name(c, h, e, name)) {
        box_empty(c, h, k);
        return;
    }
    int count = slow;
    if (e != b->item || strcmp(name, b->name)) {
        put_name(c, h, SC_NAME, name);
        pane_shown(c, h->icons[k], 1);
        ib_pin_slot(c, e);
        CALL(c, F_SET_ITEM, h->ctrl[k], h->scratch + SC_NAME, (uint32_t)e, 1, 0, 0xffffffffu, (uint64_t)h->quiet);
        ib_pin_slot(c, IB_NONE);
        b->item = e;
        memcpy(b->name, name, sizeof name);
        b->row = 0, b->ammo = b->stock = 0;
        if (!is_bottle(e)) {
            const uint64_t row = CALL(c, F_ROW, h->scratch + SC_NAME);
            if (readable(row, ROW_STOCKABLE + 1)) {
                const uint64_t at = h->scratch + SC_INT;
                recomp_store32(c, at, 0xffffffffu);
                const int known = (int)(CALL(c, F_CATEGORY, at, row + ROW_CATEGORY) & 1);
                b->row = row;
                b->ammo = known && (int32_t)recomp_load32(c, at) == 1;
                b->stock = peek8(row + ROW_STOCKABLE) != 0;
            }
        }
        count = 1;
    }
    if (count) box_count(c, h, k);
    if (greyed != b->greyed) CALL(c, F_INVALID, h->ctrl[k], (uint64_t)greyed), b->greyed = greyed;
}

/* the game's right-hand group shown this frame: IsItemVisible held at its end (its frame, decided by this update) */
static int item_visible(uint64_t screen) {
    const uint64_t anim = peek64(screen + SCREEN_ITEM_VISIBLE), player = anim ? peek64(anim + 0x20) : 0;
    const uint64_t info = player ? peek64(player) : 0;
    float frame;
    uint32_t last;
    if (!info || !peek(player + 0x18, &frame, 4) || !peek(info + 0x28, &last, 4)) return 0;
    return frame == (float)(last & 0xffff);
}

static void hud_frame(Ctx *c, Hud *h, uint64_t screen) {
    const int64_t now = hos_now_ns();
    for (int k = 0; k < IB_BUTTONS; k++) input_off(c, h->button[k]);   /* (kept off: a read each, a call if it came on) */
    if (!ib_enabled()) {
        if (!h->off) {
            pane_shown(c, h->group, 0);
            pane_alpha(c, h->zr, 1.0f);
            pane_alpha(c, h->hint, 1.0f);
            set_hints(c, h, 0);
            h->t = 0.0f, h->last_ns = 0, h->off = 1;
        }
        return;
    }
    if (h->off) h->off = 0, h->quiet = 1, h->ticks = 0;
    const int shown = item_visible(screen);
    float alpha = 1.0f;
    peek(h->scale_r + PANE_ALPHA, &alpha, 4);
    if (!(alpha >= 0.0f)) alpha = 0.0f;
    if (alpha > 1.0f) alpha = 1.0f;
    h->t = hud_advance(h->t, ib_large(), h->last_ns ? now - h->last_ns : 0);
    h->last_ns = now;
    const float e = hud_ease(h->t);
    float x, y, scale, fade, hint_y, hint_scale;
    hud_place(e, &x, &y, &scale, &fade);
    hud_hint(scale, &hint_y, &hint_scale);
    pane_shown(c, h->group, shown);
    pane_alpha(c, h->group, alpha * fade);
    pane_at(c, h->group, x, y);
    pane_scale(c, h->group, scale);
    pane_at(c, h->my_hint, 0.0f, hint_y);
    pane_scale(c, h->my_hint, hint_scale);
    pane_alpha(c, h->zr, 1.0f - e);
    pane_alpha(c, h->hint, 1.0f - e);
    set_hints(c, h, 1);
    for (int k = 0; k < IB_BUTTONS; k++) pane_alpha(c, h->glyph[k], h->glyph_alpha[k] * e);
    if (h->ticks % 30 == 0) {   /* (the controls can change in the menu) */
        int pad[IB_BUTTONS];
        float px[IB_BUTTONS], py[IB_BUTTONS];
        for (int k = 0; k < IB_BUTTONS; k++) pad[k] = hos_binding(HOS_BIND_PAD, HOS_SW_A + k, 0);
        hud_diamond(pad, px, py);
        for (int k = 0; k < IB_BUTTONS; k++) {
            float rgba[4];
            pane_at(c, h->part[k], px[k], py[k]);
            if (h->coloured >> k & 1) ib_glyph_white(c, h->glyph[k], ib_glyph_colour(k, rgba) ? rgba : h->cream[k], NULL);
            pane_shown(c, h->hit[k], 0);   /* (kept hidden) */
        }
        if (h->glyphs != 0xf) set_glyphs(c, h);
    }
    if (shown) {
        const uint64_t ui = peek64(UI_STATE);
        const int greyed = ui && !(peek8(ui + 0x58c) & 0x10);
        int age = ib_age(c);
        if (age != IB_ADULT && age != IB_CHILD) age = IB_ADULT;
        for (int k = 0; k < IB_BUTTONS; k++) box_frame(c, h, k, age, (h->ticks + (unsigned)k) % 6 == 0, greyed);
        h->quiet = 0;
    }
    h->ticks++;
}

void ib_hud_tick(Ctx *c, uint64_t screen) {
    if (!c || !screen) return;
    for (int j = 0; j < 2; j++) {
        Slot *s = &slots[j];
        if (__atomic_load_n(&s->screen, __ATOMIC_ACQUIRE) != screen) continue;
        if (!take(s)) return;
        if (__atomic_load_n(&s->screen, __ATOMIC_ACQUIRE) == screen) hud_frame(c, &s->h, screen);
        give(s);
        return;
    }
}
