/* (hookshot) Item assignable buttons (the Insert menu's Controls tab): what the feature's two files share.
   host/oot_item_buttons.c has the controller filter, the item slot's answers, the game's hooks and the file the
   assignments are kept in; host/oot_item_buttons_hud.c shows the four items on the game's HUD.

   The game has one item slot, used with ZR, and a quick-switch menu on L and R. With the feature on, one of the two
   shoulder buttons is a hotkey the game no longer sees: held in play, A B X Y each use the item assigned to them; with the
   quick-switch menu open (the other shoulder button), or on the pause menu's Items page, hotkey + A B X Y assigns the item
   shown. Nothing is written to the game's save: the items are in <user>/item_buttons.ini.

   The hooks are nx2/oot_patches.py's (the supported build's lift only). Without them none of this runs and the filter
   passes every button through. */
#pragma once
#include "hos.h"

enum { IB_A, IB_B, IB_X, IB_Y, IB_BUTTONS };   /* the face buttons, as HOS_SW_A.. */
enum { IB_ADULT, IB_CHILD, IB_AGES };          /* the game's age index (PouchMgr's: 0 adult, 1 child) */
#define IB_NONE (-1)                           /* no item (the game's AssignableItem Empty) */
#define IB_ITEMS 54                            /* the game's AssignableItem values: 0 DekuStick .. 53 NormalLure */

/* ---- oot_item_buttons.c ---- */

int ib_enabled(void);                       /* the menu's Item assignable buttons */
enum { IB_HOTKEY_L, IB_HOTKEY_R };
int ib_hotkey(void);                        /* the menu's Item button hotkey */
int ib_age(Ctx *c);                         /* the age the game plays now, IB_ADULT or IB_CHILD */
int ib_assignment(int age, int button);     /* the item on a face button, or IB_NONE */
int ib_large(void);                         /* the hotkey is held where it works: the HUD's large arrangement */
unsigned ib_generation(void);               /* changes whenever an assignment does */

/* a call of a game function on the game's thread: x[0..nx) and s[0..ns) in, x0 out; the Ctx is put back as it was */
uint64_t ib_guest(Ctx *c, uint64_t fn, int nx, const uint64_t *x, int ns, const float *s);

/* The actor an item's icon and count go by now, as the HUD's own box looks it up (a bottle: its content's; the bow and
   the magic arrows: their own): the address of the game's string goes into the 8 guest bytes at slot, which is what the
   game's name arguments take. 0 when the item has none. */
int ib_item_name(Ctx *c, int item, uint64_t slot);
/* the item is in the pouch now (a bottle: the bottle itself; anything else: at least one of it); slot as above */
int ib_item_owned(Ctx *c, int item, uint64_t slot);

/* While set for this Ctx, ItemBtn::setItem's own read of the ZR slot answers item, so a box draws its bow or arrow as
   the ZR box would (the game picks that icon by what is on ZR). IB_NONE ends it. */
void ib_pin_slot(Ctx *c, int item);

/* a screen destroyed (hook 10, hos_oot_ib_screen_gone): the menus' guides, the pause menu's tab bar, the carousel's cells,
   the Items page's slots and the control guide forget their panes of it, the filter the pause menu's screen */
void ib_screen_gone(uint64_t screen);

/* ---- oot_item_buttons_hud.c ---- */

void ib_hud_tick(Ctx *c, uint64_t screen);  /* the HUD screen's frame, after its own update */

/* The face buttons' glyphs (a T_Assign_00 text pane each on the HUD and on the quick-switch menu's entries, a T_Icon_00 on
   the pause menu's Items page): glyph k's colour now, 1 and rgba with the Xbox prompts, 0 for the layout's cream; and a
   text pane's glyph colour (its material's white, linear rgba) read into was and set to rgba, each when not NULL. 0 when
   the pane has no colours. */
int ib_glyph_colour(int k, float rgba[4]);
int ib_glyph_white(Ctx *c, uint64_t pane, const float rgba[4], float was[4]);
/* the face buttons (IB_A..IB_Y) in the pad's east, south, west, north order, by the controls (the Switch's when the four are
   not the four face buttons, one each) */
void ib_face_order(int order[IB_BUTTONS]);
