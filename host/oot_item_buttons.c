/* (hookshot) Item assignable buttons (the Insert menu's Controls tab, options 12 and 13): one shoulder button, the
   hotkey, is held to use the items put on A, B, X and Y, and in the game's quick-switch menu (the other shoulder
   button opens it) and on the pause menu's Items page hotkey + A B X Y puts the highlighted item on that button (the
   pause menu's pages then turn with ZL and ZR alone). host/oot_item_buttons.h has what the HUD's file
   (oot_item_buttons_hud.c) shares with this one.

   The game has one item slot, used with ZR (PouchMgr's AssignableItem, one per age). A face button's item is used by
   answering it for the slot to the player's own readers for a while and presenting ZR to the game in the face
   button's stead, so the press, the hold and the release are the game's own (a bow draws while the button is held and
   shoots when it is let go). Everything else that reads the slot (the HUD's ZR box, the menus, the pouch's
   bookkeeping) keeps seeing the saved one. The items are kept with each save, in an item_buttons.ini in its slot's
   folder that the game never reads: read when the game loads that slot, checked against the save once play starts,
   written when the game saves into a slot. An assignment changes them in memory only.

   The calls into here are nx2/oot_patches.py's (the supported build only) and one each in nn_hid.c and nn_fs.c:
   - hos_oot_ib_filter: each controller read (npad_states, the polling thread). The hotkey and the face buttons pressed
     under it are hidden from the game where the hotkey works, ZR is presented for a face button, and the presses
     become requests for the hooks below.
   - hos_oot_ib_save_file (nn_fs.c): each file the game opens. A slot's progress.sav read is a load of that slot,
     written a save into it (gmd::SaveDataMgr's thread).
   - hos_oot_ib_main, hos_oot_ib_leave: the Main sequence state's selector (f_83323ca0) and its commit to leave it
     (f_80f89630): play, where the hotkey works. There a save's items are checked once it has loaded, and a new game's
     emptied.
   - hos_oot_ib_player: Link's virtual keys (f_80594ab0), once a frame before his item selector: a use is started,
     followed and ended there, and whether its item is out (drawn, in hand: ZR is then that item's) is told.
   - hos_oot_ib_slot, hos_oot_ib_slot_set: PouchMgr::getAssignableItem (f_8019b6e0) and setAssignableItem (f_81231c00).
   - hos_oot_ib_screen: after every screen's update (Screen::calc, f_802f1380): the quick-switch menu here (assignments,
     the entries' glyphs and light blue, its key guide), the pause menu and the screen over it (assignments on the Items
     page, its slots' light blue and glyphs, the tab bar's glyphs, the key guide), the control guide (the hotkey's
     combo beside ZR while its item is out) and the title screen (a new game is play with no load since it came up),
     the HUD in oot_item_buttons_hud.c.
   - hos_oot_ib_decide, hos_oot_ib_bind: the quick-switch's decide (f_833e98f0) and the binding of its entries
     (f_833ea110).
   Without them nothing here runs, the filter passes every button through and no save's file is read or written.

   The hooks run on several of the game's threads (the sequence's, Link's worker, the UI's workers, the poll's, the
   saves'): what they share is atomic, or for the items under one lock held only to copy or change them (never over a
   file or a call into the game), and none waits for another otherwise (a busy try-lock skips that frame). */
#include "hos.h"
#include "oot_item_buttons.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

int rx_option(int id, int otherwise);
int hos_oot_is_player(Ctx *c, uint64_t actor);   /* hos_main.c */

/* the game's (lifted addresses) */
#define IB_UI_SLOT 0x84e9cfa8ULL          /* game::ui::UIModule */
#define IB_EVENT_SLOT 0x84eb4840ULL       /* engine::event::EventMgr */
#define IB_POUCH_SLOT 0x84e98e28ULL       /* PouchMgr::sInstance */
#define IB_GETTER 0x8019b6e0ULL           /* PouchMgr::getAssignableItem(mgr, w1 age, w2 isDirect) */
#define IB_LOBBY 0x805941f0ULL            /* game::banc::isDreamWorldLobby(): the Enemy Museum */
#define IB_EMPTY_TEXT 0x83f04f8cULL       /* "" */
#define IB_T_ASSIGN 0x83deee49ULL         /* "T_Assign_00" */
#define IB_CHANGE_SOUND 0x83d60dc1ULL     /* "mc_ChangeItem" */
#define IB_NAMES 0x83f0ac60ULL            /* AssignableItem's names: item i's at IB_NAMES + (s32)offsets[i + 1] */
#define IB_NAME_OFFSETS 0x83f0aeb0ULL
#define IB_LINK_VTABLE 0x84b45e18ULL
#define IB_SHORTCUT_VTABLE 0x84c0d430ULL  /* UIShortCutScreen */
#define IB_HUD_VTABLE 0x84c0b710ULL       /* UIPlayerStatusScreen */
#define IB_TITLE_VTABLE 0x84c106e8ULL     /* UITitleScreen */

#define IB_LIVE_NS 100000000LL      /* (a hook ran this recently: its context holds) */
#define IB_REQUEST_NS 200000000LL   /* (a request older than this is not acted on) */
#define IB_LOAD_TWICE_NS 1000000000LL   /* (a load opens its progress.sav again this soon) */
#define IB_READY_FRAMES 90          /* (a use gives up when the selector has not taken its item by then) */
#define IB_LEAVE_FRAMES 30          /* (a real ZR press waits at most this long for the selector to leave the item) */
#define IB_REAL_FRAMES 300          /* (and then at most this long for its release to be seen) */
#define IB_RESERVE 0x200            /* (a game function called from here starts its frames this far below the guest sp) */
#define IB_SCRATCH 0x100            /* (and the host's own records are in the part of it just below the sp) */

/* ---- the menu's rows. By number, as 11, 16 and 17: a name in gpu/vk/vk_api.h would change the shader cache's stamp */
int ib_enabled(void) { return rx_option(12, 0) != 0; }

/* ---- the filter: one call per controller read, levels in, levels out. A step over its own state and what the hooks
   published, with no guest access, so tests/test_item_buttons_filter.py checks it alone */
enum { IB_CTX_NONE, IB_CTX_PLAY, IB_CTX_MENU, IB_CTX_PAUSE };
enum { IB_ZR_NORMAL, IB_ZR_HOLD, IB_ZR_FACE, IB_ZR_REAL };
enum { IB_BIT_L = 6, IB_BIT_R = 7, IB_BIT_ZR = 9 };   /* (nn::hid's button bits, as nn_hid.c's B_*; A B X Y are 0 to 3) */
enum { IB_ZR_MIN = 3, IB_ZR_OWED_POLLS = 90 };   /* (polls: a presented ZR lasts at least; a hidden press stays owed) */

typedef struct {
    uint64_t buttons;   /* as pressed */
    int enabled;
    int hotkey;         /* IB_BIT_L or IB_BIT_R */
    int context;        /* IB_CTX_PLAY: the Main state's selector runs; IB_CTX_MENU: the quick-switch menu is open;
                           IB_CTX_PAUSE: the pause menu is open */
    int can_use;        /* play: nothing keeps the player from an item now, so a press is a use request */
    int usable;         /* menu, pause: the list (the Items page) takes an assignment now, so a press is an assign request */
    uint32_t mode;      /* the ZR mode the game side set: seq << 8 | IB_ZR_* << 4 | face button */
    int guard;          /* an item other than ZR's own is answered for ZR: a real ZR press is hidden from its first poll */
    int out;            /* face mode: the item of its face button, used with the hotkey, is out (drawn, in hand, carried) */
} IbPoll;

typedef struct {
    int on;
    uint64_t prev;          /* the last poll's buttons, as pressed: the edges are these, never the game's */
    uint64_t hidden;        /* the hotkey (and in the pause menu L and R), hidden until it is let go */
    unsigned taken;         /* face buttons pressed under the hotkey, hidden until they are let go */
    uint32_t use, assign, pause;   /* the latest requests (use, assign in the quick-switch, assign in the pause menu): a
                                      sequence number << 4 | the face button (0: none yet) */
    uint32_t zr_presses;    /* real ZR presses seen (not those on a face button's item out: they are the item's) */
    uint32_t mode;          /* the mode the report below is for */
    unsigned shown;         /* polls ZR was presented in it */
    int released;           /* a poll with ZR up has followed them */
    int face_owed;          /* face mode: polls ZR is still presented at least */
    int zr_owed;            /* polls a hidden real ZR press is still presented at least, once ZR passes again */
    int zr_wait;            /* polls the owed press has waited */
    int zr_hidden;          /* the real ZR now down was hidden at its press: it is the game's once ZR passes again */
    int zr_kept;            /* the real ZR now down was down before ZR was hidden: never the game's */
    int large;              /* the hotkey is held in play */
} IbFilter;

static int ib_mode_of(uint32_t word) { return (int)(word >> 4 & 0xf); }
static int ib_mode_button(uint32_t word) { return (int)(word & 0xf); }

/* the request after last, for a face button */
static uint32_t ib_request(uint32_t last, int button) {
    uint32_t seq = ((last >> 4) + 1) & 0x0fffffffu;
    if (!seq) seq = 1;
    return seq << 4 | (uint32_t)button;
}

static uint64_t ib_step(IbFilter *f, const IbPoll *p) {
    if (!p->enabled) {   /* off: everything as pressed, the state forgotten (the sequence numbers go on) */
        const uint32_t use = f->use, assign = f->assign, pause = f->pause, presses = f->zr_presses;
        memset(f, 0, sizeof *f);
        f->use = use, f->assign = assign, f->pause = pause, f->zr_presses = presses;
        return p->buttons;
    }
    const uint64_t down = p->buttons, pressed = down & ~f->prev, hot = 1ULL << p->hotkey, zr = 1ULL << IB_BIT_ZR;
    const int hot_down = (down & hot) != 0, ctx = p->context;
    uint64_t out = down;
    f->on = 1, f->prev = down;
    /* The hotkey is hidden in play and in the menus; one that is down when they end stays hidden until it is let go
       (the pause menu must not see a held L arrive as a new press). In the pause menu L and R both are, the same way: its
       pages turn with ZL and ZR alone (a shoulder button held as it closes is then no quick-switch press in play) */
    f->hidden &= down;
    if (ctx != IB_CTX_NONE) f->hidden |= down & hot;
    if (ctx == IB_CTX_PAUSE) f->hidden |= down & (1ULL << IB_BIT_L | 1ULL << IB_BIT_R);
    out &= ~f->hidden;
    f->large = hot_down && ctx == IB_CTX_PLAY;
    /* A face button pressed under the hotkey there is taken: hidden until it is let go, whatever the hotkey or the
       context do meanwhile. One already down when the hotkey went down is not (a dash or a dive goes on) */
    f->taken &= (unsigned)(down & 0xf);
    if (hot_down && ctx != IB_CTX_NONE)
        for (int k = 0; k < IB_BUTTONS; k++) {
            if (!(pressed >> k & 1)) continue;
            f->taken |= 1u << k;
            if (ctx == IB_CTX_PLAY && p->can_use) f->use = ib_request(f->use, k);
            else if (ctx == IB_CTX_MENU && p->usable) f->assign = ib_request(f->assign, k);
            else if (ctx == IB_CTX_PAUSE && p->usable) f->pause = ib_request(f->pause, k);
        }
    out &= ~(uint64_t)f->taken;
    /* ZR, in play by the game side's mode. normal: the real ZR. hold: nothing. face k: ZR while k is taken, and for the
       first IB_ZR_MIN polls of the mode (a tap that ended before the item was ready still arrives as a press and a
       release); while k's item is out the real ZR too, uncounted: it acts on that item as it would had ZR drawn it.
       real: the real ZR, and a hidden press for at least IB_ZR_MIN polls. Wherever the real ZR is hidden its press is
       owed and given once ZR passes again; one that was down before ZR was hidden (or when the item out went) is never
       given back. Elsewhere (an event, the pause menu: Link may not run to end a use) ZR is the game's as pressed, and
       nothing is owed to play when it comes back */
    const int zr_down = (down & zr) != 0, mode = ib_mode_of(p->mode), k = ib_mode_button(p->mode);
    const int drawn = p->out && mode == IB_ZR_FACE;
    if (p->mode != f->mode) {   /* (a mode set, or set again: its own report, and in face mode its press owed) */
        f->mode = p->mode, f->shown = 0, f->released = 0;
        f->face_owed = mode == IB_ZR_FACE && ctx == IB_CTX_PLAY ? IB_ZR_MIN : 0;
    }
    if (ctx != IB_CTX_PLAY) {
        f->face_owed = f->zr_owed = f->zr_hidden = f->zr_kept = 0;
        if (f->shown && !zr_down) f->released = 1;
        return zr_down ? out | zr : out & ~zr;
    }
    if ((pressed & zr) && !drawn) f->zr_presses++;
    const int hide = mode == IB_ZR_HOLD || (mode == IB_ZR_FACE && !drawn) || (mode == IB_ZR_NORMAL && p->guard);
    if (!zr_down) f->zr_hidden = f->zr_kept = 0;
    else if (hide && (pressed & zr)) f->zr_hidden = 1, f->zr_owed = IB_ZR_MIN, f->zr_wait = 0;
    else if (hide && !f->zr_hidden) f->zr_kept = 1;
    if (f->zr_owed && ++f->zr_wait > IB_ZR_OWED_POLLS) f->zr_owed = 0;
    int show = 0;
    if (mode == IB_ZR_FACE) {
        show = (k < IB_BUTTONS && (f->taken >> k & 1)) || f->face_owed > 0 || (drawn && zr_down && !f->zr_hidden && !f->zr_kept);
        if (f->face_owed > 0) f->face_owed--;
    } else if (!hide) {
        show = (zr_down && !f->zr_kept) || f->zr_owed > 0;
        if (show && f->zr_owed > 0) f->zr_owed--;
    }
    if (show) f->shown++, f->released = 0;
    else if (f->shown || mode == IB_ZR_REAL) f->released = 1;
    return show ? out | zr : out & ~zr;
}

/* ---- what the hooks and the filter share (atomics) */
static unsigned ib_gen;               /* the items' generation: any change of what ib_assignment answers bumps it */
static int64_t ib_main_ns;            /* the Main state's selector ran (0: it has left Main since) */
static int64_t ib_menu_ns;            /* the quick-switch screen ran open */
static int ib_usable;                 /* its list takes an assignment */
static int64_t ib_pause_ns;           /* the pause menu's screen ran open (0: it has closed, or the Minus panel is up) */
static uint64_t ib_plus;              /* that screen */
static int ib_pause_usable;           /* its Items page takes an assignment */
static uint32_t ib_use_req, ib_assign_req, ib_pause_req;   /* the filter's latest requests, and when they were made */
static int64_t ib_use_ns, ib_assign_ns, ib_pause_req_ns;
static uint32_t ib_zr_presses;        /* real ZR presses the filter saw */
static uint64_t ib_zr_report;         /* the filter on the mode it was given: mode << 32 | polls ZR was shown << 1 | released */
static uint32_t ib_zr_mode, ib_mode_seq;
#define IB_ON 0x80000000u
static uint32_t ib_answer;            /* while an item is answered for ZR: IB_ON | epoch << 16 | age << 8 | item */
static uint64_t ib_out;               /* while that item is out (hook 3): (its face button + 1) << 32 | the answer word */
static int ib_real_now = IB_NONE;     /* ZR's own item, as last read with an item answered */
static int ib_held;                   /* the hotkey is held in play */
static int ib_just_assigned;          /* an assignment in the open menu, its focus not moved since */
static int ib_glyphs;                 /* a face button's glyph was put on an entry of the menu */
static _Thread_local Ctx *ib_pin_ctx; /* ib_pin_slot's */
static _Thread_local int ib_pin_item;

static int64_t ib_load64(int64_t *p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
static uint32_t ib_load32(uint32_t *p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }

/* A guest read of what the game's pointers lead to, at the poll too: 0 outside the guest window and in its first MB
   (a null pointer's) */
static uint64_t ib_peek(uint64_t a, unsigned n) {
    uint64_t v = 0;
    if (a >= 0x100000 && hos_guest_range(a, n)) memcpy(&v, GP(a), n);
    return v;
}

/* Nothing keeps the player from an item now: no event running or asked for, no action committed this frame or the
   last, the quick-switch not forbidden this frame (the selector's own tests, plain reads) */
static int ib_play_now(void) {
    const uint64_t ev = ib_peek(IB_EVENT_SLOT, 8), ui = ib_peek(IB_UI_SLOT, 8);
    return ev && ui && !ib_peek(ev + 0x68, 8) && !(ib_peek(ev + 0xb8, 4) & 0x4000) && !(ib_peek(ui + 0x588, 1) & 2) &&
           !(ib_peek(ui + 0x58a, 2) & 6);
}

int ib_hotkey(void) { return rx_option(13, 0) ? IB_HOTKEY_R : IB_HOTKEY_L; }
static int ib_hotkey_bit(void) { return ib_hotkey() == IB_HOTKEY_R ? IB_BIT_R : IB_BIT_L; }
/* (nn_hid.c) the Switch's button held as the hotkey (nn::hid's bit, L 6 or R 7), -1 while the feature is off */
int hos_oot_ib_hotkey(void) { return ib_enabled() ? ib_hotkey_bit() : -1; }

/* nn_hid.c npad_states, each read of the controller: the buttons the game is given */
uint64_t hos_oot_ib_filter(uint64_t buttons) {
    static IbFilter f;   /* (one read at a time, as nn_hid.c's own statics) */
    static int said = -1;
    static int64_t menu_was, play_was, pause_was;
    static unsigned menu_reads, play_reads, pause_reads;   /* (reads since the hook's time last changed) */
    IbPoll p = {0};
    p.enabled = ib_enabled();
    if (!p.enabled && !f.on) return buttons;
    p.buttons = buttons;
    const int64_t now = hos_now_ns();
    if (p.enabled) {
        /* a context holds while its hook ran in the last 100 ms, or since the read before last (a long frame, a shader
           compiled meanwhile, is no gap in it) */
        const int64_t menu = ib_load64(&ib_menu_ns), play = ib_load64(&ib_main_ns), pause = ib_load64(&ib_pause_ns);
        menu_reads = menu != menu_was ? 0 : menu_reads + 1, menu_was = menu;
        play_reads = play != play_was ? 0 : play_reads + 1, play_was = play;
        pause_reads = pause != pause_was ? 0 : pause_reads + 1, pause_was = pause;
        const int in_menu = menu && (now - menu < IB_LIVE_NS || menu_reads < 2);
        const int in_play = play && (now - play < IB_LIVE_NS || play_reads < 2);
        const int in_pause = pause && (now - pause < IB_LIVE_NS || pause_reads < 2);
        p.hotkey = ib_hotkey_bit();
        /* (the pause menu over play: its screen's stamp goes as it closes; menu and play: the later, Main runs again once
           the menu has closed) */
        if (in_pause)
            p.context = IB_CTX_PAUSE, p.usable = __atomic_load_n(&ib_pause_usable, __ATOMIC_ACQUIRE);
        else if (in_menu && (!in_play || menu >= play))
            p.context = IB_CTX_MENU, p.usable = __atomic_load_n(&ib_usable, __ATOMIC_ACQUIRE);
        else if (in_play)
            p.context = IB_CTX_PLAY, p.can_use = ib_play_now();
        p.mode = ib_load32(&ib_zr_mode);
        const uint32_t a = ib_load32(&ib_answer);
        const uint64_t o = __atomic_load_n(&ib_out, __ATOMIC_ACQUIRE);
        p.guard = (a & IB_ON) && (int)(a & 0xff) != __atomic_load_n(&ib_real_now, __ATOMIC_ACQUIRE);
        p.out = (a & IB_ON) && (uint32_t)o == a && (int)(o >> 32) == ib_mode_button(p.mode) + 1;
        if (said != p.hotkey)
            said = p.hotkey, hos_log("item buttons: on (the Insert menu's Item assignable buttons); the hotkey is %s",
                                     p.hotkey == IB_BIT_R ? "R" : "L");
    } else if (said >= 0) {
        said = -1, hos_log("item buttons: off");
    }
    const uint32_t use = f.use, assign = f.assign, pause = f.pause;
    const uint64_t out = ib_step(&f, &p);
    if (f.use != use) __atomic_store_n(&ib_use_ns, now, __ATOMIC_RELAXED), __atomic_store_n(&ib_use_req, f.use, __ATOMIC_RELEASE);
    if (f.assign != assign)
        __atomic_store_n(&ib_assign_ns, now, __ATOMIC_RELAXED), __atomic_store_n(&ib_assign_req, f.assign, __ATOMIC_RELEASE);
    if (f.pause != pause)
        __atomic_store_n(&ib_pause_req_ns, now, __ATOMIC_RELAXED), __atomic_store_n(&ib_pause_req, f.pause, __ATOMIC_RELEASE);
    __atomic_store_n(&ib_zr_presses, f.zr_presses, __ATOMIC_RELEASE);
    __atomic_store_n(&ib_zr_report, (uint64_t)f.mode << 32 | (uint64_t)(f.shown < 0x7fffffffu ? f.shown : 0x7fffffffu) << 1 |
                                        (uint64_t)(f.released != 0), __ATOMIC_RELEASE);
    __atomic_store_n(&ib_held, f.large, __ATOMIC_RELEASE);
    return out;
}

int ib_large(void) { return __atomic_load_n(&ib_held, __ATOMIC_ACQUIRE) && ib_enabled(); }

/* ---- calls into the game */
uint64_t ib_guest(Ctx *c, uint64_t fn, int nx, const uint64_t *x, int ns, const float *s) {
    A64Fn f = a64_lookup(fn);
    if (!f || nx < 0 || nx > 9 || ns < 0 || ns > 8) return 0;   /* (x8 too: an indirect result's address) */
    const Ctx saved = *c;
    for (int i = 0; i < nx; i++) c->x[i] = x[i];
    for (int i = 0; i < ns; i++) {
        uint32_t bits;
        memcpy(&bits, &s[i], 4);
        c->vreg[i][0] = bits, c->vreg[i][1] = 0;
    }
    c->x[30] = 0;
    c->x[31] = (saved.x[31] - IB_RESERVE) & ~0xfULL;
    f(c);
    const uint64_t r = c->x[0];
    *c = saved;
    return r;
}

/* the host's records for its calls: IB_SCRATCH bytes below the guest sp, above the frames of the functions it calls */
static uint64_t ib_scratch(Ctx *c) { return (c->x[31] - IB_SCRATCH) & ~0xfULL; }

int ib_age(Ctx *c) {
    (void)c;
    return ib_peek(ib_peek(IB_UI_SLOT, 8) + 0x5c0, 1) & 1 ? IB_CHILD : IB_ADULT;   /* (UIModule's: the byte the game passes) */
}

static int ib_bottle(int item) { return (item >= 14 && item <= 17) || item == 50; }
static int ib_bow(int item) { return item == 30 || (item >= 46 && item <= 48); }

int ib_item_name(Ctx *c, int item, uint64_t slot) {
    const uint64_t mgr = ib_peek(IB_POUCH_SLOT, 8);
    if (!mgr || item < 0 || item >= IB_ITEMS || slot < 0x100000 || !hos_guest_range(slot, 8)) return 0;
    recomp_store64(c, slot, IB_EMPTY_TEXT);   /* (a lookup that finds nothing leaves it: the game's callers do this) */
    if (ib_bottle(item)) {   /* (getBottleContent, getBottleActorOfContent) */
        const uint64_t a[2] = {mgr, (uint32_t)item};
        const uint64_t b[3] = {mgr, slot, (uint32_t)ib_guest(c, 0x80424b80ULL, 2, a, 0, NULL)};
        ib_guest(c, 0x80a8f8b0ULL, 3, b, 0, NULL);
    } else if (ib_bow(item)) {   /* (getActorOfAssignableItem with 1: the HUD's own box's look) */
        const uint64_t a[4] = {mgr, slot, (uint32_t)item, 1};
        ib_guest(c, 0x80a945f0ULL, 4, a, 0, NULL);
    } else {   /* (getDefaultActorOfAssignableItem) */
        const uint64_t a[3] = {mgr, slot, (uint32_t)item};
        ib_guest(c, 0x805b2b20ULL, 3, a, 0, NULL);
    }
    return ib_peek(ib_peek(slot, 8), 1) != 0;
}

/* getContentNum(name, isDirect 1, isMiniGame 0) of the name at slot */
static int ib_count(Ctx *c, uint64_t mgr, uint64_t slot) {
    const uint64_t a[4] = {mgr, slot, 1, 0};
    return (int32_t)ib_guest(c, 0x805b63e0ULL, 4, a, 0, NULL);
}

int ib_item_owned(Ctx *c, int item, uint64_t slot) {
    const uint64_t mgr = ib_peek(IB_POUCH_SLOT, 8);
    if (!mgr || item < 0 || item >= IB_ITEMS) return 0;
    if (ib_bottle(item)) {   /* (hasBottle) */
        const uint64_t a[2] = {mgr, (uint32_t)item};
        return (int)(ib_guest(c, 0x80a97000ULL, 2, a, 0, NULL) & 1);
    }
    if (ib_item_name(c, item, slot) && ib_count(c, mgr, slot) > 0) return 1;
    if (!ib_bow(item) || slot < 0x100000 || !hos_guest_range(slot, 8)) return 0;
    /* (the bow and the magic arrows: by their default actor too) */
    recomp_store64(c, slot, IB_EMPTY_TEXT);
    const uint64_t a[3] = {mgr, slot, (uint32_t)item};
    ib_guest(c, 0x805b2b20ULL, 3, a, 0, NULL);
    return ib_peek(ib_peek(slot, 8), 1) && ib_count(c, mgr, slot) > 0;
}

void ib_pin_slot(Ctx *c, int item) {
    ib_pin_item = item;
    ib_pin_ctx = item == IB_NONE ? NULL : c;
}

/* ---- the file: each save's own, save:/slot_NN/item_buttons.ini beside its progress.sav, a line a button with an item,
   "<age>_<button>=<the game's name>", and no file when no button has one. The names are handed in (the game's own table
   at run time), so tests/test_item_buttons_ini.py checks this alone */
static const char *const ib_age_keys[IB_AGES] = {"adult", "child"};
static const char ib_button_keys[IB_BUTTONS + 1] = "abxy";

static int ib_same_name(const char *a, const char *b) {
    for (; *a && *b; a++, b++)
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b)) return 0;
    return !*a && !*b;
}

/* the item a name is, or IB_NONE */
static int ib_item_named(const char *const names[IB_ITEMS], const char *name) {
    for (int i = 0; i < IB_ITEMS; i++)
        if (names[i] && !strcmp(names[i], name)) return i;
    for (int i = 0; i < IB_ITEMS; i++)
        if (names[i] && ib_same_name(names[i], name)) return i;
    return IB_NONE;
}

/* The file's lines into items (IB_NONE where none): lines it does not know and names that are not items are passed
   over, as is an item already on another button of that age. The assignments read, -1 if the file is not there or
   could not be opened */
static int ib_ini_read(const char *path, const char *const names[IB_ITEMS], int items[IB_AGES][IB_BUTTONS]) {
    for (int age = 0; age < IB_AGES; age++)
        for (int k = 0; k < IB_BUTTONS; k++) items[age][k] = IB_NONE;
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    char line[256];
    int n = 0, first = 1;
    while (fgets(line, sizeof line, f)) {
        char *s = line;
        if (first && (unsigned char)s[0] == 0xEF && (unsigned char)s[1] == 0xBB && (unsigned char)s[2] == 0xBF) s += 3;
        first = 0;
        size_t len = strlen(s);
        if (len && s[len - 1] != '\n' && !feof(f)) {   /* (longer than any of ours: the rest of it passed over too) */
            int ch;
            while ((ch = fgetc(f)) != EOF && ch != '\n') {}
            continue;
        }
        while (len && isspace((unsigned char)s[len - 1])) s[--len] = 0;
        while (isspace((unsigned char)*s)) s++;
        char *eq = strchr(s, '=');
        if (!*s || *s == '#' || *s == ';' || !eq) continue;
        char *key_end = eq, *value = eq + 1;
        while (key_end > s && isspace((unsigned char)key_end[-1])) key_end--;
        while (isspace((unsigned char)*value)) value++;
        *key_end = 0;
        int age = -1, k = -1;
        for (int a = 0; a < IB_AGES; a++) {
            const size_t n_age = strlen(ib_age_keys[a]);
            if (!strncmp(s, ib_age_keys[a], n_age) && s[n_age] == '_' && s[n_age + 1] && !s[n_age + 2]) {
                const char *at = strchr(ib_button_keys, tolower((unsigned char)s[n_age + 1]));
                if (at) age = a, k = (int)(at - ib_button_keys);
            }
        }
        const int item = age >= 0 ? ib_item_named(names, value) : IB_NONE;
        if (item == IB_NONE || items[age][k] != IB_NONE) continue;
        int elsewhere = 0;
        for (int j = 0; j < IB_BUTTONS; j++) elsewhere |= items[age][j] == item;
        if (elsewhere) continue;
        items[age][k] = item, n++;
    }
    fclose(f);
    return n;
}

/* the items with a name, the ones the file keeps */
static int ib_named(const char *const names[IB_ITEMS], int items[IB_AGES][IB_BUTTONS]) {
    int n = 0;
    for (int age = 0; age < IB_AGES; age++)
        for (int k = 0; k < IB_BUTTONS; k++) n += items[age][k] >= 0 && items[age][k] < IB_ITEMS && names[items[age][k]];
    return n;
}

/* the file's text for these items, its length (-1: it does not fit) */
static int ib_ini_text(char *out, size_t cap, const char *const names[IB_ITEMS], int items[IB_AGES][IB_BUTTONS]) {
    int n = snprintf(out, cap, "# Hookshot's Item assignable buttons (the Insert menu, Controls): the item on A, B, X and Y "
                               "for each age, kept with this save. The game does not read this file.\n");
    for (int age = IB_AGES - 1; age >= 0 && n >= 0 && (size_t)n < cap; age--)   /* (the child's first: the game starts as one) */
        for (int k = 0; k < IB_BUTTONS && n >= 0 && (size_t)n < cap; k++) {
            const int item = items[age][k];
            if (item >= 0 && item < IB_ITEMS && names[item]) {
                const int m = snprintf(out + n, cap - (size_t)n, "%s_%c=%s\n", ib_age_keys[age], ib_button_keys[k], names[item]);
                n = m < 0 ? -1 : n + m;
            }
        }
    return n >= 0 && (size_t)n < cap ? n : -1;
}

/* The items to the file: written to <path>.tmp, which then takes the file's place, unless the file holds them already;
   with no item (none with a name) the file is removed instead. 1 written or removed, 0 nothing to do, -1 not done */
static int ib_ini_write(const char *path, const char *const names[IB_ITEMS], int items[IB_AGES][IB_BUTTONS]) {
    char text[2048], old[sizeof text + 1], tmp[600];
    if (!ib_named(names, items)) {
        if (!remove(path)) return 1;
        return errno == ENOENT ? 0 : -1;
    }
    const int n = ib_ini_text(text, sizeof text, names, items);
    if (n < 0 || snprintf(tmp, sizeof tmp, "%s.tmp", path) >= (int)sizeof tmp) return -1;
    FILE *f = fopen(path, "rb");
    if (f) {
        const size_t had = fread(old, 1, sizeof old, f);
        fclose(f);
        if (had == (size_t)n && !memcmp(old, text, (size_t)n)) return 0;
    }
    f = fopen(tmp, "wb");
    if (!f) return -1;
    int ok = fwrite(text, 1, (size_t)n, f) == (size_t)n;
    ok &= fclose(f) == 0;
    if (!ok || !MoveFileExA(tmp, path, MOVEFILE_REPLACE_EXISTING)) {
        remove(tmp);
        return -1;
    }
    return 1;
}

/* The game's AssignableItem names, from its own table (so no list of them is kept here): host copies, NULL for an
   item without one. 0 when the table is not what it should be (nothing is then kept in the files) */
static const char *ib_names[IB_ITEMS];
static char ib_name_text[IB_ITEMS][32];
static int ib_names_from_game(void) {
    int found = 0;
    for (int i = 0; i < IB_ITEMS; i++) {
        ib_names[i] = NULL;
        const int32_t at = (int32_t)ib_peek(IB_NAME_OFFSETS + 4ull * (unsigned)(i + 1), 4);
        if (at < 0) continue;
        if (at > 0x1000) return 0;
        char *t = ib_name_text[i];
        size_t len = 0;
        for (; len < sizeof ib_name_text[i]; len++) {
            t[len] = (char)ib_peek(IB_NAMES + (uint64_t)at + len, 1);
            if (!t[len]) break;
            if (!isalnum((unsigned char)t[len]) && t[len] != '_') return 0;
        }
        if (!len || len == sizeof ib_name_text[i]) return 0;
        ib_names[i] = t, found++;
    }
    return found;
}

/* The names, read the first time they are wanted (they need the game's image): 1 when they are there */
static int ib_names_ready(void) {
    static SRWLOCK once = SRWLOCK_INIT;
    static int state;   /* (0 not read yet, 1 found, -1 not found) */
    int s = __atomic_load_n(&state, __ATOMIC_ACQUIRE), read = 0;
    if (!s) {
        AcquireSRWLockExclusive(&once);
        if (!(s = __atomic_load_n(&state, __ATOMIC_ACQUIRE)))
            s = ib_names_from_game() ? 1 : -1, read = 1, __atomic_store_n(&state, s, __ATOMIC_RELEASE);
        ReleaseSRWLockExclusive(&once);
    }
    if (read && s < 0) hos_log("item buttons: the game's item names were not found: the items on A, B, X and Y are not kept");
    return s > 0;
}

static const char *ib_name(int item) {
    return item >= 0 && item < IB_ITEMS && ib_names_ready() && ib_names[item] ? ib_names[item] : "an item";
}

/* ---- the saves. The game reads a slot's progress.sav to load it and writes it to save into it, on its thread
   gmd::SaveDataMgr (nn_fs.c tells each open: hos_oot_ib_save_file). A load reads that slot's file into the items, a save
   writes them to the slot it goes to, which is often not the one loaded (an autosave takes the oldest autosave's slot, a
   save from the menu the one slot kept for those, whichever was loaded). An assignment changes the items in memory
   only, so a game left without saving loses it, as it loses a change of the ZR item. A load's items are checked against
   the save once play runs (hook 1), each age while the game is at it (a slot's actor, and so the test, follows the
   age): until then ib_assignment answers none for that age, and a save writes them as they were read. A new game (play
   with no load since the title came up) starts with none. These three read no guest memory:
   tests/test_item_buttons_saves.py checks them alone */

/* the slot of a guest path that is exactly save:/slot_NN/progress.sav, -1 for any other */
static int ib_slot_of(const char *guest) {
    static const char head[] = "save:/slot_", tail[] = "/progress.sav";
    if (strncmp(guest, head, sizeof head - 1)) return -1;
    const char *d = guest + sizeof head - 1;
    if (d[0] < '0' || d[0] > '9' || d[1] < '0' || d[1] > '9' || strcmp(d + 2, tail)) return -1;
    return (d[0] - '0') * 10 + (d[1] - '0');
}

/* An age's items kept where valid (bits by item) has them, the others emptied: the buttons emptied, as bits */
static unsigned ib_keep_valid(int items[IB_BUTTONS], uint64_t valid) {
    unsigned emptied = 0;
    for (int k = 0; k < IB_BUTTONS; k++)
        if (items[k] != IB_NONE && (items[k] < 0 || items[k] >= IB_ITEMS || !(valid >> items[k] & 1)))
            items[k] = IB_NONE, emptied |= 1u << k;
    return emptied;
}

/* Play runs (hook 1): a new game when the title has come up since it last ran (title) and nothing was loaded since
   (load_ns before title_ns; 0 for no load yet) */
static int ib_new_game(int title, int64_t title_ns, int64_t load_ns) { return title && load_ns < title_ns; }

static SRWLOCK ib_lock = SRWLOCK_INIT;   /* the items, the load generation and the ages checked change under it */
static int ib_items[IB_AGES][IB_BUTTONS] = {{IB_NONE, IB_NONE, IB_NONE, IB_NONE}, {IB_NONE, IB_NONE, IB_NONE, IB_NONE}};
static unsigned ib_load_gen;             /* each load and each new game: its items */
static unsigned ib_checked[IB_AGES];     /* the load generation each age's items were checked for */
static int64_t ib_load_ns;               /* the last load */
static int ib_title_open;                /* the title screen has come up since play last ran */
static int64_t ib_title_ns, ib_title_last_ns;   /* when it came up; its last frame */
static int ib_hooked;                    /* hook 7 has run: the build has the hooks */

/* slot NN's file on the host, through the save mount (with /: fopen on Linux takes no \), 0 when there is none */
static int ib_slot_path(int slot, char *out, size_t cap) {
    char guest[48];
    snprintf(guest, sizeof guest, "save:/slot_%02d/item_buttons.ini", slot);
    if (!hos_fs_host_path(guest, out, cap)) return 0;
    for (char *p = out; *p; p++)
        if (*p == '\\') *p = '/';
    return 1;
}

/* A load of slot NN: its file's items, none where it has none (each load opens progress.sav twice: said once) */
static void ib_load_slot(int slot, const char *path) {
    static int said_slot = -1;   /* (the saves' thread alone) */
    static int64_t said_ns;
    int items[IB_AGES][IB_BUTTONS];
    const int away = hos_vcore_away();
    const int n = ib_ini_read(path, ib_names, items);
    const int missing = n < 0 && errno == ENOENT;
    if (away) hos_vcore_back();
    const int64_t now = hos_now_ns();
    __atomic_store_n(&ib_load_ns, now, __ATOMIC_RELEASE);
    AcquireSRWLockExclusive(&ib_lock);
    memcpy(ib_items, items, sizeof ib_items);
    __atomic_add_fetch(&ib_load_gen, 1, __ATOMIC_ACQ_REL);
    ReleaseSRWLockExclusive(&ib_lock);
    __atomic_add_fetch(&ib_gen, 1, __ATOMIC_RELEASE);
    if (slot == said_slot && now - said_ns < IB_LOAD_TWICE_NS) return;
    said_slot = slot, said_ns = now;
    if (n >= 0)
        hos_log("item buttons: slot_%02d loaded: %d item%s on A, B, X and Y, checked once play runs", slot, n, n == 1 ? "" : "s");
    else if (missing)
        hos_log("item buttons: slot_%02d loaded: no item_buttons.ini, no items", slot);
    else
        hos_log("item buttons: slot_%02d loaded: %s could not be read, no items", slot, path);
}

/* A save into slot NN: the items to its file as they are (an age not checked yet keeps what was read), the file removed
   when there are none */
static void ib_save_slot(int slot, const char *path) {
    int items[IB_AGES][IB_BUTTONS];
    AcquireSRWLockShared(&ib_lock);
    memcpy(items, ib_items, sizeof items);
    ReleaseSRWLockShared(&ib_lock);
    const int n = ib_named(ib_names, items);
    const int away = hos_vcore_away();
    const int r = ib_ini_write(path, ib_names, items);
    if (away) hos_vcore_back();
    if (r < 0)
        hos_log("item buttons: slot_%02d saved, but %s could not be %s", slot, path, n ? "written" : "removed");
    else if (n)
        hos_log("item buttons: slot_%02d saved: %d item%s on A, B, X and Y%s", slot, n, n == 1 ? "" : "s",
                r ? "" : " (the file had them already)");
    else
        hos_log("item buttons: slot_%02d saved: no items, %s", slot, r ? "its item_buttons.ini removed" : "no item_buttons.ini");
}

static void ib_new_game_seen(void);

/* nn_fs.c's OpenFile, each file the game has opened (guest: its path; write: for writing). A slot's progress.sav read is
   a load of that slot, written a save into it. With the feature off too: a save then carries what was loaded. A save
   before a new game's first tick of play (the autosave New Game starts with) takes none of the last save's items */
void hos_oot_ib_save_file(const char *guest, int write) {
    const int slot = ib_slot_of(guest);
    if (slot < 0 || !__atomic_load_n(&ib_hooked, __ATOMIC_ACQUIRE) || !ib_names_ready()) return;
    char path[600];
    if (!ib_slot_path(slot, path, sizeof path)) {
        hos_log("item buttons: slot_%02d has no folder on the host: its items are not kept", slot);
        return;
    }
    if (write) ib_new_game_seen(), ib_save_slot(slot, path);
    else ib_load_slot(slot, path);
}

/* (an age's items are answered once they are checked against the save loaded) */
int ib_assignment(int age, int button) {
    if (age < 0 || age >= IB_AGES || button < 0 || button >= IB_BUTTONS) return IB_NONE;
    AcquireSRWLockShared(&ib_lock);
    const int checked = __atomic_load_n(&ib_checked[age], __ATOMIC_RELAXED) == __atomic_load_n(&ib_load_gen, __ATOMIC_RELAXED);
    const int item = checked ? ib_items[age][button] : IB_NONE;
    ReleaseSRWLockShared(&ib_lock);
    return item;
}

unsigned ib_generation(void) { return __atomic_load_n(&ib_gen, __ATOMIC_ACQUIRE); }

/* the face button an item is on for an age, or -1 */
static int ib_button_of(int age, int item) {
    if (item < 0) return -1;
    for (int k = 0; k < IB_BUTTONS; k++)
        if (ib_assignment(age, k) == item) return k;
    return -1;
}

/* ---- the ZR mode the filter is given, and the item answered for ZR */
static uint32_t ib_set_mode(int mode, int button) {
    const uint32_t seq = __atomic_add_fetch(&ib_mode_seq, 1, __ATOMIC_RELAXED) & 0xffffffu;
    const uint32_t word = seq << 8 | (uint32_t)mode << 4 | (uint32_t)button;
    __atomic_store_n(&ib_zr_mode, word, __ATOMIC_RELEASE);
    return word;
}

/* No item answered for ZR any more (any thread: a menu's choice, the quick-switch opening); hos_oot_ib_player sees it */
static void ib_drop(void) {
    uint32_t a = ib_load32(&ib_answer);
    while (a & IB_ON)
        if (__atomic_compare_exchange_n(&ib_answer, &a, a & ~IB_ON, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            ib_set_mode(IB_ZR_NORMAL, 0);
            return;
        }
}

/* ---- hooks 1 and 2: play */

/* the game's (lifted): the pouch's calls the quick-switch makes its list with (buildShortCutList) */
#define IB_POUCH_ARRAY 0x80a8f690ULL     /* PouchMgr::getPouchArray(mgr, w1 kind): 0 the ItemArray */
#define IB_ARRAY_COUNT 0x80021a20ULL     /* an array's count, its parents' entries with it */
#define IB_SLOT_ACTOR 0x80a8ef20ULL      /* PouchMgr::getCurrentActorOfSlot(mgr, w1 kind, w2 slot, x3 s32 *bottle, x4 u32 *entry) */
#define IB_ACTOR_SHORT 0x8002a4c0ULL     /* PouchItemParam::getActorShort(param): a char ** */
#define IB_ITEM_OF_ACTOR 0x833c6860ULL   /* PouchMgr::getAssignableItemOfActor(mgr, x1 char **): -1 none */
#define IB_LISTABLE 0x805b6af0ULL        /* PouchMgr::canListInShortCut(mgr, x1 char **, w2 bottle, x3 param, w4 age) */
#define IB_IS_GET 0x801a1160ULL          /* PouchMgr::isGet(x0 char **): its IsGet flag */

/* The items the quick-switch would list now for the age the game is at (bits by item): each of the pouch's ItemArray
   slots by the actor it shows, which the age picks, through the game's own test (owned and usable at that age: a bomb
   bag with no bombs left is, a bottle by the bottle alone, the ocarina, the masks and the boots never, having no such
   slot). A bottle slot's item is its own enum (the bottle rows all say BottleA). With the Items page's one difference:
   a child's Magic Beans on their IsGet alone (the quick-switch wants one left, or an unnamed counter of the game's at 1
   to 9). Reads only, no lock. 0 when the walk cannot be made now (no pouch or no UI yet, a count that is no array's) */
static int ib_valid_items(Ctx *c, int age, uint64_t *valid) {
    static const uint64_t calls[] = {IB_POUCH_ARRAY, IB_ARRAY_COUNT, IB_SLOT_ACTOR, IB_ACTOR_SHORT, IB_ITEM_OF_ACTOR,
                                     IB_LISTABLE, IB_IS_GET};
    for (size_t i = 0; i < sizeof calls / sizeof *calls; i++)
        if (!a64_lookup(calls[i])) return 0;
    const uint64_t mgr = ib_peek(IB_POUCH_SLOT, 8), scr = ib_scratch(c);
    if (!mgr || !ib_peek(IB_UI_SLOT, 8)) return 0;
    const uint64_t kind[2] = {mgr, 0};
    const uint64_t array = ib_guest(c, IB_POUCH_ARRAY, 2, kind, 0, NULL);
    const int n = array ? (int32_t)ib_guest(c, IB_ARRAY_COUNT, 1, &array, 0, NULL) : 0;
    if (n < 1 || n > 64) return 0;
    const int bean = ib_item_named(ib_names, "MagicBean");
    uint64_t v = 0;
    for (int i = 0; i < n; i++) {
        recomp_store32_sp(c, scr, 0xffffffffu), recomp_store32_sp(c, scr + 4, 0);   /* (the bottle's enum: -1, the game's start) */
        const uint64_t at[5] = {mgr, 0, (uint32_t)i, scr, scr + 4};
        const uint64_t actor = ib_guest(c, IB_SLOT_ACTOR, 5, at, 0, NULL);
        const uint64_t name = actor ? ib_guest(c, IB_ACTOR_SHORT, 1, &actor, 0, NULL) : 0;
        if (!name || !ib_peek(ib_peek(name, 8), 1)) continue;   /* (an empty slot) */
        const int bottle = (int32_t)ib_peek(scr, 4);
        const uint64_t of[2] = {mgr, name};
        const int item = ib_bottle(bottle) ? bottle : (int32_t)ib_guest(c, IB_ITEM_OF_ACTOR, 2, of, 0, NULL);
        if (item < 0 || item >= IB_ITEMS) continue;
        const uint64_t list[5] = {mgr, name, (uint32_t)bottle, actor, (uint64_t)age};
        if ((ib_guest(c, IB_LISTABLE, 5, list, 0, NULL) & 1) ||
            (item == bean && age == IB_CHILD && (ib_guest(c, IB_IS_GET, 1, &name, 0, NULL) & 1)))
            v |= 1ULL << item;
    }
    *valid = v;
    return 1;
}

/* "Bow on A, Bomb on X" for the buttons in bits, "none" for none */
static const char *ib_list(char *out, size_t cap, const int items[IB_BUTTONS], unsigned bits) {
    size_t n = 0;
    out[0] = 0;
    for (int k = 0; k < IB_BUTTONS && n < cap; k++)
        if (bits >> k & 1) {
            const int m = snprintf(out + n, cap - n, "%s%s on %c", n ? ", " : "", ib_name(items[k]), "ABXY"[k]);
            n = m < 0 ? cap : n + (size_t)m;
        }
    return n ? out : "none";
}

/* The items of the age the game is at, once after each load: those the save does not hold for that age, or that the
   file names wrongly, emptied. Not while the title is up. A walk that cannot be made is tried again next tick (nothing
   emptied); one a load came during is dropped (that load's check comes next) */
static void ib_check(Ctx *c) {
    const int age = ib_age(c);
    const unsigned gen = __atomic_load_n(&ib_load_gen, __ATOMIC_ACQUIRE);
    if (__atomic_load_n(&ib_checked[age], __ATOMIC_ACQUIRE) == gen || !ib_names_ready() ||
        hos_now_ns() - __atomic_load_n(&ib_title_last_ns, __ATOMIC_ACQUIRE) < IB_LIVE_NS)
        return;
    uint64_t valid;
    if (!ib_valid_items(c, age, &valid)) return;
    int was[IB_BUTTONS], done = 0;
    unsigned emptied = 0, kept = 0;
    AcquireSRWLockExclusive(&ib_lock);
    if (__atomic_load_n(&ib_load_gen, __ATOMIC_ACQUIRE) == gen) {
        memcpy(was, ib_items[age], sizeof was);
        emptied = ib_keep_valid(ib_items[age], valid);
        __atomic_store_n(&ib_checked[age], gen, __ATOMIC_RELEASE);
        done = 1;
    }
    ReleaseSRWLockExclusive(&ib_lock);
    if (!done) return;
    __atomic_add_fetch(&ib_gen, 1, __ATOMIC_RELEASE);
    for (int k = 0; k < IB_BUTTONS; k++) kept |= (unsigned)(was[k] != IB_NONE && !(emptied >> k & 1)) << k;
    char kept_text[200], emptied_text[200];
    hos_log("item buttons: the %s's items checked against the save: kept %s; emptied %s", ib_age_keys[age],
            ib_list(kept_text, sizeof kept_text, was, kept), ib_list(emptied_text, sizeof emptied_text, was, emptied));
}

/* a new game: no items, both ages as checked */
static void ib_new_game_now(void) {
    AcquireSRWLockExclusive(&ib_lock);
    for (int age = 0; age < IB_AGES; age++)
        for (int k = 0; k < IB_BUTTONS; k++) ib_items[age][k] = IB_NONE;
    const unsigned gen = __atomic_add_fetch(&ib_load_gen, 1, __ATOMIC_ACQ_REL);
    for (int age = 0; age < IB_AGES; age++) __atomic_store_n(&ib_checked[age], gen, __ATOMIC_RELEASE);
    ReleaseSRWLockExclusive(&ib_lock);
    __atomic_add_fetch(&ib_gen, 1, __ATOMIC_RELEASE);
    hos_log("item buttons: a new game (no save loaded since the title): no items on A, B, X and Y");
}

/* The title has come up since play last ran and nothing was loaded since: a new game, its items emptied. Asked at each
   tick of play and before each save (whichever comes first after the title takes it) */
static void ib_new_game_seen(void) {
    const int title = __atomic_load_n(&ib_title_open, __ATOMIC_ACQUIRE) && __atomic_exchange_n(&ib_title_open, 0, __ATOMIC_ACQ_REL);
    if (ib_new_game(title, __atomic_load_n(&ib_title_ns, __ATOMIC_ACQUIRE), __atomic_load_n(&ib_load_ns, __ATOMIC_ACQUIRE)))
        ib_new_game_now();
}

/* Each tick of play. A new game is seen with the feature off too (its first save must not take the last save's items);
   with it on, the filter's context is stamped and the items checked */
void hos_oot_ib_main(Ctx *c, uint64_t selector) {
    (void)selector;
    ib_new_game_seen();
    if (!ib_enabled()) return;
    __atomic_store_n(&ib_main_ns, hos_now_ns(), __ATOMIC_RELEASE);
    ib_check(c);
}

/* The selector leaves Main (link: the state it goes to). For the quick-switch the item answered for ZR goes now,
   before the menu's onOpenStart reads the slot; for anything else (an event, a pause menu) a use ends by its own
   rules: a bottle's drink is an event and still reads the slot */
void hos_oot_ib_leave(Ctx *c, uint64_t selector, uint64_t link) {
    (void)c;
    __atomic_store_n(&ib_main_ns, 0, __ATOMIC_RELEASE);
    if (!selector || (uint8_t)link != (uint8_t)ib_peek(selector + 0x25, 1)) return;   /* (the commit takes w1's low byte) */
    if (ib_enabled()) __atomic_store_n(&ib_menu_ns, hos_now_ns(), __ATOMIC_RELEASE);   /* (the hotkey stays hidden meanwhile) */
    __atomic_store_n(&ib_just_assigned, 0, __ATOMIC_RELEASE);
    ib_drop();
}

/* ---- hook 4: the slot's readers. The player's (the selector, the bottle nodes, the ammunition of a shot) are
   answered the item in use; every other caller, known or not, gets the saved slot. ItemBtn::setItem is answered the
   pinned item for its own call (ib_pin_slot) */
static int ib_answered(uint64_t lr) {
    switch (lr) {
    case 0x83035134ULL:   /* ItemSelector::syncSelectedItem */
    case 0x828e2ce0ULL:   /* OneShotConsumeDrinkFromSelectedBottle */
    case 0x8293650cULL:   /* OneShotPushToEmptyBottle */
    case 0x82a3d97cULL:   /* QueryGetSelectedAssignableItem */
    case 0x833c784cULL:   /* PouchMgr::getShootableActorOfAssignableItem */
    case 0x8060a5e0ULL:   /* the player's own shooter lookups */
    case 0x80c23ab4ULL:
        return 1;
    }
    return 0;
}

int hos_oot_ib_slot(Ctx *c) {
    const uint32_t a = __atomic_load_n(&ib_answer, __ATOMIC_ACQUIRE);
    Ctx *const pin = ib_pin_ctx;
    if (!(a & IB_ON) && !pin) return 0;
    const uint64_t lr = c->x[30];
    if (pin == c && lr == 0x80a96020ULL) {   /* (ItemBtn::setItem) */
        c->x[0] = (uint32_t)ib_pin_item;
        return 1;
    }
    if (!(a & IB_ON) || (uint32_t)c->x[1] != (a >> 8 & 0xff) || !ib_answered(lr)) return 0;
    c->x[0] = a & 0xff;
    return 1;
}

/* hook 5: a menu's choice (the pause menu's, the quick-switch's: reasons 0 and 1) ends a use; the call goes on */
void hos_oot_ib_slot_set(Ctx *c) {
    if ((uint32_t)c->x[3] <= 1) ib_drop();
}

/* ---- hook 3: a use, on Link's frame (his item selector runs after it). A use request starts it: the item is
   answered for ZR and the filter holds ZR back until the selector has taken it, then presents ZR while the face button
   is held. While the item is out (drawn, in hand, a bomb carried) the real ZR is its own, as if ZR had drawn it: the
   filter presents it too and it ends nothing. The use stops once the button is up and the game has seen ZR let go, no
   buffered press waits, nothing is in his hands or carried from it, no event has him and his actions are no item's, two
   frames running. A real ZR press with the item not out ends it at once: hidden until the selector has left the item,
   then given to the game */
enum { IB_IDLE, IB_WAIT, IB_ACTIVE, IB_END_HOLD, IB_END_REAL };
static struct {
    int phase, item, button, age, frames, calm;
    int bomb;                 /* a bomb of the use lifted (1), then carried (2) */
    unsigned epoch;
    uint32_t answer, mode;    /* the answer word set, the mode word last set */
    uint32_t use_seen, press_seen;
} ib_use;

static int ib_verb(uint64_t action) {
    if (!action) return -1;
    const int v = (int32_t)ib_peek(action + 0x28, 4);
    return v == 0x11a ? (int32_t)ib_peek(action + 0x4c, 4) : v;
}

/* Link's main and sub action verbs (-1: none) */
static void ib_verbs(uint64_t actor, int *verb, int *sub_verb) {
    const uint64_t actions = ib_peek(ib_peek(actor + 0x270, 8) + 0x188, 8);
    *verb = ib_verb(ib_peek(actions + 0x1c0, 8)), *sub_verb = ib_verb(ib_peek(actions + 0x1c8, 8));
}

/* Link's main action or sub action is an item's (UseItem, UseEmptyBottle, ShowItem, RangedAttack, HookshotShoot, ...;
   Bow, Hookshot, HoldItem) */
static int ib_item_action(int verb, int sub_verb) {
    static const int verbs[] = {0xee, 0x102, 0xdc, 0x79, 5, 0xf3, 0xf5, 0xf7, 0x3d}, sub_verbs[] = {0x3b, 6, 0xed};
    for (size_t i = 0; i < sizeof verbs / sizeof *verbs; i++)
        if (verbs[i] == verb) return 1;
    for (size_t i = 0; i < sizeof sub_verbs / sizeof *sub_verbs; i++)
        if (sub_verbs[i] == sub_verb) return 1;
    return 0;
}

/* The item in Link's hands, by the reads the control guide picks its hints by: the Bow sub action (the bow, the arrows,
   the slingshot), the Hookshot sub action or its flight (HookshotShoot; not the hookshot in use alone, which only a
   put-away clears), HoldItem's or the boomerang in use, the Deku Stick or the Hammer in use. A bomb is ib_bomb's. These
   two read no guest memory: tests/test_item_buttons_filter.py checks them alone */
static int ib_in_hand(int item, int verb, int sub_verb, int using_item) {
    if (item == 4 || ib_bow(item)) return sub_verb == 0x3b;
    if (item == 5 || item == 6) return sub_verb == 6 || verb == 5;
    if (item == 3) return sub_verb == 0xed || using_item == 3;
    return (item == 0 || item == 7) && using_item == item;
}

/* A bomb of the use (Bomb, Bombchu), by the lift (sub verb Lift; its state 2 or 3: something carried): latched (1) when
   the lift takes it in hand (the lift starts only for the selected bomb), carried (2) while the lift holds it, let go
   (0) once it is thrown or set down. It leaves the pouch on its way into the hands, so the last one is still the use's */
static int ib_bomb(int bomb, int item, int sub_verb, int using_item, uint32_t lift) {
    if ((item != 2 && item != 9) || sub_verb != 0x2b) return 0;
    if (lift == 2 || lift == 3) return 2;
    return bomb != 2 && (bomb || using_item == item);
}

/* Link's actor when comp is his player component, else 0 (as hos_main.c's hos_oot_lift_player finds him) */
static uint64_t ib_link(Ctx *c, uint64_t comp) {
    const uint64_t actor = ib_peek(comp + 0x18, 8);
    if (!actor || ib_peek(actor, 8) != IB_LINK_VTABLE) return 0;
    const uint64_t comps = ib_peek(actor + 0x270, 8);
    if (!comps || ib_peek(comps + 0x358, 8) != comp) return 0;
    const uint64_t movement = ib_peek(comps + 800, 8);
    if (movement < HOS_HEAP_BASE + 0x1d50 || ib_peek(movement + 24, 8) != actor) return 0;
    return hos_oot_is_player(c, movement - 0x1d50) ? actor : 0;
}

static int ib_event_has(uint64_t actor) {
    const uint64_t comps = ib_peek(actor + 0x270, 8), user = ib_peek(comps + 0x88, 8), e = ib_peek(user + 0x18, 8);
    for (int i = 0; e && i < 4; i++)
        if (ib_peek(e + 0x10 + 0x38 * i, 8) && (ib_peek(e + 0x18 + 0x38 * i, 1) & 1)) return 1;
    return 0;
}

/* ZR's own item for an age (the getter called from here: its hook lets an unknown caller through) */
static int ib_real(Ctx *c, int age) {
    const uint64_t mgr = ib_peek(IB_POUCH_SLOT, 8);
    if (!mgr || !a64_lookup(IB_GETTER)) return IB_NONE;
    const uint64_t a[3] = {mgr, (uint64_t)age, 0};
    const int item = (int32_t)ib_guest(c, IB_GETTER, 3, a, 0, NULL);
    __atomic_store_n(&ib_real_now, item, __ATOMIC_RELEASE);
    return item;
}

/* the mode for the use in hand: normal at once if another thread has dropped it meanwhile */
static void ib_use_mode(int mode, int button) {
    ib_use.mode = ib_set_mode(mode, button);
    if (ib_load32(&ib_answer) != ib_use.answer) ib_use.mode = ib_set_mode(IB_ZR_NORMAL, 0);
}

static void ib_finish(void) {
    uint32_t a = ib_use.answer;
    if (ib_use.phase == IB_WAIT || ib_use.phase == IB_ACTIVE)
        __atomic_compare_exchange_n(&ib_answer, &a, a & ~IB_ON, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    ib_use.mode = ib_set_mode(IB_ZR_NORMAL, 0);
    ib_use.phase = IB_IDLE, ib_use.bomb = 0;
    __atomic_store_n(&ib_out, 0, __ATOMIC_RELEASE);
}

/* A real ZR press: the slot's own item at once. Its press waits, hidden, until the selector has left the item in use */
static void ib_end_now(Ctx *c) {
    uint32_t a = ib_use.answer;
    __atomic_compare_exchange_n(&ib_answer, &a, a & ~IB_ON, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    ib_use.bomb = 0;
    if (ib_real(c, ib_use.age) == ib_use.item) {
        ib_use.mode = ib_set_mode(IB_ZR_NORMAL, 0), ib_use.phase = IB_IDLE;
        return;
    }
    ib_use.mode = ib_set_mode(IB_ZR_HOLD, 0), ib_use.phase = IB_END_HOLD, ib_use.frames = 0;
}

/* nothing keeps the player from using an item now: play, the selector's tests, no item-lending mini game, not the
   Enemy Museum's lobby, his selector following the slot */
static int ib_can_use(Ctx *c, int mini, int flags) {
    if (!ib_load64(&ib_main_ns) || !ib_play_now() || mini != -1 || (flags & 9)) return 0;
    if (!(ib_peek(ib_peek(IB_UI_SLOT, 8) + 0x58c, 1) & 8) || !a64_lookup(IB_LOBBY)) return 0;
    return !(ib_guest(c, IB_LOBBY, 0, NULL, 0, NULL) & 1);
}

static void ib_start(Ctx *c, int button, int age, int selected, int mini, int flags) {
    const int item = ib_assignment(age, button);
    if (item == IB_NONE || !ib_can_use(c, mini, flags)) return;
    if ((ib_use.phase == IB_WAIT || ib_use.phase == IB_ACTIVE) && ib_use.item == item && ib_use.age == age) {
        ib_use.button = button;   /* (pressed again: a new press for the filter to present) */
        if (ib_use.phase == IB_ACTIVE) ib_use_mode(IB_ZR_FACE, button), ib_use.calm = 0;
        return;
    }
    if (!ib_item_owned(c, item, ib_scratch(c))) return;
    ib_real(c, age);   /* (before the answer: the filter compares the two) */
    ib_use.epoch = (ib_use.epoch + 1) & 0x7fff;
    ib_use.answer = IB_ON | ib_use.epoch << 16 | (uint32_t)age << 8 | (uint32_t)item;
    __atomic_store_n(&ib_answer, ib_use.answer, __ATOMIC_RELEASE);
    ib_use.item = item, ib_use.button = button, ib_use.age = age, ib_use.frames = 0, ib_use.calm = 0, ib_use.bomb = 0;
    if (selected == item) ib_use.phase = IB_ACTIVE, ib_use_mode(IB_ZR_FACE, button);   /* (the selector has it already) */
    else ib_use.phase = IB_WAIT, ib_use_mode(IB_ZR_HOLD, 0);
}

static int ib_released(void) {
    const uint64_t r = __atomic_load_n(&ib_zr_report, __ATOMIC_ACQUIRE);
    return (uint32_t)(r >> 32) == ib_use.mode && (r & 1);
}

static void ib_player_locked(Ctx *c, uint64_t comp, uint64_t actor) {
    const uint32_t use = ib_load32(&ib_use_req), press = ib_load32(&ib_zr_presses);
    const uint32_t new_use = use != ib_use.use_seen ? use : 0, new_press = press != ib_use.press_seen;
    ib_use.use_seen = use, ib_use.press_seen = press;
    const int in_use = ib_use.phase == IB_WAIT || ib_use.phase == IB_ACTIVE;
    if (!ib_enabled()) {
        if (ib_use.phase != IB_IDLE) ib_finish();
        return;
    }
    const int flags = (int)ib_peek(comp + 0x7c1, 1), selected = (int32_t)ib_peek(comp + 0x7d0, 4);
    const int using_item = (int32_t)ib_peek(comp + 0x7d8, 4), mini = (int32_t)ib_peek(comp + 0x7dc, 4);
    const uint32_t timer_bits = (uint32_t)ib_peek(comp + 0x1604, 4);
    float timer;
    memcpy(&timer, &timer_bits, 4);
    const int age = ib_age(c), event = ib_event_has(actor);
    int verb, sub_verb;
    ib_verbs(actor, &verb, &sub_verb);
    /* (the lift's state: 2 or 3 something carried) */
    const uint32_t lift = (uint32_t)ib_peek(ib_peek(ib_peek(actor + 0x270, 8) + 0x2c8, 8) + 0x2b0, 4);
    if (in_use && ib_load32(&ib_answer) != ib_use.answer) ib_use.phase = IB_IDLE;   /* (dropped elsewhere: the mode is set) */
    else if (in_use && age != ib_use.age) ib_finish();
    if (new_press && (ib_use.phase == IB_WAIT || ib_use.phase == IB_ACTIVE)) ib_end_now(c);
    switch (ib_use.phase) {
    case IB_WAIT:
    case IB_ACTIVE: {
        /* (a bomb of the use is kept on while lifted and carried, so ZR throws it as it would had ZR lifted it; an item
           out is the use's though none is left in the pouch) */
        if (ib_use.phase == IB_ACTIVE) ib_use.bomb = ib_bomb(ib_use.bomb, ib_use.item, sub_verb, using_item, lift);
        const int held = ib_use.phase == IB_ACTIVE && (ib_use.bomb || ib_in_hand(ib_use.item, verb, sub_verb, using_item));
        if (!held && !ib_item_owned(c, ib_use.item, ib_scratch(c))) {
            ib_finish();
            break;
        }
        ib_real(c, age);
        if (ib_use.phase == IB_WAIT) {   /* (ready: the selector has taken the item) */
            if (selected == ib_use.item) ib_use.phase = IB_ACTIVE, ib_use.calm = 0, ib_use_mode(IB_ZR_FACE, ib_use.button);
            else if (++ib_use.frames > IB_READY_FRAMES) ib_finish();
            break;
        }
        if (ib_released() && !(timer > 0) && using_item == -1 && !event && !ib_item_action(verb, sub_verb) && !ib_use.bomb)
            ib_use.calm++;
        else
            ib_use.calm = 0;
        if (ib_use.calm >= 2) ib_finish();
        break;
    }
    case IB_END_HOLD:
        if (selected != ib_use.item || ++ib_use.frames >= IB_LEAVE_FRAMES)
            ib_use.mode = ib_set_mode(IB_ZR_REAL, 0), ib_use.phase = IB_END_REAL, ib_use.frames = 0;
        break;
    case IB_END_REAL:
        if (ib_released() || ++ib_use.frames > IB_REAL_FRAMES) ib_use.mode = ib_set_mode(IB_ZR_NORMAL, 0), ib_use.phase = IB_IDLE;
        break;
    }
    /* (a request made while a real ZR press is being given back is passed over) */
    if (new_use && ib_use.phase != IB_END_HOLD && ib_use.phase != IB_END_REAL &&
        hos_now_ns() - ib_load64(&ib_use_ns) < IB_REQUEST_NS && (int)(new_use & 0xf) < IB_BUTTONS)
        ib_start(c, (int)(new_use & 0xf), age, selected, mini, flags);
    /* the use's item out: the filter gives it the real ZR, the control guide shows its face button's combo beside ZR */
    const int out = ib_use.phase == IB_ACTIVE && !event && (ib_use.bomb || ib_in_hand(ib_use.item, verb, sub_verb, using_item));
    __atomic_store_n(&ib_out, out ? (uint64_t)(ib_use.button + 1) << 32 | ib_use.answer : 0, __ATOMIC_RELEASE);
}

void hos_oot_ib_player(Ctx *c, uint64_t comp) {
    static int busy, going;   /* (Link is updated by different workers on successive frames; going: a use or its end) */
    if (!ib_enabled() && !__atomic_load_n(&going, __ATOMIC_ACQUIRE)) return;
    const uint64_t actor = ib_link(c, comp);
    if (!actor || __atomic_exchange_n(&busy, 1, __ATOMIC_ACQUIRE)) return;
    ib_player_locked(c, comp, actor);
    __atomic_store_n(&going, ib_use.phase != IB_IDLE, __ATOMIC_RELEASE);
    __atomic_store_n(&busy, 0, __ATOMIC_RELEASE);
}

/* ---- what the menus share: the host's strings in guest memory, the assignment, the colours of an item on a face button */

/* The Assign guides' parts and words, and the panes the executable has no name of, in guest memory made once: for guide part
   k at k * IB_GUIDE_ROOM its name, its word's path and its glyph's; at IB_GUIDE_WORDS + w * IB_WORD_ROOM word w's record
   {char *, int, s64 -1} and its text (a text pane keeps a pointer to its text); at IB_PANE_NAMES the names, IB_NAME_ROOM
   each */
enum { IB_GUIDES = 5, IB_KEY_L = 5, IB_KEY_ZL = 6, IB_KEY_R = 7 };   /* (makeGuideKeyIconMsg's keys: 1 + IB_A.., L, ZL, R) */
enum { IB_WORD_MENU, IB_WORD_PLUS, IB_WORD_PAUSE, IB_WORDS };
/* (the quick-switch menu's row lines its parts up with no margin: spaces before its word, about the pause menu's gap; the
   pause menu's row has 90 between the game's guides and the Assign group, and none in it) */
static const char *const ib_words[IB_WORDS] = {"      Assign", " +", "Assign"};
enum { IB_N_GROUP, IB_N_TAB_L, IB_N_TAB_R, IB_N_EQUIP, IB_N_CELL_BG, IB_N_CELL_DECO, IB_N_BADGE, IB_N_BADGE_GLYPH, IB_NAMES_N };
static const char *const ib_pane_names[IB_NAMES_N] = {"A_GuideAssign_00", "T_BtnL_00", "T_BtnR_00", "P_Equip_00",
                                                      "P_ShortcutBg_01", "P_ShortcutDeco_02", "Pa_AssignKey_00",
                                                      "Pa_AssignKey_00/T_Icon_00"};
enum { IB_GUIDE_ROOM = 0x60, IB_GUIDE_WORD = 0x14, IB_GUIDE_ICON = 0x34, IB_GUIDE_WORDS = IB_GUIDES * IB_GUIDE_ROOM,
       IB_WORD_ROOM = 0x40, IB_PANE_NAMES = IB_GUIDE_WORDS + IB_WORDS * IB_WORD_ROOM, IB_NAME_ROOM = 0x20,
       IB_MEM = IB_PANE_NAMES + IB_NAMES_N * IB_NAME_ROOM };
static uint64_t ib_mem;

/* the block, 0 when there is none (made by the first hook that asks; two at once: one is kept) */
static uint64_t ib_guest_mem(void) {
    uint64_t m = __atomic_load_n(&ib_mem, __ATOMIC_ACQUIRE);
    if (m) return m;
    m = hos_sys_alloc(IB_MEM, 16);
    if (!m) return 0;
    for (int k = 0; k < IB_GUIDES; k++) {
        char *p = GP(m + (uint64_t)(IB_GUIDE_ROOM * k));
        snprintf(p, IB_GUIDE_WORD, "Pa_GuideAssign_%02d", k);
        snprintf(p + IB_GUIDE_WORD, IB_GUIDE_ICON - IB_GUIDE_WORD, "%s/T_Guide_00", p);
        snprintf(p + IB_GUIDE_ICON, IB_GUIDE_ROOM - IB_GUIDE_ICON, "%s/T_Icon_00", p);
    }
    for (int w = 0; w < IB_WORDS; w++) {
        const uint64_t rec = m + (uint64_t)(IB_GUIDE_WORDS + IB_WORD_ROOM * w);
        size_t n = strlen(ib_words[w]);
        if (n > IB_WORD_ROOM - 0x19) n = IB_WORD_ROOM - 0x19;
        memcpy(GP(rec + 0x18), ib_words[w], n);
        *(uint64_t *)GP(rec) = rec + 0x18, *(int32_t *)GP(rec + 8) = (int32_t)n, *(int64_t *)GP(rec + 0x10) = -1;
    }
    for (int i = 0; i < IB_NAMES_N; i++)
        snprintf(GP(m + (uint64_t)(IB_PANE_NAMES + IB_NAME_ROOM * i)), IB_NAME_ROOM, "%s", ib_pane_names[i]);
    HOS_WRITTEN(GP(m), IB_MEM);
    uint64_t none = 0;
    return __atomic_compare_exchange_n(&ib_mem, &none, m, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE) ? m : none;
}

static uint64_t ib_pane_name(uint64_t m, int i) { return m + (uint64_t)(IB_PANE_NAMES + IB_NAME_ROOM * i); }

/* An item on face button k of an age, or off it when it is there already (the menus' assignments): an item sits on one
   face button of an age at a time. In memory only, logged: the game's next save writes it. 0 when nothing was done (no
   item; that age's items not checked against the save yet) */
static int ib_put(int age, int k, int item) {
    if (item < 0 || item >= IB_ITEMS) return 0;
    int done = 0, off = 0;
    AcquireSRWLockExclusive(&ib_lock);
    if (__atomic_load_n(&ib_checked[age], __ATOMIC_ACQUIRE) == __atomic_load_n(&ib_load_gen, __ATOMIC_ACQUIRE)) {
        done = 1, off = ib_items[age][k] == item;
        for (int j = 0; j < IB_BUTTONS; j++)
            if (ib_items[age][j] == item) ib_items[age][j] = IB_NONE;
        if (!off) ib_items[age][k] = item;
    }
    ReleaseSRWLockExclusive(&ib_lock);
    if (!done) return 0;
    __atomic_add_fetch(&ib_gen, 1, __ATOMIC_RELEASE);
    hos_log("item buttons: %s %s %c (%s)", ib_name(item), off ? "off" : "on", "ABXY"[k], ib_age_keys[age]);
    return 1;
}

/* An assignment shown as the game shows its own choice: a flash of the button chosen (LayoutAnim::start), and the sound of
   an item put on ZR (Screen::playSound, when the screen has its sound user; x8 the result) */
static void ib_chosen(Ctx *c, uint64_t screen, uint64_t flash) {
    const float speed = 1.0f;
    if (flash) ib_guest(c, 0x80bcce80ULL, 1, &flash, 1, &speed);
    if (ib_peek(ib_peek(screen + 0x198, 8) + 8, 8)) {
        const uint64_t sound[9] = {screen, IB_CHANGE_SOUND, 0, 0, 0, 0, 0, 0, ib_scratch(c)};
        ib_guest(c, 0x8379c0d0ULL, 9, sound, 0, NULL);
    }
}

/* An item on a face button is light blue where the item on ZR is gold: a cool hue (#6EC6FF) as light on the screen as the
   gold beside it (measured there), linear as the layouts' colours. On the pause menu's Items page the four stops (rgb) of
   the colour ramp P_Equip_00's shader draws its grey square through (the gold square of the item on ZR); in the
   quick-switch carousel P_ShortcutBg_01's black and white and P_ShortcutDeco_02's white (the amber of the item on ZR) */
static const float ib_blue_ramp[4][3] = {{0.026f, 0.093f, 0.163f}, {0.063f, 0.232f, 0.410f}, {0.079f, 0.288f, 0.510f},
                                         {0.700f, 0.950f, 1.000f}};
static const float ib_blue_cell[3][4] = {{0.037f, 0.135f, 0.240f, 0.0f}, {0.081f, 0.294f, 0.520f, 1.0f},
                                         {0.020f, 0.073f, 0.130f, 1.0f}};

/* a pane of a layout, its colours (Layout::findPane, then Pane::getMaterialColors: +0x00 the black, +0x10 the white, +0x20
   the drawable), 0 none */
static uint64_t ib_colours_of(Ctx *c, uint64_t layout, uint64_t name) {
    const uint64_t find[2] = {layout, name};
    const uint64_t pane = layout && name ? ib_guest(c, 0x8078e2b0ULL, 2, find, 0, NULL) : 0;
    return pane ? ib_guest(c, 0x8045b700ULL, 1, &pane, 0, NULL) : 0;
}

/* a pane's black (white 0) or white colour set to rgba (MaterialColors::setBlackColor, setWhiteColor: each walks the pane
   tree up), unless it is that already */
static void ib_colour(Ctx *c, uint64_t colors, int white, const float rgba[4]) {
    const void *now = colors >= 0x100000 ? hos_guest_range(colors + (white ? 0x10 : 0), 16) : NULL;
    if (now && memcmp(now, rgba, 16)) ib_guest(c, white ? 0x8155db90ULL : 0x8155db70ULL, 1, &colors, 4, rgba);
}

/* a LayoutAnim's frame now (its player at +0x20, the frame at +0x18 of that), -1 none */
static int ib_frame(uint64_t anim) {
    const uint64_t player = anim ? ib_peek(anim + 0x20, 8) : 0;
    const uint32_t bits = (uint32_t)ib_peek(player + 0x18, 4);
    float f;
    memcpy(&f, &bits, 4);
    return player && f >= 0.0f && f < 64.0f ? (int)(f + 0.5f) : -1;
}

/* ---- hooks 6, 7 and 8: the quick-switch menu (UIShortCutScreen; its row of items at +0x2b0) */

/* A face button's glyph on an entry's T_Assign_00, shown in its colour (k: 0 to 3), or the pane hidden and its colour the
   layout's cream again (-1): the entries' parts are pooled, so one that shows another item must lose both. The text goes
   on the pane itself: the layout's setter by path (setAssignKey's) takes only text ids "@name", T_Assign_00's is "*" */
static void ib_glyph(Ctx *c, uint64_t btn, int k) {
    static float cream[4];
    static int cream_known;   /* (the first entry's, read before any is set: every entry's T_Assign_00 has the same) */
    const uint64_t layout = ib_peek(btn + 0x20, 8), s = ib_scratch(c);
    if (!layout) return;
    const uint64_t find[2] = {layout, IB_T_ASSIGN};
    const uint64_t pane = ib_guest(c, 0x8078e2b0ULL, 2, find, 0, NULL);   /* (Layout::findPane) */
    if (!pane) return;
    if (k >= 0) {   /* (an empty string record, as f_80a86f70 makes one; makeGuideKeyIconMsg: 1 A, 2 B, 3 X, 4 Y) */
        recomp_store64_sp(c, s, 0), recomp_store64_sp(c, s + 8, 0), recomp_store64_sp(c, s + 16, ~0ULL);
        const uint64_t key[2] = {s, (uint64_t)(1 + k)};
        if (ib_guest(c, 0x80a8ae50ULL, 2, key, 0, NULL) & 1) {
            const uint64_t text[2] = {pane, s};
            ib_guest(c, 0x80459520ULL, 2, text, 0, NULL);   /* (Pane::setTextBoxString) */
            __atomic_store_n(&ib_glyphs, 1, __ATOMIC_RELEASE);
        } else {
            k = -1;
        }
    }
    float was[4], rgba[4];
    if (ib_glyph_white(c, pane, NULL, was)) {
        if (!__atomic_load_n(&cream_known, __ATOMIC_ACQUIRE))
            memcpy(cream, was, sizeof was), __atomic_store_n(&cream_known, 1, __ATOMIC_RELEASE);
        ib_glyph_white(c, pane, k >= 0 && ib_glyph_colour(k, rgba) ? rgba : cream, NULL);
    }
    const uint64_t shown[2] = {pane, k >= 0};
    ib_guest(c, 0x8022aea0ULL, 2, shown, 0, NULL);   /* (Pane::setVisible) */
}

/* every pooled entry's glyph, again */
static void ib_glyphs_all(Ctx *c, uint64_t row, int on) {
    const uint64_t ctrl = ib_peek(row + 0x68, 8), list = ib_peek(ctrl + 0x68, 8);
    const int n = (int32_t)ib_peek(ctrl + 0x60, 4), age = ib_age(c);
    for (int i = 0; list && i < n && i < 64; i++) {
        const uint64_t btn = ib_peek(list + 8ull * (unsigned)i, 8);
        if (btn) ib_glyph(c, btn, on ? ib_button_of(age, (int32_t)ib_peek(btn + 0xd8, 4)) : -1);
    }
}

/* Each frame of the open menu: an entry whose item is on a face button and whose glyph is hidden gets it again. The menu's
   screen is made as it opens, and its entries' Type hold (frame 0: T_Assign_00 hidden), applied at the screen's first
   animation step, comes after their binding */
static void ib_glyphs_kept(Ctx *c, uint64_t row) {
    const uint64_t ctrl = ib_peek(row + 0x68, 8), list = ib_peek(ctrl + 0x68, 8);
    const int n = (int32_t)ib_peek(ctrl + 0x60, 4), age = ib_age(c);
    for (int i = 0; list && i < n && i < 64; i++) {
        const uint64_t btn = ib_peek(list + 8ull * (unsigned)i, 8), layout = ib_peek(btn + 0x20, 8);
        const int k = btn ? ib_button_of(age, (int32_t)ib_peek(btn + 0xd8, 4)) : -1;
        if (k < 0 || !layout) continue;
        const uint64_t find[2] = {layout, IB_T_ASSIGN};
        const uint64_t pane = ib_guest(c, 0x8078e2b0ULL, 2, find, 0, NULL);   /* (Layout::findPane) */
        if (pane && !(ib_peek(pane + 0xa8, 4) & 1)) ib_glyph(c, btn, k);   /* (bit 0 of its flags: shown) */
    }
}

/* The carousel's cells light blue for an item on a face button, at State frame 0 (frame 1 is the item on ZR: the game's
   amber, also when it is on a face button). The game sets the State's colours only when a cell's frame changes, and the
   cells are pooled (one shows another item as the list moves), so a cell that goes on to another item at frame 0 keeps the
   blue: frame 0's own colours go back from here, read once from a cell that has been at frame 0 for a frame (one that has
   just come to it keeps its old colours until the animation's next step, after this hook) */
enum { IB_CELLS = 64 };
static struct {
    uint64_t screen, btn[IB_CELLS], bg[IB_CELLS], deco[IB_CELLS];   /* (each cell's two panes' colours) */
    int zero[IB_CELLS];      /* (frames each cell has been at frame 0, up to 2) */
    float base[3][4];        /* (frame 0's: the background's black and white, the decoration's white) */
    int base_known, tinted;
} ib_cells;

static void ib_cells_tint(Ctx *c, uint64_t screen, uint64_t row, int on) {
    const uint64_t ctrl = ib_peek(row + 0x68, 8), list = ib_peek(ctrl + 0x68, 8), m = ib_guest_mem();
    const int n = (int32_t)ib_peek(ctrl + 0x60, 4), age = ib_age(c);
    if (__atomic_load_n(&ib_cells.screen, __ATOMIC_ACQUIRE) != screen)   /* (a new screen; one destroyed: ib_screen_gone) */
        memset(ib_cells.btn, 0, sizeof ib_cells.btn), __atomic_store_n(&ib_cells.screen, screen, __ATOMIC_RELEASE);
    int tinted = 0;
    for (int i = 0; list && m && i < n && i < IB_CELLS; i++) {
        const uint64_t btn = ib_peek(list + 8ull * (unsigned)i, 8);
        if (!btn) continue;
        if (ib_cells.btn[i] != btn) {
            const uint64_t layout = ib_peek(btn + 0x20, 8);
            ib_cells.bg[i] = ib_colours_of(c, layout, ib_pane_name(m, IB_N_CELL_BG));
            ib_cells.deco[i] = ib_colours_of(c, layout, ib_pane_name(m, IB_N_CELL_DECO));
            ib_cells.btn[i] = btn, ib_cells.zero[i] = 0;
        }
        const void *bg = ib_cells.bg[i] ? hos_guest_range(ib_cells.bg[i], 0x20) : NULL;
        const void *deco = ib_cells.deco[i] ? hos_guest_range(ib_cells.deco[i] + 0x10, 0x10) : NULL;
        if (!bg || !deco) continue;
        const int frame = ib_frame(ib_peek(btn + 0x38, 8));   /* (its State) */
        ib_cells.zero[i] = frame ? 0 : ib_cells.zero[i] < 2 ? ib_cells.zero[i] + 1 : 2;
        float now[3][4];
        memcpy(now[0], bg, 0x20), memcpy(now[2], deco, 0x10);
        const int blue = !memcmp(now[1], ib_blue_cell[1], 16);
        if (!ib_cells.base_known && ib_cells.zero[i] >= 2 && !blue) memcpy(ib_cells.base, now, sizeof now), ib_cells.base_known = 1;
        if (frame || !ib_cells.base_known) continue;
        if (on && ib_button_of(age, (int32_t)ib_peek(btn + 0xd8, 4)) >= 0) {
            ib_colour(c, ib_cells.bg[i], 0, ib_blue_cell[0]), ib_colour(c, ib_cells.bg[i], 1, ib_blue_cell[1]);
            ib_colour(c, ib_cells.deco[i], 1, ib_blue_cell[2]);
            tinted = 1;
        } else if (blue) {
            ib_colour(c, ib_cells.bg[i], 0, ib_cells.base[0]), ib_colour(c, ib_cells.bg[i], 1, ib_cells.base[1]);
            ib_colour(c, ib_cells.deco[i], 1, ib_cells.base[2]);
        }
    }
    ib_cells.tinted = tinted;
}

/* The Assign guides (nx2/item_buttons_layout.py: five PaGuideKey_00 parts, hidden, in a bottom row of guides, an alignment
   pane that lines up the parts it shows by what each draws; each part a word, then a glyph): "Assign" and the hotkey's
   glyph, a plus and the east face button's glyph, then the south, west and north ones' (the glyph of the Switch button on
   that face of the pad, through the prompts' font as every glyph is). The quick-switch menu's follows its own "Select" and
   shows while the feature is on; its screen is made anew each time it opens, and the parts are found, filled and shown
   then. The pause menu's is the last of the guides in the bottom row of the screen over it (MenuOverlay_00, Resident), in
   an alignment pane of its own (A_GuideAssign_00, hidden too), and shows on the Items page. The glyphs are set again when
   the controls change */
typedef struct {
    uint64_t screen;        /* (the screen the panes are of) */
    uint64_t group;         /* (the pause menu's: the alignment pane holding the parts) */
    uint64_t part[IB_GUIDES], word[IB_GUIDES], icon[IB_GUIDES];
    int keys[IB_GUIDES], shown;
    int relay;              /* (frames until the group is hidden and shown again, 0 none) */
    int missing, said;      /* (the screen's layout has no such parts; said so) */
    float cream[4];         /* (the glyphs' colour in the layout, for the face buttons' with the Xbox prompts) */
    int coloured;
} IbGuide;
static IbGuide ib_gd, ib_pd;   /* (the quick-switch menu's, the pause menu's) */
/* (the pause menu's shown: the room it takes at the right of its row, in the layout's units, 0 none; oot_menu.c moves its
   "Back" prompt's box that far left) */
static int ib_footer_room;
enum { IB_FOOTER_MARGIN = 90 };   /* (MenuOverlay_00's A_FirstGuide_00: the room it leaves between its guides) */
int ib_pause_footer_shift(void) { return __atomic_load_n(&ib_footer_room, __ATOMIC_ACQUIRE); }

static void ib_show(Ctx *c, uint64_t pane, int on) {
    if (pane && (int)(ib_peek(pane + 0xa8, 4) & 1) != !!on) {   /* (bit 0 of its flags: shown) */
        const uint64_t x[2] = {pane, !!on};
        ib_guest(c, 0x8022aea0ULL, 2, x, 0, NULL);   /* (Pane::setVisible) */
    }
}

/* the glyph of key on the text pane: makeGuideKeyIconMsg into a record below the sp, then Pane::setTextBoxString */
static int ib_put_key(Ctx *c, uint64_t pane, int key) {
    const uint64_t s = ib_scratch(c);
    recomp_store64_sp(c, s, 0), recomp_store64_sp(c, s + 8, 0), recomp_store64_sp(c, s + 16, ~0ULL);
    const uint64_t a[2] = {s, (uint64_t)key}, b[2] = {pane, s};
    if (!(ib_guest(c, 0x80a8ae50ULL, 2, a, 0, NULL) & 1)) return 0;
    ib_guest(c, 0x80459520ULL, 2, b, 0, NULL);
    return 1;
}

/* A guide on its screen, each frame of it: on, shown; fresh, the screen has just opened; word, part 0's; grouped, its parts
   are in A_GuideAssign_00, shown and hidden with them. A screen whose layout lacks the parts (the game's own, a mod's) is
   left alone, said once in the log (what: whose); one destroyed is forgotten (ib_screen_gone) */
static void ib_guide(Ctx *c, IbGuide *g, uint64_t screen, int on, int fresh, int word, int grouped, const char *what) {
    if (fresh || __atomic_load_n(&g->screen, __ATOMIC_ACQUIRE) != screen) {
        __atomic_store_n(&g->screen, 0, __ATOMIC_RELEASE);
        g->shown = g->missing = 0, g->group = 0;
        memset(g->keys, 0, sizeof g->keys);
        if (!on) return;
        const uint64_t m = ib_guest_mem(), body = ib_peek(screen + 0x28, 8), inst = body ? ib_peek(body + 0x80, 8) : 0;
        int found = inst && m;
        if (found && grouped) {
            const uint64_t a[2] = {inst, ib_pane_name(m, IB_N_GROUP)};
            found = (g->group = ib_guest(c, 0x8045e300ULL, 2, a, 0, NULL)) != 0;   /* (LayoutInstance::findPane) */
        }
        for (int k = 0; found && k < IB_GUIDES; k++) {
            const uint64_t at = m + (uint64_t)(IB_GUIDE_ROOM * k);
            const uint64_t a[2] = {inst, at}, w[2] = {body, at + IB_GUIDE_WORD}, i[2] = {body, at + IB_GUIDE_ICON};
            g->part[k] = ib_guest(c, 0x8045e300ULL, 2, a, 0, NULL);   /* (LayoutInstance::findPane) */
            g->word[k] = ib_guest(c, 0x8045e1e0ULL, 2, w, 0, NULL);   /* (Layout::findPaneByPath) */
            g->icon[k] = ib_guest(c, 0x8045e1e0ULL, 2, i, 0, NULL);
            found = g->part[k] && g->word[k] && g->icon[k];
        }
        if (!found) {
            if (!g->said)
                g->said = 1, hos_log("item buttons: %s layout has no Assign guide (the game's own, or a mod's): none there", what);
            g->missing = 1;
            __atomic_store_n(&g->screen, screen, __ATOMIC_RELEASE);
            return;
        }
        /* (the hotkey's glyph keeps the layout's cream: the east one's may still have its Xbox colour from the last showing,
           the overlay's panes being looked up again each time the Items page comes back) */
        g->coloured = ib_glyph_white(c, g->icon[0], NULL, g->cream);
        for (int k = 0; k < IB_GUIDES; k++) {
            const int w = k == 0 ? word : k == 1 ? IB_WORD_PLUS : -1;
            if (w >= 0) {
                const uint64_t x[2] = {g->word[k], m + (uint64_t)(IB_GUIDE_WORDS + IB_WORD_ROOM * w)};
                ib_guest(c, 0x80459520ULL, 2, x, 0, NULL);   /* (Pane::setTextBoxString) */
            }
            ib_show(c, g->word[k], w >= 0);   /* (no word: nothing drawn left of the glyph) */
        }
        __atomic_store_n(&g->screen, screen, __ATOMIC_RELEASE);
    }
    if (__atomic_load_n(&g->screen, __ATOMIC_ACQUIRE) != screen || g->missing) return;
    if (!on) {
        ib_show(c, g->group, 0);
        for (int k = 0; k < IB_GUIDES; k++) ib_show(c, g->part[k], 0);
        g->shown = 0;
        __atomic_store_n(&g->screen, 0, __ATOMIC_RELEASE);
        return;
    }
    int order[IB_BUTTONS], keys[IB_GUIDES];
    ib_face_order(order);
    keys[0] = ib_hotkey() == IB_HOTKEY_R ? IB_KEY_R : IB_KEY_L;
    for (int k = 1; k < IB_GUIDES; k++) keys[k] = 1 + order[k - 1];
    for (int k = 0; k < IB_GUIDES; k++) {
        if (keys[k] == g->keys[k] || !ib_put_key(c, g->icon[k], keys[k])) continue;
        g->keys[k] = keys[k], g->relay = 2;
        float rgba[4];
        if (k && g->coloured) ib_glyph_white(c, g->icon[k], ib_glyph_colour(order[k - 1], rgba) ? rgba : g->cream, NULL);
    }
    if (!g->shown) {
        for (int k = 0; k < IB_GUIDES; k++) ib_show(c, g->part[k], 1);
        ib_show(c, g->group, 1);
        g->shown = 1, g->relay = 2;
    }
    /* (the pause menu's row lines its guides up by each one's bounds, which a pane works out again only while it is marked
       changed (nn::ui::Pane::calcBounds, word 0 bit 3): a new glyph in a part does not mark the group, and the row would keep
       the room it had (over the game's guides as the menu opens). Hidden and shown in one frame, the frame after the group
       is shown or a glyph in it changes, it is marked; nothing else is drawn) */
    if (g->group && g->relay && --g->relay == 0) ib_show(c, g->group, 0), ib_show(c, g->group, 1);
}

/* hook 8, an entry bound to an item (x19 its ItemBtn, w20 the item) */
void hos_oot_ib_bind(Ctx *c, uint64_t btn, uint64_t item) {
    const int on = ib_enabled();
    if (!btn || (!on && !__atomic_load_n(&ib_glyphs, __ATOMIC_ACQUIRE))) return;
    int e = (int32_t)(uint32_t)item;
    if (e < 0 || e >= IB_ITEMS) e = (int32_t)ib_peek(btn + 0xd8, 4);
    ib_glyph(c, btn, on ? ib_button_of(ib_age(c), e) : -1);
}

/* hook 6, the menu's close on the sequence thread (x0 the row, w1 isBCancel): right after an assignment, with the
   focus not moved, letting the menu go leaves ZR as it was (decide then only clears its name) */
void hos_oot_ib_decide(Ctx *c) {
    if (__atomic_exchange_n(&ib_just_assigned, 0, __ATOMIC_ACQ_REL)) c->x[1] = 1;
}

/* An assign request: the highlighted item on face button k, or off it (ib_put). Shown as the game shows its own choice: the
   entry's flash, the row's, the sound */
static void ib_assign(Ctx *c, uint64_t screen, uint64_t row, int k) {
    const uint64_t ui = ib_peek(IB_UI_SLOT, 8);
    if (!(ib_peek(ui + 0x58c, 1) & 8) || !a64_lookup(IB_LOBBY) || (ib_guest(c, IB_LOBBY, 0, NULL, 0, NULL) & 1)) return;
    const uint64_t ctrl = ib_peek(row + 0x68, 8), list = ib_peek(ctrl + 0x68, 8);
    const int idx = (int32_t)ib_peek(ctrl + 0x4c, 4), n = (int32_t)ib_peek(ctrl + 0x60, 4);
    uint64_t focused = 0;
    for (int i = 0; list && i < n && i < 64 && !focused; i++) {   /* (the pooled entry bound to the focused index) */
        const uint64_t btn = ib_peek(list + 8ull * (unsigned)i, 8), entry = ib_peek(btn + 0xe0, 8);
        if (entry && (int32_t)ib_peek(entry + 0x44, 4) == idx) focused = btn;
    }
    if (!focused || !ib_put(ib_age(c), k, (int32_t)ib_peek(focused + 0xd8, 4))) return;
    __atomic_store_n(&ib_just_assigned, 1, __ATOMIC_RELEASE);
    const uint64_t btn[1] = {focused};
    ib_guest(c, 0x833dcf90ULL, 1, btn, 0, NULL);   /* (ItemBtn::playAssign) */
    ib_chosen(c, screen, ib_peek(row + 0x60, 8));   /* (the row's flash) */
    ib_glyphs_all(c, row, 1);
}

static void ib_shortcut_locked(Ctx *c, uint64_t screen) {
    static int64_t last_ns;
    static int last_index = -1;
    static uint32_t assign_seen;
    const int64_t now = hos_now_ns();
    const int on = ib_enabled(), state = (int)ib_peek(screen + 0x1a6, 1);
    const uint64_t row = ib_peek(screen + 0x2b0, 8);
    if (state) ib_guide(c, &ib_gd, screen, on, now - last_ns > IB_LIVE_NS, IB_WORD_MENU, 0, "the quick-switch menu's");
    if (!on || !state || !row) {
        __atomic_store_n(&ib_usable, 0, __ATOMIC_RELEASE);
        __atomic_store_n(&ib_just_assigned, 0, __ATOMIC_RELEASE);
        last_index = -1;
        if (!on && row && __atomic_exchange_n(&ib_glyphs, 0, __ATOMIC_ACQ_REL)) ib_glyphs_all(c, row, 0);
        if (!on && row && ib_cells.tinted) ib_cells_tint(c, screen, row, 0);
        return;
    }
    if (now - last_ns > IB_LIVE_NS) {   /* (opened anew: a screen of its own) */
        __atomic_store_n(&ib_just_assigned, 0, __ATOMIC_RELEASE), last_index = -1;
        __atomic_store_n(&ib_cells.screen, 0, __ATOMIC_RELEASE);
    }
    last_ns = now;
    __atomic_store_n(&ib_menu_ns, now, __ATOMIC_RELEASE);
    /* the list takes left and right (ShortCutSlideList::calc's tests): the row's flash is over, its layout open, the
       screen open with no close asked for, the row not locked; and it lists the slot's items */
    const uint32_t flash_bits = (uint32_t)ib_peek(ib_peek(row + 0x60, 8) + 0x10, 4);
    float flash;
    memcpy(&flash, &flash_bits, 4);
    const uint64_t parts = ib_peek(row + 0x20, 8), ctrl = ib_peek(row + 0x68, 8);
    const int usable = ib_peek(row + 0x60, 8) && flash == 0 && parts && ib_peek(parts + 0x3a, 1) == 2 && state == 2 &&
                       (int8_t)ib_peek(screen + 0x1a5, 1) >= 0 && !(ib_peek(row + 0x29c, 1) & 1) &&
                       (int32_t)ib_peek(row + 0x298, 4) == 0 && ctrl;
    __atomic_store_n(&ib_usable, usable, __ATOMIC_RELEASE);
    const int index = ctrl ? (int32_t)ib_peek(ctrl + 0x4c, 4) : -1;
    if (index != last_index) __atomic_store_n(&ib_just_assigned, 0, __ATOMIC_RELEASE), last_index = index;
    ib_glyphs_kept(c, row);
    const uint32_t r = ib_load32(&ib_assign_req);
    if (r != assign_seen) {
        assign_seen = r;
        if (usable && now - ib_load64(&ib_assign_ns) < IB_REQUEST_NS && (int)(r & 0xf) < IB_BUTTONS)
            ib_assign(c, screen, row, (int)(r & 0xf));
    }
    ib_cells_tint(c, screen, row, 1);
}

static void ib_shortcut(Ctx *c, uint64_t screen) {
    static int busy;
    if (__atomic_exchange_n(&busy, 1, __ATOMIC_ACQUIRE)) return;
    ib_shortcut_locked(c, screen);
    __atomic_store_n(&busy, 0, __ATOMIC_RELEASE);
}

/* ---- hook 7 with UICtrlGuideScreen: the game's control guide, the hints at the bottom of the screen ("Shoot Arrow" and
   ZR's glyph). Each of its entries (a GuideKeyControl: its part's word, then T_Icon_00 with the key's glyph) is written
   only when the guide shown changes (setGuideType, f_802f8df0). While an item used with the hotkey is out (hook 3), an
   open entry whose glyph is ZR's gets "ZR, hotkey + face button": the comma and the plus are glyphs of the prompts' font
   (nx2/prompt_assets.py guide_marks, a word space in each); the game's own icon font has neither, and with it the glyphs
   stand side by side after a gap, as the game draws an entry's two keys. Once the item is put away, or the entry closes,
   the game's own glyph goes back. The texts are in guest memory of their own (a text pane keeps a pointer to its text).
   The face button's glyph keeps the others' cream: the pane's colour is its whole text's, and one glyph's own would take
   the messages' colour tags */
#define IB_CTRL_GUIDE_VTABLE 0x84c05318ULL   /* UICtrlGuideScreen: +0x2b0 its entries' count, +0x2b8 the entries */
#define IB_GUIDE_KEY_VTABLE 0x84c010d8ULL    /* GuideKeyControl: +0x20 its part's layout */
#define IB_T_ICON 0x83e16a47ULL              /* "T_Icon_00" */
int hos_prompts_punctuation(void);           /* prompts.c */
/* (makeGuideKeyIconMsg's ZR; the entries read at most; the texts: hotkey L, then R, by the face buttons, IB_COMBO_ROOM each,
   a string record {char *, int, s64 -1} and its text; the gap without the marks: spaces of the icon font, 0.016 em each) */
enum { IB_KEY_ZR = 8, IB_ENTRIES = 8, IB_COMBOS = 2 * IB_BUTTONS, IB_COMBO_ROOM = 0x40, IB_COMBO_GAP = 12 };
static struct {
    uint64_t mem, screen;   /* (mem: the texts, 0 until made; screen: the guide's screen the panes are of) */
    uint64_t entry[IB_ENTRIES], icon[IB_ENTRIES];   /* (each entry's control, and its T_Icon_00) */
    unsigned mine;          /* (bits: the entries with a text of ours) */
    char zr[8];
    int zr_len;             /* (ZR's glyph, as its message has it) */
} ib_cg;

/* a key's glyph, makeGuideKeyIconMsg's message: its bytes into out, their count; 0 when it is not there */
static int ib_key_text(Ctx *c, int key, char out[8]) {
    const uint64_t s = ib_scratch(c);
    recomp_store64_sp(c, s, 0), recomp_store64_sp(c, s + 8, 0), recomp_store64_sp(c, s + 16, ~0ULL);
    const uint64_t a[2] = {s, (uint64_t)key};
    if (!(ib_guest(c, 0x80a8ae50ULL, 2, a, 0, NULL) & 1)) return 0;
    const uint64_t text = ib_peek(s, 8);
    const int n = (int32_t)ib_peek(s + 8, 4);
    if (n <= 0 || n > 8 || text < 0x100000 || !hos_guest_range(text, (unsigned)n)) return 0;
    memcpy(out, GP(text), (size_t)n);
    return n;
}

/* What an entry gets (no guest memory read: tests/test_item_buttons_filter.py checks it alone): the combo (1), ZR's
   glyph back (-1) or nothing (0). want: a combo is shown; open: its part's state (1 opening, 2 open); mine: it has a
   text of ours, wanted: that one; zr: its text is ZR's glyph alone */
static int ib_entry(int want, int open, int mine, int wanted, int zr) {
    if (want && (open == 1 || open == 2)) return (mine ? !wanted : zr) ? 1 : 0;
    return mine ? -1 : 0;
}

/* the texts, made once the messages are there: 1 when they are */
static int ib_combos(Ctx *c) {
    if (ib_cg.mem) return 1;
    char zr[8], hot[2][8], face[IB_BUTTONS][8];
    const int zn = ib_key_text(c, IB_KEY_ZR, zr), hn[2] = {ib_key_text(c, IB_KEY_L, hot[0]), ib_key_text(c, IB_KEY_R, hot[1])};
    int fn[IB_BUTTONS], ok = zn && hn[0] && hn[1];
    for (int k = 0; k < IB_BUTTONS; k++) ok &= (fn[k] = ib_key_text(c, 1 + k, face[k])) != 0;
    const uint64_t m = ok ? hos_sys_alloc(IB_COMBOS * IB_COMBO_ROOM, 16) : 0;
    if (!m) return 0;
    const int marks = hos_prompts_punctuation();   /* (the font was served at the game's start, long before play) */
    for (int i = 0; i < IB_COMBOS; i++) {
        const int h = i / IB_BUTTONS, k = i % IB_BUTTONS;
        const uint64_t rec = m + (uint64_t)(IB_COMBO_ROOM * i);
        char *t = GP(rec + 0x18);
        int n = 0;
        memcpy(t, zr, (size_t)zn), n += zn;
        if (marks) t[n++] = ',';   /* (the comma and a word space: one glyph of the prompts' font) */
        else memset(t + n, ' ', IB_COMBO_GAP), n += IB_COMBO_GAP;
        memcpy(t + n, hot[h], (size_t)hn[h]), n += hn[h];
        if (marks) t[n++] = '+';   /* (a word space, the plus, a word space) */
        memcpy(t + n, face[k], (size_t)fn[k]), n += fn[k];
        *(uint64_t *)GP(rec) = rec + 0x18, *(int32_t *)GP(rec + 8) = n, *(int64_t *)GP(rec + 0x10) = -1;
    }
    HOS_WRITTEN(GP(m), IB_COMBOS * IB_COMBO_ROOM);
    memcpy(ib_cg.zr, zr, (size_t)zn), ib_cg.zr_len = zn;
    ib_cg.mem = m;
    return 1;
}

static void ib_ctrl_guide_locked(Ctx *c, uint64_t screen) {
    const uint64_t o = __atomic_load_n(&ib_out, __ATOMIC_ACQUIRE);
    int k = ib_enabled() && o && (uint32_t)o == ib_load32(&ib_answer) ? (int)(o >> 32) - 1 : -1;
    if (k < 0 && !ib_cg.mine) return;   /* (every frame: nothing to show, nothing to put back) */
    if (__atomic_load_n(&ib_cg.screen, __ATOMIC_ACQUIRE) != screen) {
        memset(ib_cg.entry, 0, sizeof ib_cg.entry), ib_cg.mine = 0;
        __atomic_store_n(&ib_cg.screen, screen, __ATOMIC_RELEASE);
    }
    if (k >= IB_BUTTONS || (k >= 0 && !ib_combos(c))) k = -1;
    const uint64_t want = k < 0 ? 0 : ib_cg.mem + (uint64_t)(IB_COMBO_ROOM * (IB_BUTTONS * (ib_hotkey() == IB_HOTKEY_R) + k));
    const uint32_t n = (uint32_t)ib_peek(screen + 0x2b0, 4);
    const uint64_t list = ib_peek(screen + 0x2b8, 8);
    for (uint32_t i = 0; list && i < n && i < IB_ENTRIES; i++) {
        const uint64_t ctrl = ib_peek(list + 8ull * i, 8), layout = ib_peek(ctrl + 0x20, 8);
        if (!ctrl || ib_peek(ctrl, 8) != IB_GUIDE_KEY_VTABLE || !layout) continue;
        if (ib_cg.entry[i] != ctrl) {
            const uint64_t find[2] = {layout, IB_T_ICON};
            ib_cg.icon[i] = ib_guest(c, 0x8078e2b0ULL, 2, find, 0, NULL);   /* (Layout::findPane) */
            ib_cg.entry[i] = ctrl, ib_cg.mine &= ~(1u << i);
        }
        const uint64_t pane = ib_cg.icon[i], tp = pane ? ib_peek(ib_peek(pane + 8, 8) + 8, 8) : 0;   /* (its TextPane) */
        if (!tp) continue;
        const uint64_t text = ib_peek(tp + 0xf0, 8);   /* (the pane's text and its length in bytes) */
        const int len = (int32_t)ib_peek(tp + 0x124, 4), open = (int)ib_peek(layout + 0x3a, 1);   /* (1 opening, 2 open) */
        int mine = ib_cg.mem && text >= ib_cg.mem && text < ib_cg.mem + IB_COMBOS * IB_COMBO_ROOM;
        const int zr = len == ib_cg.zr_len && text >= 0x100000 && hos_guest_range(text, (unsigned)len) &&
                       !memcmp(GP(text), ib_cg.zr, (size_t)len);
        const int todo = ib_entry(want != 0, open, mine, text == want + 0x18, zr);
        if (todo > 0) {
            const uint64_t x[2] = {pane, want};
            ib_guest(c, 0x80459520ULL, 2, x, 0, NULL);   /* (Pane::setTextBoxString) */
            mine = 1;
        } else if (todo < 0 && ib_put_key(c, pane, IB_KEY_ZR)) {
            mine = 0;
        }
        ib_cg.mine = mine ? ib_cg.mine | 1u << i : ib_cg.mine & ~(1u << i);
    }
}

static void ib_ctrl_guide(Ctx *c, uint64_t screen) {
    static int busy;
    if (__atomic_exchange_n(&busy, 1, __ATOMIC_ACQUIRE)) return;
    ib_ctrl_guide_locked(c, screen);
    __atomic_store_n(&busy, 0, __ATOMIC_RELEASE);
}

/* ---- hook 7 with the pause menu (UIPlusMenuScreen) and the screen over it (UIMenuOverlayScreen: the tab bar and the bottom
   row of guides, the Minus panel's as well). With the feature on:
   - the pause menu's pages turn with ZL and ZR alone, which the game takes as it takes L and R: the filter hides L and R
     while the pause menu's screen runs open (its stamp), and the tab bar shows ZL's and ZR's glyphs;
   - on the Items page hotkey + A B X Y puts the focused slot's item on that face button, as in the quick-switch menu (the
     filter hides the four under the hotkey on every page), shown with the slot's own Decide flash and the game's sound;
   - the Items page's slots of items on face buttons are light blue with their button's glyph on a corner, and its bottom
     row has the Assign guide */
#define IB_PLUS_VTABLE 0x84c0baa8ULL      /* UIPlusMenuScreen: +0x308 its Items page (an ItemMenu, a parts control) */
#define IB_OVERLAY_VTABLE 0x84c08aa0ULL   /* UIMenuOverlayScreen: +0x350 1 with the pause menu's tabs, +0x354 its preset */
enum { IB_SLOTS = 64, IB_PAGE_ITEMS = 4, IB_PRESET_ITEMS = 5 };   /* (UIModule +0x530's page; the overlay's preset of it) */

/* the item on ZR for an age as the Items page compares its slots with it (getAssignableItem, isDirect 1: ItemMenu::onOpen's;
   the getter's hook lets a caller it does not know through) */
static int ib_zr_item(Ctx *c, int age) {
    const uint64_t mgr = ib_peek(IB_POUCH_SLOT, 8);
    if (!mgr || !a64_lookup(IB_GETTER)) return IB_NONE;
    const uint64_t a[3] = {mgr, (uint64_t)age, 1};
    return (int32_t)ib_guest(c, IB_GETTER, 3, a, 0, NULL);
}

/* The Items page (an ItemMenu: +0x20 its parts layout, s32 +0x70 its slots' count, +0x78 the slots) and a slot (an
   ItemMenuBtn: +0x20 its layout, +0x30 its Decide animation, +0x48 its State, s32 +0xe0 its item, -1 none, +0xe8 its
   UniteButton: +0x38 not 0 while focused, +0x40 bit 4 input on). State: 0 empty, 1 an item, 2 the item on ZR (the plain
   square hidden, P_Equip_00's gold one shown), 3 the other age's. The slot the focus is on, 0 none */
static uint64_t ib_focused_slot(uint64_t page) {
    const uint64_t list = ib_peek(page + 0x78, 8);
    const int n = (int32_t)ib_peek(page + 0x70, 4);
    for (int i = 0; list && i < n && i < IB_SLOTS; i++) {
        const uint64_t slot = ib_peek(list + 8ull * (unsigned)i, 8), button = slot ? ib_peek(slot + 0xe8, 8) : 0;
        if (button && ib_peek(button + 0x38, 1)) return slot;
    }
    return 0;
}

/* Where a slot's glyph goes (no guest memory: tests/test_item_buttons_hud.py checks it alone): on the top right corner of
   its box, a little in, in the slot's N_All_00 units (y up). The box is P_Base_00's picture, one of 14 shapes, which the
   slot's ItemPattern (a frame each slot holds, 0 to 35: its place on the page) picks by its texture pattern; a shape's
   corner is the point of its outline nearest the top right of its bounds, 12 units towards the middle (measured on the
   textures). A frame the page does not use: the plain square's */
enum { IB_PATTERNS = 36, IB_SHAPES = 14 };
static void ib_badge_at(int pattern, float *x, float *y) {
    static const signed char shape[IB_PATTERNS] = {5, 4, 7, 6, 8, 8, 9, 9, 10, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13, 13,
                                                   13, 13, 13, 11, 2, 2, 2, 2, 3, 3, 3, 3, 0, 1, 1, 12};
    static const short corner[IB_SHAPES][2] = {{127, 235}, {153, 156}, {222, 225}, {214, 60}, {136, 150}, {91, 228},
                                               {67, 151}, {132, 91}, {121, 115}, {91, 78}, {75, 132}, {100, 115},
                                               {75, 76}, {109, 117}};
    const int s = pattern >= 0 && pattern < IB_PATTERNS ? shape[pattern] : 13;
    *x = corner[s][0], *y = corner[s][1];
}

/* The slots light blue for an item on a face button: State frame 2 with P_Equip_00's colour ramp blue. Its four stops are
   the drawable's shader parameters (the drawable at the colours' +0x20: +0x40 the parameters, 16 bytes each, their count in
   bits 23..26 of +0x58), each pane's own copy of its material's, written as Drawable::setShaderParam writes them; no
   animation of the slot drives them. The page's readers of State take 1 and 2 alike, and the game holds it again from the
   item on ZR (the page opening, A on a slot): the frame is put back each frame. The item on ZR keeps its gold, also when it
   is on a face button; the gold is read from the first slot seen (every slot has the layout's).
   Each slot of an item on a face button (the item on ZR too) shows that button's glyph on its box's corner: a PaGuideKey_00
   part of its own (nx2/item_buttons_layout.py: Pa_AssignKey_00, hidden, the last child of the slot's N_All_00, which moves
   with the box), whose T_Icon_00 gets makeGuideKeyIconMsg's 1 + k, the glyph the carousel and the HUD show for the button,
   in the same colour; its word stays empty. A layout without the part (the game's own, a mod's) has no glyphs there */
static struct {
    uint64_t screen, page, slot[IB_SLOTS], ramp[IB_SLOTS];   /* (screen: the pause menu's the page is of) */
    uint64_t badge[IB_SLOTS], glyph[IB_SLOTS];               /* (each slot's Pa_AssignKey_00, the pane itself; its glyph) */
    int key[IB_SLOTS];                                       /* (the face button whose glyph it shows, + 1; 0 none) */
    float gold[4][4], blue[4][4], cream[4];                  /* (cream: the glyph's colour in the layout) */
    int gold_known, cream_known, tinted, badges, said;
    unsigned ticks;
} ib_page;

/* slot i's glyph: face button k's at its box's corner, or hidden (-1). Its text is set when the button changes (none shown
   while the message is not there); its colour then and every 30 frames (the controls can change with the menu open) */
static void ib_badge(Ctx *c, int i, uint64_t slot, int k) {
    const uint64_t badge = ib_page.badge[i], glyph = ib_page.glyph[i];
    if (!badge) return;
    if (k < 0 || (ib_page.key[i] != k + 1 && !ib_put_key(c, glyph, 1 + k))) {
        ib_show(c, badge, 0), ib_page.key[i] = 0;
        return;
    }
    float x, y, now[2];
    ib_badge_at(ib_frame(ib_peek(slot + 0x60, 8)), &x, &y);   /* (its ItemPattern) */
    const uint64_t at = ib_peek(badge + 0x6c, 8);              /* (the pane's translate) */
    memcpy(now, &at, sizeof now);
    if (now[0] != x || now[1] != y) {
        const float s[3] = {x, y, 0.0f};
        ib_guest(c, 0x8022a3e0ULL, 1, &badge, 3, s);   /* (Pane::setTranslate) */
    }
    float rgba[4];
    if (ib_page.cream_known && (ib_page.key[i] != k + 1 || ib_page.ticks % 30 == 0))
        ib_glyph_white(c, glyph, ib_glyph_colour(k, rgba) ? rgba : ib_page.cream, NULL);
    ib_page.key[i] = k + 1;
    ib_show(c, badge, 1);
}

static void ib_items_tint(Ctx *c, uint64_t screen, uint64_t page, int on) {
    const uint64_t list = ib_peek(page + 0x78, 8), m = ib_guest_mem();
    const int n = (int32_t)ib_peek(page + 0x70, 4), age = ib_age(c), zr = ib_zr_item(c, age);
    /* (a new page, or a new screen: one destroyed, ib_screen_gone) */
    if (ib_page.page != page || __atomic_load_n(&ib_page.screen, __ATOMIC_ACQUIRE) != screen) {
        memset(ib_page.slot, 0, sizeof ib_page.slot), ib_page.page = page;
        __atomic_store_n(&ib_page.screen, screen, __ATOMIC_RELEASE);
    }
    int tinted = 0, badges = 0;
    for (int i = 0; list && m && i < n && i < IB_SLOTS; i++) {
        const uint64_t slot = ib_peek(list + 8ull * (unsigned)i, 8);
        if (!slot) continue;
        if (ib_page.slot[i] != slot) {
            const uint64_t layout = ib_peek(slot + 0x20, 8), inst = layout ? ib_peek(layout + 0x80, 8) : 0;
            const uint64_t colors = ib_colours_of(c, layout, ib_pane_name(m, IB_N_EQUIP));
            const uint64_t draw = colors ? ib_peek(colors + 0x20, 8) : 0, ramp = draw ? ib_peek(draw + 0x40, 8) : 0;
            ib_page.ramp[i] = ramp && (ib_peek(draw + 0x58, 4) >> 23 & 0xf) >= 4 ? ramp : 0;
            /* (LayoutInstance::findPane: the parts pane itself; Layout::findPaneByPath: the glyph in its part) */
            const uint64_t a[2] = {inst, ib_pane_name(m, IB_N_BADGE)}, b[2] = {layout, ib_pane_name(m, IB_N_BADGE_GLYPH)};
            ib_page.badge[i] = inst ? ib_guest(c, 0x8045e300ULL, 2, a, 0, NULL) : 0;
            ib_page.glyph[i] = ib_page.badge[i] ? ib_guest(c, 0x8045e1e0ULL, 2, b, 0, NULL) : 0;
            if (!ib_page.glyph[i]) ib_page.badge[i] = 0;
            if (!ib_page.badge[i] && !ib_page.said)
                ib_page.said = 1, hos_log("item buttons: the Items page's slots have no Pa_AssignKey_00 (the game's own "
                                          "layout, or a mod's): no button glyphs on them");
            if (ib_page.glyph[i] && !ib_page.cream_known)   /* (the first slot's, before any is coloured) */
                ib_page.cream_known = ib_glyph_white(c, ib_page.glyph[i], NULL, ib_page.cream);
            ib_page.key[i] = 0, ib_page.slot[i] = slot;
        }
        const uint64_t state = ib_peek(slot + 0x48, 8);
        const int frame = ib_frame(state), item = (int32_t)ib_peek(slot + 0xe0, 4);
        const int k = on && item >= 0 && item < IB_ITEMS && (frame == 1 || frame == 2) ? ib_button_of(age, item) : -1;
        ib_badge(c, i, slot, k);
        badges += ib_page.key[i] != 0;
        void *ramp = ib_page.ramp[i] >= 0x100000 ? hos_guest_range(ib_page.ramp[i], sizeof ib_page.gold) : NULL;
        if (!ramp) continue;
        if (!ib_page.gold_known) {
            memcpy(ib_page.gold, ramp, sizeof ib_page.gold);
            for (int s = 0; s < 4; s++) memcpy(ib_page.blue[s], ib_blue_ramp[s], 12), ib_page.blue[s][3] = ib_page.gold[s][3];
            ib_page.gold_known = 1;
        }
        const int blue = !memcmp(ramp, ib_page.blue, 64);
        float to = 0.0f;
        if (k >= 0 && item != zr) {
            if (!blue) memcpy(ramp, ib_page.blue, 64), HOS_WRITTEN(ramp, 64);
            to = frame != 2 ? 2.0f : 0.0f;
            tinted = 1;
        } else if (blue) {
            memcpy(ramp, ib_page.gold, 64), HOS_WRITTEN(ramp, 64);
            to = frame == 2 && item != zr ? 1.0f : 0.0f;
        }
        if (to > 0.0f) ib_guest(c, 0x802f2d90ULL, 1, &state, 1, &to);   /* (LayoutAnim::setFrame) */
    }
    ib_page.tinted = tinted, ib_page.badges = badges, ib_page.ticks++;
}

/* hotkey + face button k on the Items page: the focused slot's item (an item of this age: State 1 or 2) on k, or off it */
static void ib_pause_assign(Ctx *c, uint64_t screen, uint64_t slot, int k) {
    const uint64_t ui = ib_peek(IB_UI_SLOT, 8);
    if (!(ib_peek(ui + 0x58c, 1) & 8) || !a64_lookup(IB_LOBBY) || (ib_guest(c, IB_LOBBY, 0, NULL, 0, NULL) & 1)) return;
    const int frame = ib_frame(ib_peek(slot + 0x48, 8));
    if ((frame == 1 || frame == 2) && ib_put(ib_age(c), k, (int32_t)ib_peek(slot + 0xe0, 4)))
        ib_chosen(c, screen, ib_peek(slot + 0x30, 8));
}

/* The pause menu's screen each frame: open (1 opening, 2 open) its stamp for the filter, gone as it closes; the Items page
   takes an assignment while it is the page shown and settled (the screen open with no close asked for, no page change and
   no InAfter running, the page's layout open, the focused slot's input on), and its slots' looks follow the assignments
   while it is shown or being turned to (UIModule +0x538, the page a change goes to), and once more after the feature is
   turned off */
static void ib_pause_locked(Ctx *c, uint64_t s) {
    static uint32_t seen;   /* (the last request looked at) */
    static int64_t last_ns;
    const int64_t now = hos_now_ns();
    const int on = ib_enabled(), st = (int)ib_peek(s + 0x1a6, 1);
    if (now - last_ns > IB_LIVE_NS) ib_page.page = 0;   /* (opened anew: its slots looked up again) */
    last_ns = now;
    __atomic_store_n(&ib_plus, s, __ATOMIC_RELEASE);
    __atomic_store_n(&ib_pause_ns, on && (st == 1 || st == 2) ? now : 0, __ATOMIC_RELEASE);
    const uint64_t page = ib_peek(s + 0x308, 8), ui = ib_peek(IB_UI_SLOT, 8);
    const int items = page && ui && (uint32_t)ib_peek(ui + 0x530, 4) == IB_PAGE_ITEMS;
    const int coming = page && ui && (uint32_t)ib_peek(ui + 0x538, 4) == IB_PAGE_ITEMS;
    const uint64_t slot = items ? ib_focused_slot(page) : 0, button = slot ? ib_peek(slot + 0xe8, 8) : 0;
    const int usable = on && st == 2 && (int8_t)ib_peek(s + 0x1a5, 1) >= 0 && !ib_peek(s + 0x328, 1) && !ib_peek(s + 0x329, 1) &&
                       slot && ib_peek(ib_peek(page + 0x20, 8) + 0x3a, 1) == 2 && (ib_peek(button + 0x40, 4) & 0x10);
    __atomic_store_n(&ib_pause_usable, usable, __ATOMIC_RELEASE);
    const uint32_t r = ib_load32(&ib_pause_req);
    if (r != seen) {
        seen = r;
        if (usable && now - ib_load64(&ib_pause_req_ns) < IB_REQUEST_NS && (int)(r & 0xf) < IB_BUTTONS)
            ib_pause_assign(c, s, slot, (int)(r & 0xf));
    }
    if (page && ((on && (items || coming)) || ib_page.tinted || ib_page.badges)) ib_items_tint(c, s, page, on);
}

static void ib_pause(Ctx *c, uint64_t screen) {
    static int busy;
    if (__atomic_exchange_n(&busy, 1, __ATOMIC_ACQUIRE)) return;
    ib_pause_locked(c, screen);
    __atomic_store_n(&busy, 0, __ATOMIC_RELEASE);
}

/* The tab bar's two glyphs (MenuOverlay_00's T_BtnL_00 and T_BtnR_00: the layout's messages, set as it loads and never
   again): ZL's and ZR's while it shows the pause menu's tabs with the feature on, the game's L and R otherwise (the Minus
   panel's tabs, the feature off). Read each frame, set only when they differ */
static struct {
    uint64_t screen, pane[2];
    char key[4][8];   /* (makeGuideKeyIconMsg's glyphs of L, R, ZL, ZR) */
    int len[4];
} ib_tabs;

static void ib_tab_glyphs(Ctx *c, uint64_t ov, int zl) {
    static const int keys[4] = {IB_KEY_L, IB_KEY_R, IB_KEY_ZL, IB_KEY_ZR};
    if (__atomic_load_n(&ib_tabs.screen, __ATOMIC_ACQUIRE) != ov) {
        const uint64_t m = ib_guest_mem(), body = ib_peek(ov + 0x28, 8);
        int ok = zl && m && body;   /* (not looked for until wanted: the game's own glyphs until then) */
        for (int i = 0; ok && i < 4; i++) ok = (ib_tabs.len[i] = ib_key_text(c, keys[i], ib_tabs.key[i])) != 0;
        if (!ok) return;
        for (int i = 0; i < 2; i++) {
            const uint64_t find[2] = {body, ib_pane_name(m, IB_N_TAB_L + i)};
            ib_tabs.pane[i] = ib_guest(c, 0x8078e2b0ULL, 2, find, 0, NULL);   /* (Layout::findPane) */
        }
        __atomic_store_n(&ib_tabs.screen, ov, __ATOMIC_RELEASE);
    }
    for (int i = 0; i < 2; i++) {
        const uint64_t pane = ib_tabs.pane[i], tp = pane ? ib_peek(ib_peek(pane + 8, 8) + 8, 8) : 0;   /* (its TextPane) */
        if (!tp) continue;
        const int want = zl ? 2 + i : i, len = (int32_t)ib_peek(tp + 0x124, 4);
        const uint64_t text = ib_peek(tp + 0xf0, 8);   /* (the pane's text and its length in bytes) */
        if (len == ib_tabs.len[want] && text >= 0x100000 && hos_guest_range(text, (unsigned)len) &&
            !memcmp(GP(text), ib_tabs.key[want], (size_t)len))
            continue;
        ib_put_key(c, pane, keys[want]);
    }
}

/* The screen over the pause menu each frame: its tab bar's glyphs, the Assign guide on the Items page's preset. With the
   Minus panel's tabs up and the pause menu's screen no longer opening or open, the pause stamp goes at once (a shoulder
   button pressed in the panel straight away is the panel's) */
static void ib_overlay_locked(Ctx *c, uint64_t ov) {
    const int on = ib_enabled(), tabs = (int32_t)ib_peek(ov + 0x350, 4), preset = (int32_t)ib_peek(ov + 0x354, 4);
    const uint64_t plus = __atomic_load_n(&ib_plus, __ATOMIC_ACQUIRE);
    const int st = plus ? (int)ib_peek(plus + 0x1a6, 1) : 0;
    if (tabs != 1 && st != 1 && st != 2) __atomic_store_n(&ib_pause_ns, 0, __ATOMIC_RELEASE);
    ib_tab_glyphs(c, ov, on && tabs == 1);
    ib_guide(c, &ib_pd, ov, on && tabs == 1 && preset == IB_PRESET_ITEMS, 0, IB_WORD_PAUSE, 1, "the pause menu's");
    /* (the room the guide takes: its bounds' width (nn::ui::Pane::calcBounds: x, y, w, h at +0x94) and the row's margin
       before it; the row is right-aligned, so its other guides are that far left of where the game has them) */
    int room = 0;
    if (ib_pd.shown && __atomic_load_n(&ib_pd.screen, __ATOMIC_ACQUIRE) == ov) {
        const uint32_t bits = (uint32_t)ib_peek(ib_pd.group + 0x9c, 4);
        float w;
        memcpy(&w, &bits, 4);
        if (w > 0.0f && w < 3000.0f) room = (int)(w + 0.5f) + IB_FOOTER_MARGIN;
    }
    __atomic_store_n(&ib_footer_room, room, __ATOMIC_RELEASE);
}

static void ib_overlay(Ctx *c, uint64_t screen) {
    static int busy;
    if (__atomic_exchange_n(&busy, 1, __ATOMIC_ACQUIRE)) return;
    ib_overlay_locked(c, screen);
    __atomic_store_n(&busy, 0, __ATOMIC_RELEASE);
}

/* hook 10 (oot_item_buttons_hud.c's hos_oot_ib_screen_gone): a screen destroyed. The guides, the tab bar, the carousel's
   cells and the Items page's slots forget their panes of it, the filter the pause menu's */
void ib_screen_gone(uint64_t screen) {
    uint64_t was = screen;
    __atomic_compare_exchange_n(&ib_gd.screen, &was, 0, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED);
    was = screen;
    if (__atomic_compare_exchange_n(&ib_pd.screen, &was, 0, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED))
        __atomic_store_n(&ib_footer_room, 0, __ATOMIC_RELEASE);
    was = screen;
    __atomic_compare_exchange_n(&ib_cells.screen, &was, 0, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED);
    was = screen;
    __atomic_compare_exchange_n(&ib_page.screen, &was, 0, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED);
    was = screen;
    __atomic_compare_exchange_n(&ib_cg.screen, &was, 0, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED);
    was = screen;
    __atomic_compare_exchange_n(&ib_tabs.screen, &was, 0, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED);
    was = screen;
    if (__atomic_compare_exchange_n(&ib_plus, &was, 0, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED))
        __atomic_store_n(&ib_pause_ns, 0, __ATOMIC_RELEASE);
}

/* hook 7 with the title screen (UITitleScreen): the title has come up, when it had not since play last ran and its
   frames had stopped (a frame of it as play starts is no new title) */
static void ib_title(void) {
    const int64_t now = hos_now_ns(), last = __atomic_exchange_n(&ib_title_last_ns, now, __ATOMIC_ACQ_REL);
    if (now - last > IB_LIVE_NS && !__atomic_load_n(&ib_title_open, __ATOMIC_ACQUIRE)) {
        __atomic_store_n(&ib_title_ns, now, __ATOMIC_RELEASE);
        __atomic_store_n(&ib_title_open, 1, __ATOMIC_RELEASE);
        hos_log("item buttons: the title screen came up");
    }
}

/* hook 7: after a screen's update, every screen's every frame (x19 the screen) */
void hos_oot_ib_screen(Ctx *c, uint64_t screen) {
    const uint64_t vt = ib_peek(screen, 8);
    if (!__atomic_load_n(&ib_hooked, __ATOMIC_RELAXED)) __atomic_store_n(&ib_hooked, 1, __ATOMIC_RELEASE);
    if (vt == IB_SHORTCUT_VTABLE) ib_shortcut(c, screen);
    else if (vt == IB_HUD_VTABLE) ib_hud_tick(c, screen);
    else if (vt == IB_CTRL_GUIDE_VTABLE) ib_ctrl_guide(c, screen);
    else if (vt == IB_PLUS_VTABLE) ib_pause(c, screen);
    else if (vt == IB_OVERLAY_VTABLE) ib_overlay(c, screen);
    else if (vt == IB_TITLE_VTABLE) ib_title();
}
