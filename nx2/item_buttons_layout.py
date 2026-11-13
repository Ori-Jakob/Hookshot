"""(hookshot) The item buttons (host/oot_item_buttons.c, host/oot_item_buttons_hud.c): the game's layouts with four item boxes
added to the HUD and a key guide to the quick-switch menu and to the pause menu, made at the build from the user's RomFS.

    python -I nx2/item_buttons_layout.py --romfs <dir> --out <game folder>/item_buttons

Writes <out>/Common.blarc: UI/Layout2Archive/Common's layouts (a SARC of .buil layouts, uncompressed) with four changed:
- PlayerStatus_00, the HUD in play: a group N_ItemButtons_00 (a null pane, hidden, the last child of N_All_00) holding four
  PaItemBtn_00 parts, the game's own item box, one per face button: Pa_ItemButtonA_00, B, X, Y in the Switch's diamond; and
  after them a copy of the hint the game shows above its ZR box (N_Shortcut_00: four page dots and a glyph),
  N_ItemButtonsHint_00 with P_ItemButtonsDot_00..03 and T_ItemButtonsHint_00. The host shows the group while the feature is
  on, and places, scales and fills the boxes and the hint;
- ShortCut_01, the quick-switch menu: in its bottom guide row (A_Guide_01, an alignment pane: it lines its shown children up,
  centred, by what each draws) after the game's own guide (Pa_Guide_00, "Select"), five more of its kind (PaGuideKey_00: a word,
  then a glyph), hidden: Pa_GuideAssign_00 for the word and the hotkey's glyph, _01 for the plus and the east face button's
  glyph, _02.._04 for the south, west and north ones'. The host fills and shows them while the feature is on. They go in among
  the layout's panes, so the two after them and every index kept of those move up one (nx2/item_buttons_buil.py);
- MenuOverlay_00, the tab bar and the bottom guide row over the pause menu (and the Minus panel): the same five, in an alignment
  pane of their own with no margin, A_GuideAssign_00 (hidden; its bounds its shown children's alone), the last child of the
  row (A_FirstGuide_00, right-aligned, 90 between the game's guides), so no pane moves. The host shows them on the pause
  menu's Items page while the feature is on;
- PaItemMenuBtn_00, a slot of the pause menu's Items page (a part the page shows 24 times): a PaGuideKey_00 part of its own,
  Pa_AssignKey_00 (hidden, the last child of N_All_00 and the last pane, so no pane moves), whose glyph pane the host fills
  with the face button the slot's item is on and places on the corner of the slot's box. The part's word stays empty.
Then <out>/Common.blarc.stamp, its size and SHA-256, last: host/prompts.c serves the archive in place of the game's (with the
button prompts' runs written over it) only when the stamp is there, and keys its cache on the stamp.

The archive keeps the game's size, and every other layout its place and its bytes: the prompts' runs are offsets into the game's
archive, and a larger archive would need its entry in the resource size table raised. The game keeps four copies of each
layout; a changed one is larger, so three copies of it go into the room of the four, each on bytes of its own (the game
relocates every entry in place: nx2/item_buttons_rules.py), and the fourth entry goes.

Before anything is written the result goes through the game's own rules (nx2/item_buttons_rules.py): the relocation each layout
gets at load, the builder's reads of the pane tree and of every index kept of a pane, the dictionaries' hashes, the archive's
lookup and its entries' ranges; and each changed layout is held to the game's: every pane there was is there with its record,
under the same parent, and every animation drives what it drove. Anything not as expected stops it with one line and a non-zero
exit, and nothing is written. Needs zstandard (to read the RomFS) and nothing else.
"""
import argparse
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # (python -I leaves the script folder off)
import item_buttons_buil as buil   # noqa: E402
import item_buttons_rules as rules   # noqa: E402
import prompt_assets   # noqa: E402 (reading the RomFS, and the prompts' layouts)

ARCHIVE, STAMP = "Common.blarc", "Common.blarc.stamp"
LAYOUT, PART, PARENT = "PlayerStatus_00", "PaItemBtn_00", "N_All_00"
# the group: a null pane, hidden (flags bit 0 clear: as N_SubItemBaseFishing_00, the fishing sub items beside it under
# N_All_00), at (1260, 820) from N_All_00's centre, scale 0.29; its size as N_All_00's other groups'
GROUP, GROUP_FLAGS, GROUP_AT, GROUP_SIZE, GROUP_SCALE = "N_ItemButtons_00", 0x0255500A, (1260.0, 820.0), (60.0, 80.0), 0.29
GROUP_LIKE = "N_SubItemBaseFishing_00"
# the boxes: visible parts panes (as Pa_SelectItem_00, the ZR box, with its size), scale 1, A B X Y at the Switch's places in
# the group (y up)
BUTTONS = (("Pa_ItemButtonA_00", (380.0, 0.0)), ("Pa_ItemButtonB_00", (0.0, -380.0)), ("Pa_ItemButtonX_00", (0.0, 380.0)),
           ("Pa_ItemButtonY_00", (-380.0, 0.0)))
BUTTON_FLAGS, BUTTON_SIZE = 0x02555313, (380.0, 492.0)
BUTTON_LIKE = "Pa_SelectItem_00"
# the hint: N_Shortcut_00's panes copied, each named here, the group's last child, above the top box (the host places it)
HINT_FROM = "N_Shortcut_00"
HINT = {"N_Shortcut_00": "N_ItemButtonsHint_00", "P_PageIcon_00": "P_ItemButtonsDot_00", "P_PageIcon_01": "P_ItemButtonsDot_01",
        "T_ShortCut_00": "T_ItemButtonsHint_00", "P_PageIcon_02": "P_ItemButtonsDot_02", "P_PageIcon_03": "P_ItemButtonsDot_03"}
HINT_AT = (0.0, 580.0)
# the quick-switch menu's guides: copies of its own Pa_Guide_00 (a PaGuideKey_00 part with its overrides), hidden (as the
# HUD's Pa_MpGauge_00), the last children of its bottom row
MENU, ROW, GUIDE_LIKE = "ShortCut_01", "A_Guide_01", "Pa_Guide_00"
GUIDES = tuple(f"Pa_GuideAssign_{k:02d}" for k in range(5))
GUIDE_FLAGS = 0x02555313 & ~buil.VISIBLE
# the pause menu's: in the bottom row of the screen over it (MenuOverlay_00's A_FirstGuide_00: right-aligned, 90 between the
# game's guides, which it takes by the names Pa_Guide_00.. while they run on), an alignment pane of their own after the
# game's, hidden, with no margin, its bounds its shown children's alone (flags bit 4, not bit 3: hidden or empty it takes no
# room), holding copies of the row's Pa_Guide_00
OVERLAY, FOOTER = "MenuOverlay_00", "A_FirstGuide_00"
GROUP_ASSIGN, GROUP_ASSIGN_FLAGS, GROUP_ASSIGN_SIZE, ALIGN_RIGHT = "A_GuideAssign_00", 0x02555190, (60.0, 80.0), 16
# an Items page slot's glyph: a PaGuideKey_00 part (as PaEquipmentBtn_00's own Pa_Guide_00, a part in a part), hidden, the last
# child of the slot's N_All_00 (the group the page's ItemPattern moves with the box; its bounds its own rect alone, so the
# slots lined up in A_Arrow_00 keep their places), at a box's corner (the host places it by the slot's shape), scale 1.25: the
# glyph as large on the screen as the quick-switch menu's under its entries and the bottom row's
SLOT, SLOT_TOP, BADGE, BADGE_PART = "PaItemMenuBtn_00", "N_All_00", "Pa_AssignKey_00", "PaGuideKey_00"
BADGE_AT, BADGE_SIZE, BADGE_SCALE = (109.0, 117.0), (200.0, 200.0), 1.25


def item_buttons(lay):
    """PlayerStatus_00 (its bytes) with the group, the four boxes and the hint added: the new bytes"""
    L = buil.Layout(lay)
    names = L.names()
    for name, flags, like in ((GROUP_LIKE, GROUP_FLAGS, "a hidden null pane"), (BUTTON_LIKE, BUTTON_FLAGS, "a parts pane")):
        if name not in names or L.pane(names.index(name))["flags"] != flags:
            raise buil.LayoutError(f"{LAYOUT} has no {name} with the flags of {like} ({flags:#x})")
    if PARENT not in names or L.pane(names.index(PARENT))["flags"] >> 7 & 7 != buil.KIND_NULL:
        raise buil.LayoutError(f"{LAYOUT} has no null pane {PARENT}")
    src = names.index(HINT_FROM) if HINT_FROM in names else -1
    if src < 0 or [names[i] for i in range(src, L.pane(src)["end"])] != list(HINT):
        raise buil.LayoutError(f"{LAYOUT}'s {HINT_FROM} is not the dots and the glyph known")
    group = L.add_pane(GROUP, names.index(PARENT), GROUP_FLAGS, GROUP_AT, GROUP_SIZE, GROUP_SCALE)
    for name, at in BUTTONS:
        L.add_part(name, group, BUTTON_FLAGS, at, BUTTON_SIZE, 1.0, PART)
    made = {}
    for i in range(src, L.pane(src)["end"]):   # (a copy's parent: the copy of the original's parent)
        made[i] = L.copy_pane(i, HINT[names[i]], made.get(L.pane(i)["parent"], group), HINT_AT if i == src else None)
    return L.write()


def menu_guides(lay):
    """ShortCut_01 (its bytes) with the five guides in its bottom row: the new bytes"""
    L = buil.Layout(lay)
    names = L.names()
    row, like = (names.index(n) if n in names else -1 for n in (ROW, GUIDE_LIKE))
    if row < 0 or like < 0 or L.pane(row)["flags"] >> 7 & 7 != 3 or L.pane(like)["parent"] != row or \
            L.pane(like)["flags"] != GUIDE_FLAGS | buil.VISIBLE:
        raise buil.LayoutError(f"{MENU} has no alignment pane {ROW} holding its guide {GUIDE_LIKE}")
    for name in GUIDES:
        L.copy_pane(like, name, row, flags=GUIDE_FLAGS)
    return L.write()


def overlay_guides(lay):
    """MenuOverlay_00 (its bytes) with the five guides in an alignment pane of their own, the last of its bottom row: the new
    bytes"""
    L = buil.Layout(lay)
    names = L.names()
    row, like = (names.index(n) if n in names else -1 for n in (FOOTER, GUIDE_LIKE))
    if row < 0 or like < 0 or L.pane(row)["flags"] >> 7 & 7 != buil.KIND_ALIGN or L.pane(like)["parent"] != row or \
            L.pane(like)["flags"] != GUIDE_FLAGS | buil.VISIBLE:
        raise buil.LayoutError(f"{OVERLAY} has no alignment pane {FOOTER} holding its guide {GUIDE_LIKE}")
    group = L.add_align(GROUP_ASSIGN, row, GROUP_ASSIGN_FLAGS, (0.0, 0.0), GROUP_ASSIGN_SIZE, 0.0, ALIGN_RIGHT)
    for name in GUIDES:
        L.copy_pane(like, name, group, flags=GUIDE_FLAGS)
    return L.write()


def item_slot(lay):
    """PaItemMenuBtn_00 (its bytes) with its glyph's part, the last pane: the new bytes"""
    L = buil.Layout(lay)
    names = L.names()
    top = names.index(SLOT_TOP) if SLOT_TOP in names else -1
    if top < 0 or L.pane(top)["flags"] >> 7 & 7 != buil.KIND_NULL or L.pane(top)["end"] != len(names) or \
            "B_Hit_00" not in names[top:]:
        raise buil.LayoutError(f"{SLOT} has no null pane {SLOT_TOP} holding the slot to its last pane")
    L.add_part(BADGE, top, GUIDE_FLAGS, BADGE_AT, BADGE_SIZE, BADGE_SCALE, BADGE_PART)
    return L.write()


CHANGES = ((LAYOUT, item_buttons), (MENU, menu_guides), (OVERLAY, overlay_guides), (SLOT, item_slot))


def same_size(blarc, name, new):
    """the archive (bytes) with the entries of `name` on copies of `new` that fit into the room of the old ones, each its own
    range from the first old one's start, 0x10 apart; the entries left over go, the others and every byte of their files stay.
    The table shrinks by 0x10 a removed entry: the names after it move up with it (the entries point at them from the names'
    start) and zero bytes fill up to the data, which stays where it was"""
    s = rules.archive(blarc)
    ents, data = s["entries"], s["data"]
    mine = [i for i, (_h, w, _st, _en) in enumerate(ents) if rules.name_of(blarc, s, w) == name]
    if not mine or mine != list(range(mine[0], mine[0] + len(mine))):
        raise buil.LayoutError(f"{name} is not in the archive, or its entries are not one after another")
    lo, hi = min(ents[i][2] for i in mine), max(ents[i][3] for i in mine)
    if lo % 0x10 or any(st < hi and en > lo for i, (_h, _w, st, en) in enumerate(ents) if i not in mine):
        raise buil.LayoutError(f"another file lies in the room of {name}'s copies")
    step = -(-len(new) // 0x10) * 0x10
    copies = min(len(mine), (hi - lo - len(new)) // step + 1 if hi - lo >= len(new) else 0)
    if copies < 1:
        raise buil.LayoutError(f"{name} of {len(new)} bytes does not fit into the {hi - lo} bytes of its copies")
    out = bytearray(blarc)
    out[data + lo:data + hi] = bytes(hi - lo)
    kept = []
    for j in range(copies):
        out[data + lo + j * step:data + lo + j * step + len(new)] = new
        kept.append(ents[mine[j]][:2] + (lo + j * step, lo + j * step + len(new)))
    table = ents[:mine[0]] + kept + ents[mine[-1] + 1:]
    head = bytearray(blarc[:s["nodes"]])
    struct.pack_into("<H", head, 0x14 + 6, len(table))
    head += b"".join(struct.pack("<IIII", *e) for e in table) + blarc[s["sfnt"]:data]
    out[:data] = head + bytes(data - len(head))
    return bytes(out), copies


def check(game, out, lays):
    """the new archive (out) against the game's (game) and the game's rules: what is wrong, [] nothing. lays: {layout name: the
    new layout} of those changed"""
    problems = rules.check_archive(out)
    if len(out) != len(game):
        problems.append(f"{len(out)} bytes, the game's {len(game)}")
    sg, so = rules.archive(game), rules.archive(out)
    changed = {nm + ".buil" for nm in lays}
    old = [(rules.name_of(game, sg, w), st, en) for _h, w, st, en in sg["entries"]]
    new = [(rules.name_of(out, so, w), st, en) for _h, w, st, en in so["entries"]]
    if [e for e in old if e[0] not in changed] != [e for e in new if e[0] not in changed] or \
            any(game[sg["data"] + st:sg["data"] + en] != out[so["data"] + st:so["data"] + en] for nm, st, en in old
                if nm not in changed):
        problems.append("a layout other than those changed moved or changed")
    for nm, lay in lays.items():
        copies = [out[so["data"] + st:so["data"] + en] for n, st, en in new if n == nm + ".buil"]
        if not copies or any(c != lay for c in copies):
            problems.append(f"the entries of {nm} are not copies of its new layout")
        i = rules.lookup(game, sg, nm + ".buil")
        was, now = rules.shape(game[sg["data"] + old[i][1]:sg["data"] + old[i][2]]), rules.shape(lay)
        moved = [p for p, v in was["panes"].items() if now["panes"].get(p) != v]
        if moved:
            problems.append(f"{nm}: {moved[0]} is not the pane it was (its record or its parent)")
        if was["targets"] != now["targets"] or was["links"] != now["links"]:
            problems.append(f"{nm}: its animations no longer drive what they drove")
    for nm in sorted(changed | {PART + ".buil", BADGE_PART + ".buil"}):
        i = rules.lookup(out, so, nm)
        if i < 0 or new[i][0] != nm:
            problems.append(f"{nm} is not found by the game's lookup")
    # (the prompts' runs, offsets into the game's archive, still land on their layouts: host/prompts.c writes them over this)
    for nm in ("DoCommand_00",) + prompt_assets.HINTS:
        at = prompt_assets.layout_copies(game, nm)
        if not at or prompt_assets.layout_copies(out, nm) != at or any(game[a:z] != out[a:z] for a, z in at):
            problems.append(f"{nm}, a layout the button prompts write over, moved or changed")
    # (the new panes as the prompts' own reader finds them: by name, each record's parent, flags, place and scale)
    hud, menu, overlay, slot = lays.get(LAYOUT), lays.get(MENU), lays.get(OVERLAY), lays.get(SLOT)
    if hud:
        panes = prompt_assets.layout_panes(hud)
        names = list(panes)
        want = [(GROUP, names.index(PARENT) if PARENT in names else -1, GROUP_FLAGS, GROUP_AT, GROUP_SCALE)]
        want += [(nm, names.index(GROUP) if GROUP in names else -1, BUTTON_FLAGS, at, 1.0) for nm, at in BUTTONS]
        for nm, parent, flags, at, scale in want:
            rec = panes.get(nm)
            got = rec and struct.unpack_from("<2f", hud, rec + 0x10) + struct.unpack_from("<2f", hud, rec + 0x1C) + \
                struct.unpack_from("<i", hud, rec + 0x28) + struct.unpack_from("<I", hud, rec + 0x38)
            if got != struct.unpack("<4fiI", struct.pack("<4fiI", scale, scale, *at, parent, flags)):
                problems.append(f"{nm}: not the pane meant ({got})")
        hint = [names.index(nm) if nm in names else -1 for nm in HINT.values()]
        if hint != list(range(len(names) - len(HINT), len(names))) or \
                struct.unpack_from("<i", hud, panes[names[hint[0]]] + 0x28)[0] != names.index(GROUP):
            problems.append(f"the hint's copy is not the last child of {GROUP}")
    if menu:
        panes = prompt_assets.layout_panes(menu)
        names = list(panes)
        row = names.index(ROW) if ROW in names else -1
        got = [(names.index(nm) if nm in names else -1, struct.unpack_from("<i", menu, panes[nm] + 0x28) +
                struct.unpack_from("<I", menu, panes[nm] + 0x38) if nm in panes else None) for nm in (GUIDE_LIKE,) + GUIDES]
        if [g[0] for g in got] != list(range(row + 1, row + 2 + len(GUIDES))) or \
                any(g[1][0] != row or (g[1][1] & buil.VISIBLE) != (j == 0) for j, g in enumerate(got)):
            problems.append(f"the guides are not hidden after {GUIDE_LIKE} in {ROW}")
    if overlay:
        panes = prompt_assets.layout_panes(overlay)
        names = list(panes)
        new = [GROUP_ASSIGN] + list(GUIDES)
        got = [struct.unpack_from("<i", overlay, panes[nm] + 0x28) + struct.unpack_from("<I", overlay, panes[nm] + 0x38)
               if nm in panes else None for nm in new]
        if names[-len(new):] != new or None in got or got[0] != (names.index(FOOTER), GROUP_ASSIGN_FLAGS) or \
                any(g != (len(names) - len(new), GUIDE_FLAGS) for g in got[1:]):
            problems.append(f"the pause menu's guides are not hidden in {GROUP_ASSIGN}, the last of {FOOTER}")
    if slot:
        panes = prompt_assets.layout_panes(slot)
        names, rec = list(panes), panes.get(BADGE)
        got = rec and struct.unpack_from("<2f", slot, rec + 0x10) + struct.unpack_from("<2f", slot, rec + 0x1C) + \
            struct.unpack_from("<i", slot, rec + 0x28) + struct.unpack_from("<I", slot, rec + 0x38)
        top = names.index(SLOT_TOP) if SLOT_TOP in names else -1
        L = buil.Layout(slot)
        part = dict(zip(L.names(0xC0, "parts"), (blk for blk, _ in L._entries(0xC0, "parts")))).get(BADGE)
        link = part.ptrs.get(0) if part else None
        if names[-1:] != [BADGE] or got != struct.unpack("<4fiI", struct.pack("<4fiI", BADGE_SCALE, BADGE_SCALE, *BADGE_AT, top,
                                                                                GUIDE_FLAGS)) or \
                not link or link[0] != "str" or L.text(link[1]) != BADGE_PART:
            problems.append(f"{BADGE} is not a hidden {BADGE_PART} part, the last child of {SLOT}'s {SLOT_TOP}")
    return problems


def write(folder, blarc):
    """<folder>/Common.blarc, then its stamp (size and SHA-256), each written beside and moved over; an old stamp goes first,
    so a half-written archive never has one"""
    os.makedirs(folder, exist_ok=True)
    stamp, path = os.path.join(folder, STAMP), os.path.join(folder, ARCHIVE)
    if os.path.exists(stamp):
        os.remove(stamp)
    with open(path + ".part", "wb") as f:
        f.write(blarc)
    os.replace(path + ".part", path)
    with open(stamp + ".part", "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{len(blarc)} {hashlib.sha256(blarc).hexdigest()}\n")
    os.replace(stamp + ".part", stamp)


def build(game):
    """the game's archive (bytes) with the layouts of CHANGES changed: the new archive, {layout: (its new bytes, copies)}"""
    s = rules.archive(game)
    out, lays = game, {}
    for name, change in CHANGES:
        i = rules.lookup(game, s, name + ".buil")
        if i < 0:
            raise buil.LayoutError(f"no {name}.buil in {prompt_assets.LAYOUTS}")
        _h, _w, st, en = s["entries"][i]
        lay = change(game[s["data"] + st:s["data"] + en])
        out, copies = same_size(out, name + ".buil", lay)
        lays[name] = (lay, copies)
    return out, lays


def main():
    ap = argparse.ArgumentParser(description="the item buttons in the game's layouts (see the file's docstring)")
    ap.add_argument("--romfs", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        import zstandard
    except ImportError:
        raise SystemExit("item buttons: no zstandard: the game's layouts cannot be read")
    try:
        game = prompt_assets.read_zs(a.romfs, prompt_assets.LAYOUTS, prompt_assets.zs_dictionary(a.romfs))
    except (OSError, zstandard.ZstdError) as e:
        raise SystemExit(f"item buttons: {prompt_assets.LAYOUTS} could not be read ({e})")
    try:
        out, lays = build(game)
        problems = check(game, out, {nm: lay for nm, (lay, _) in lays.items()})
    except (buil.LayoutError, ValueError, IndexError, KeyError, struct.error) as e:
        raise SystemExit(f"item buttons: the game's layouts are not the ones known: {e}")
    if problems:
        raise SystemExit(f"item buttons: the new layouts would not load as meant: {problems[0]}"
                         + (f" (and {len(problems) - 1} more)" if len(problems) > 1 else ""))
    write(a.out, out)
    print("item buttons: " + ", ".join(f"{nm} in {copies} copies of {len(lay)} bytes" for nm, (lay, copies) in lays.items())
          + f" in {ARCHIVE} ({len(out)} bytes, as the game's)", file=sys.stderr)


if __name__ == "__main__":
    main()
