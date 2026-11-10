"""The item buttons in the game's layouts, made at the build (nx2/item_buttons_layout.py, with nx2/item_buttons_buil.py and
nx2/item_buttons_rules.py), on layouts and archives made up here: no game file.

- the dictionaries' key hash against CityHash64's own published values (cityhash's city-test.cc, the first 33 rows: lengths 0 to
  32 of its pseudo-random data), and a longer key refused;
- a layout written by hand (panes of each kind the generator meets: null, parts with a string list, picture and text with their
  drawables and materials, capture, alignment; an animation with targets and part links) read and written again byte for byte,
  held to the game's rules, and refused when a byte the schema does not know, a key's hash or the version is changed;
- panes added: a hidden group as the last child of a pane that ends at the last pane, parts in it (no pane moves); then copies
  put in among the panes: every pane after one moves up an index, and with it each place that keeps one (parents, ends, the
  parts' panes and their string lists, a text box's and a capture's pane, the animations' targets and part links), a copy has
  drawables, materials and records of its own; the file read back, the game's rules, every pane there was the pane it was and
  every animation driving what it drove; a part whose string list is not its index refused;
- the generator's four layouts on made-up ones: the HUD's group, boxes and the hint's copy; the menu's guides after its own in
  its row, hidden, the panes after them moved; the pause menu's in an alignment pane of their own (hidden, no margin,
  right-aligned, its bounds its children's alone, a third entry in the aligns) at the end of the overlay's bottom row, every
  pane there was as it was; an alignment entry for a pane of another kind, and an overlay whose row is no alignment pane,
  refused; the Items page's slot with its glyph's part (a PaGuideKey_00 part of its own, hidden, at its place and scale, the
  last child of N_All_00 and the last pane: nothing moves), and a slot whose N_All_00 does not hold its last pane, or
  holds no hit pane, refused;
- the archive rewrite on a made-up SARC with four copies of each layout: each changed layout in three copies in the room of its
  four, the game's size, three entries fewer, every other entry at its place with its bytes, the lookup finding every name; an
  archive with two entries on one range refused by the rules;
- the output and its stamp (size and SHA-256), an old stamp gone first;
- with zstandard: the script itself on a made-up RomFS (the archive in a zstd frame with a dictionary of its own), and one
  line and a non-zero exit on a RomFS without the archive.

python -I -B tests/test_item_buttons_layout.py
"""
import hashlib
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import item_buttons_buil as buil  # noqa: E402
import item_buttons_layout as gen  # noqa: E402
import item_buttons_rules as rules  # noqa: E402
import prompt_assets  # noqa: E402

M = (1 << 64) - 1
# city-test.cc's testdata[i][0], CityHash64(data + i * i, i) for i = 0..32 (the data: setup() below)
CITY = [0x9ae16a3b2f90404f, 0x541150e87f415e96, 0xf3786a4b25827c1, 0xef923a7a1af78eab, 0x11df592596f41d88, 0x831f448bdc5600b3,
        0x3eca803e70304894, 0x1b5a063fb4c7f9f1, 0xa0f10149a0e538d6, 0xfb8d9c70660b910b, 0x236827beae282a46, 0xc385e435136ecf7c,
        0xe3f6828b6017086d, 0x851fff285561dca0, 0x61152a63595a96d9, 0x44473e03be306c88, 0x3ead5f21d344056, 0x6abbfde37ee03b5b,
        0x943e7ed63b3c080, 0xd72ce05171ef8a1a, 0x4182832b52d63735, 0xd6cdae892584a2cb, 0x5c8e90bc267c5ee4, 0xbbd7f30ac310a6f3,
        0x36a097aa49519d97, 0xdc78cb032c49217, 0x441593e0da922dfe, 0x2ba3883d71cc2133, 0xf2b6d2adf8423600, 0x38fffe7f3680d63c,
        0xb7477bf0b9ce37c6, 0x55bdb0e71e3edebd, 0x782fa1b08b475e7]
# pane flags as the game's layouts have them, by kind (bits 7-9)
FLAGS = {"null": 0x02555003, "hidden": 0x0255500A, "picture": 0x02555089, "text": 0x02555109, "align": 0x02555189,
         "capture": 0x02555283, "parts": 0x02555313}
KIND = {"null": 0, "hidden": 0, "picture": 1, "text": 2, "align": 3, "capture": 5, "parts": 6}


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def city_data(n):
    """city-test.cc's setup(): its pseudo-random bytes"""
    a, b, out = 9, 777, bytearray()
    for i in range(n):
        a = (a + b) & M
        b = (b + a) & M
        a = ((a ^ (a >> 41)) * 0xC3A5C85C97CB3127) & M
        b = (((b ^ (b >> 41)) * 0xC3A5C85C97CB3127) + i) & M
        out.append(b >> 37 & 0xFF)
    return bytes(out)


def address(pane, prop, m=3):
    """an animation target's 5-byte address (and its NUL) for a pane's property"""
    return bytes((0x7F, (pane & 0xF) << 3 | 7, m << 5 | pane >> 4, prop, 0, 0))


def made_layout(name, panes, anims=()):
    """a .buil written by hand, laid out as the game's: panes [(name, parent, kind, options)] in tree order (each pane's end
    worked out), kind one of FLAGS; options: "flags", "layout" (a part's), "lists" (a part's string lists, "#" its own index),
    "subs" (a text pane's four materials after its own). anims [(name, [(pane, property)], [(part's animation, pane)])]. Every
    block at the alignment the reader gives its kind, every other dictionary empty, one alpha preset"""
    out, pool, strings = bytearray(0xF8), bytearray(b"\0"), []
    n = len(panes)
    end = list(range(1, n + 1))
    for i in reversed(range(n)):
        if panes[i][1] >= 0:
            end[panes[i][1]] = max(end[panes[i][1]], end[i])

    def s(text):   # (the pool: a NUL, the layout's name, "RootPane", ...: as prompt_assets.layout_copies finds a layout)
        enc = text.encode() + b"\0" if isinstance(text, str) else text
        at = pool.find(b"\0" + enc) if isinstance(text, str) else -1
        if at < 0:
            at = len(pool) - 1
            pool.extend(enc)
        return at + 1

    def put(data, align=8):
        out.extend(bytes(-len(out) % align))
        out.extend(data)
        return len(out) - len(data)

    def text(at, value):
        strings.append((at, s(value)))

    def array(at, ptr, count, size):
        struct.pack_into("<QII", out, at, ptr, count, size if count else 0)

    root = put(bytes(0x228))
    out[root:root + 4] = b"UIL\0"
    struct.pack_into("<I", out, root + 8, 0xCE)
    text(root + 0x18, name)
    kind = [KIND[p[2]] for p in panes]
    index = {}   # (each pane's entry in its kind's dictionary)
    of = {}
    for i, p in enumerate(panes):
        index[i] = len(of.setdefault(kind[i], []))
        of[kind[i]].append(i)
    drawn = [i for i in range(n) if kind[i] in (1, 2, 5)]
    draw = {i: j for j, i in enumerate(drawn)}
    mats, mat_of = [], {}
    for i in drawn:
        mat_of[i] = len(mats)
        mats += [0x10205] + list(panes[i][3].get("subs", ())) if kind[i] == 2 else [0x10100]

    def dictionary(at, keys, values, run=0, align=4):
        """values: a function placing the structs given the values block; run: a run of records of that size instead"""
        if not keys:
            z = put(bytes(0x20))
            struct.pack_into("<QQQII", out, root + at, z, z, z, 0, 8)
            return
        v, k = put(bytes(8 * len(keys))), put(bytes(8 * len(keys)))
        h = put(b"".join(struct.pack("<Q", buil.key_hash(key.encode())) for key in keys) + bytes(0x20))
        for i, key in enumerate(keys):
            text(k + 8 * i, key)
        struct.pack_into("<QQQII", out, root + at, k, v, h, len(keys), 8)
        if run:
            r = put(b"".join(values(i) for i in range(len(keys))), align)
            for i in range(len(keys)):
                struct.pack_into("<Q", out, v + 8 * i, r + run * i)
        else:
            for i in range(len(keys)):
                struct.pack_into("<Q", out, v + 8 * i, values(i))

    def record(i):
        p = panes[i]
        flags = p[3].get("flags", FLAGS[p[2]])
        return buil.PANE.pack(0, 0, 0, 0, 1, 1, 0, 10 * i, -10 * i, 0, p[1], 100, 100, end[i], flags,
                              draw.get(i, 0xFFFF), 0xFFFF, 0xFFFF, index[i])

    def drawable(j):
        d = put(bytes(0x40))
        struct.pack_into("<II4III", out, d + 0x10, 0x1C4BB1, mat_of[drawn[j]], 1, 1, 1, 1, 1, 0)
        return d

    def picture(j):
        q = put(bytes(0x18))
        struct.pack_into("<I", out, q + 0x10, draw[of[1][j]])
        return q

    def textbox(j):
        i = of[2][j]
        q = put(bytes(0xA8))
        text(q, "External_00")
        text(q + 0x18, "*")
        struct.pack_into("<II", out, q + 0x88, draw[i], i)
        return q

    def part(j):
        i = of[6][j]
        q, tail = put(bytes(buil.PART_SIZE)), put(bytes(0x10))
        text(q, panes[i][3].get("layout", "PaThing_00"))
        lists = panes[i][3].get("lists", [])
        if lists:
            offs = put(bytes(8 * len(lists)))
            array(q + 0x18, offs, len(lists), 8)
            for k, lst in enumerate(lists):
                head = put(bytes(0x10))
                struct.pack_into("<Q", out, offs + 8 * k, head)
                names = put(bytes(8 * len(lst)))
                array(head, names, len(lst), 8)
                for m, value in enumerate(lst):
                    text(names + 8 * m, str(i) if value == "#" else value)
        struct.pack_into("<QI", out, q + 0x38, tail, i)
        return q

    def anim(j):
        nm, targets, links = anims[j]
        a = put(bytes(0x30))
        clip = put(bytes(0x60))
        struct.pack_into("<Q", out, a, clip)
        text(clip, nm)
        struct.pack_into("<II", out, a + 0x28, 1, 0)
        if links:
            offs = put(bytes(8 * len(links)))
            array(a + 0x18, offs, len(links), 8)
            for k, (sub, pane) in enumerate(links):
                link = put(bytes(0x20))
                struct.pack_into("<Q", out, offs + 8 * k, link)
                text(link, sub)
                struct.pack_into("<II", out, link + 0x18, pane, 1)
        offs = put(bytes(8 * len(targets)))
        array(clip + 8, offs, len(targets), 8)
        for k, (pane, prop) in enumerate(targets):
            t = put(bytes(0x20))
            struct.pack_into("<Q", out, offs + 8 * k, t)
            text(t, address(pane, prop))
            struct.pack_into("<HHBBB", out, t + 8, 0xFFFF, k, 0, 1, 0xC)
        consts = put(struct.pack(f"<{len(targets)}f", *[1.0] * len(targets)), 4)
        array(clip + 0x38, consts, len(targets), 4)
        comps = put(bytes(len(targets)), 1)
        array(clip + 0x48, comps, len(targets), 1)
        struct.pack_into("<II", out, clip + 0x58, 0, 1)
        return a

    dictionary(0x20, [p[0] for p in panes], record, run=buil.PANE_SIZE)
    dictionary(0x40, [panes[i][0] for i in drawn], drawable)
    dictionary(0x60, [panes[i][0] for i in of.get(1, [])], picture)
    dictionary(0x80, [panes[i][0] for i in of.get(2, [])], textbox)
    dictionary(0xA0, [panes[i][0] for i in of.get(3, [])], lambda j: struct.pack("<fI", 0.0, 8), run=8)
    dictionary(0xC0, [panes[i][0] for i in of.get(6, [])], part)
    dictionary(0xE0, [panes[i][0] for i in of.get(5, [])], lambda j: struct.pack("<IIfI", 1, of[5][j], 1.0, 2), run=0x10)
    dictionary(0x100, [], None)
    if mats:
        offs = put(bytes(8 * len(mats)))
        array(root + 0x130, offs, len(mats), 8)
        for k, flags in enumerate(mats):
            m = put(bytes(0x88))
            struct.pack_into("<I", out, m + 0x60, flags)
            text(m + 0x78, "ui")
            struct.pack_into("<Q", out, offs + 8 * k, m)
    dictionary(0x140, [a[0] for a in anims], anim)
    for at in (0x160, 0x180, 0x1A8):
        dictionary(at, [], None)
    presets = put(bytes(8))
    array(root + 0x1E8, presets, 1, 8)
    struct.pack_into("<Q", out, presets, put(struct.pack("<5f", 1, 0, 0, 0, 1), 4))
    struct.pack_into("<2f", out, root + 0x200, 3840, 2160)
    if drawn:
        array(root + 0x208, put(bytes(4 * len(drawn)), 4), len(drawn), 4)
    d1 = len(out)
    for at, off in strings:
        struct.pack_into("<Q", out, at, d1 + off)
    out += pool
    out[0:0x28] = b"BFFH" + struct.pack("<IIIQIIQ", 0, len(out), 8, 0xA8, 2, 0x28, 0xF8)
    out[0x28:0x28 + len(buil.TYPE_NAME)] = buil.TYPE_NAME
    out[0xA8:0xD0] = b"BFSI" + struct.pack("<IIIQ", 0xF8, d1 - 0xF8, 8, 0xF8) + b"Default".ljust(16, b"\0")
    out[0xD0:0xF8] = b"BFSI" + struct.pack("<IIIQ", d1, len(pool), 1, d1) + b"StringPool".ljust(16, b"\0")
    return bytes(out)


SUBS = {"subs": (0xC00, 0xA00, 0x400, 0x600)}


def sarc_hash(name):
    h = 0
    for c in name.encode():
        h = (h * 0x65 + (c if c < 0x80 else c - 0x100)) & 0xFFFFFFFF
    return h


def made_sarc(files):
    """a SARC as the game's layout archives: [(name, bytes)], each an entry (copies too), by hash, every file at a multiple
    of 0x10 from the data's start, every name word numbered 1"""
    names, sfat, body = bytearray(), bytearray(), bytearray()
    for nm, blob in sorted(files, key=lambda f: sarc_hash(f[0])):
        body.extend(bytes(-len(body) % 16))
        sfat += struct.pack("<IIII", sarc_hash(nm), 0x01000000 | len(names) // 4, len(body), len(body) + len(blob))
        body.extend(blob)
        names += nm.encode() + b"\0"
        names += bytes(-len(names) % 4)
    table = b"SFAT" + struct.pack("<HHI", 0xC, len(files), 0x65) + sfat + b"SFNT" + struct.pack("<HH", 8, 0) + names
    data = -(-(0x14 + len(table)) // 16) * 16
    out = bytearray(b"SARC" + struct.pack("<HHIIHH", 0x14, 0xFEFF, 0, data, 0x100, 0) + table)
    out += bytes(data - len(out)) + body
    struct.pack_into("<I", out, 8, len(out))
    return bytes(out)


def hud(fill):
    """a made-up PlayerStatus_00: fill groups under RootPane, then N_All_00 with the right-hand group (the hint: four dots
    and a glyph; the ZR box) and the fishing group (hidden); an animation on the hint and one on the box"""
    panes = [("RootPane", -1, "null", {})] + [(f"N_Fill_{i:02d}", 0, "null", {}) for i in range(fill)]
    a = len(panes)
    panes += [("N_All_00", 0, "null", {}), ("N_ScaleR_00", a, "null", {}), ("N_Shortcut_00", a + 1, "null", {}),
              ("P_PageIcon_00", a + 2, "picture", {}), ("P_PageIcon_01", a + 2, "picture", {}),
              ("T_ShortCut_00", a + 2, "text", SUBS), ("P_PageIcon_02", a + 2, "picture", {}),
              ("P_PageIcon_03", a + 2, "picture", {}), (gen.BUTTON_LIKE, a + 1, "parts", {"layout": "PaItemBtn_00"}),
              (gen.GROUP_LIKE, a, "hidden", {})]
    return made_layout("PlayerStatus_00", panes, [("IsOpenShortCut", [(a + 2, 2)], []), ("InGauge", [(a + 8, 4)], [])])


def menu():
    """a made-up ShortCut_01: a picture and a capture, the fading group with a guide and the bottom row (an alignment pane)
    holding the game's guide, then two pictures after them; an animation on the group and one on the last picture"""
    guide = {"layout": "PaGuideKey_00", "lists": [["#"]]}
    panes = [("RootPane", -1, "null", {}), ("P_Bg_00", 0, "picture", {}), ("C_CaptureR_00", 0, "capture", {}),
             ("N_InOut_00", 0, "null", {}), ("Pa_Guide_02", 3, "parts", guide), (gen.ROW, 3, "align", {}),
             (gen.GUIDE_LIKE, 5, "parts", guide), ("P_MaskR_00", 0, "picture", {}), ("P_MaskL_00", 0, "picture", {})]
    return made_layout("ShortCut_01", panes, [("In", [(3, 4)], []), ("Mask", [(8, 4), (2, 0)], [("Sub", 6)])])


def overlay():
    """a made-up MenuOverlay_00: the header with an alignment pane (the rupees) and a picture in it, then the footer, its
    background and its bottom row (an alignment pane, the layout's last subtree) holding the game's five guides; an animation
    on the footer and one on the background"""
    guide = {"layout": "PaGuideKey_00"}
    panes = [("RootPane", -1, "null", {}), ("N_Header_00", 0, "null", {}), ("A_Rupee_00", 1, "align", {}),
             ("P_Icon_00", 2, "picture", {}), ("N_Footer_00", 0, "null", {}), ("W_GuideBg_00", 4, "picture", {}),
             (gen.FOOTER, 4, "align", {})] + [(f"Pa_Guide_{k:02d}", 6, "parts", guide) for k in range(5)]
    return made_layout("MenuOverlay_00", panes, [("FooterIn", [(4, 9)], []), ("Bg", [(5, 4)], [])])


def overlay_checks(old, new):
    """the pause menu's guides: an alignment pane of their own after the row's five, hidden, no margin, right-aligned, its
    bounds its children's alone; the five copies of the row's first guide in it, hidden; every pane there was as it was"""
    O, N = buil.Layout(old), buil.Layout(new)
    names, row = N.names(), N.names().index(gen.FOOTER)
    check(names == O.names() + [gen.GROUP_ASSIGN] + list(gen.GUIDES), f"the overlay's panes are {names}")
    g = names.index(gen.GROUP_ASSIGN)
    rec = N.pane(g)
    check(rec["parent"] == row and rec["flags"] == gen.GROUP_ASSIGN_FLAGS and rec["flags"] >> 7 & 7 == buil.KIND_ALIGN and
          not rec["flags"] & buil.VISIBLE and (rec["flags"] >> 3 & 3) == 2 and rec["index"] == 2 and rec["end"] == len(names),
          f"the group's record is {rec}")
    check(N.names(0xA0, "aligns") == ["A_Rupee_00", gen.FOOTER, gen.GROUP_ASSIGN], "the group is not the third align")
    run = N._dict_blocks(0xA0, "aligns")[1].ptrs[0][0]
    check(struct.unpack_from("<fI", run.data, 16) == (0.0, gen.ALIGN_RIGHT) and bytes(run.data[:16]) == bytes(
          O._dict_blocks(0xA0, "aligns")[1].ptrs[0][0].data), "the group's align entry, or the others' changed")
    check(all(N.pane(i)["parent"] == g and N.pane(i)["flags"] == gen.GUIDE_FLAGS for i in range(g + 1, len(names))),
          "the guides are not hidden in the group")
    check([N.pane(i)["end"] for i in (0, names.index("N_Footer_00"), row)] == [len(names)] * 3 and
          all(N.pane(i) == O.pane(i) for i in range(len(O.names())) if i not in (0, 4, row)),
          "a pane there was is not as it was (only the row's, the footer's and the root's ends grow)")
    same(old, new, "the overlay")
    try:   # (an alignment pane's entry for a pane of another kind)
        buil.Layout(old).add_align("A_Bad_00", row, FLAGS["null"], (0, 0), (1, 1), 0.0, 16)
        check(False, "an alignment entry was made for a null pane")
    except buil.LayoutError:
        pass
    try:   # (an overlay whose row is not an alignment pane)
        gen.overlay_guides(made_layout("MenuOverlay_00", [("RootPane", -1, "null", {}), (gen.FOOTER, 0, "null", {}),
                                                          (gen.GUIDE_LIKE, 1, "parts", {"layout": "PaGuideKey_00"})]))
        check(False, "an overlay whose bottom row is no alignment pane was taken")
    except buil.LayoutError:
        pass


def slot(after=False, hit="B_Hit_00"):
    """a made-up PaItemMenuBtn_00: N_All_00 holding the box (its hit pane, the base picture) and the item (the icon's part,
    the count's text pane) to the last pane (after: one more pane under RootPane after it); an animation on the base and
    the count, linking the icon part's State"""
    panes = [("RootPane", -1, "null", {}), (gen.SLOT_TOP, 0, "null", {}), ("N_BtnBase_00", 1, "null", {}),
             (hit, 2, "null", {}), ("P_Base_00", 2, "picture", {}), ("N_Item_00", 1, "null", {}),
             ("Pa_ReplaceIcon_00", 5, "parts", {"layout": "PaReplaceIcon_00"}), ("T_ItemNum_00", 5, "text", SUBS)]
    panes += [("N_After_00", 0, "null", {})] if after else []
    return made_layout(gen.SLOT, panes, [("ItemPattern", [(4, 1), (7, 1)], [("State", 6)])])


def slot_checks(old, new):
    """the slot's glyph: a PaGuideKey_00 part of its own, hidden, at its place and scale, the last child of N_All_00 and the
    last pane; every pane there was as it was"""
    O, N = buil.Layout(old), buil.Layout(new)
    names, top = N.names(), N.names().index(gen.SLOT_TOP)
    check(names == O.names() + [gen.BADGE], f"the slot's panes are {names}")
    rec = N.pane(len(names) - 1)
    check(rec["parent"] == top and rec["flags"] == gen.GUIDE_FLAGS and rec["flags"] >> 7 & 7 == buil.KIND_PARTS and
          not rec["flags"] & buil.VISIBLE and rec["at"] == gen.BADGE_AT and abs(rec["scale"][0] - gen.BADGE_SCALE) < 1e-6 and
          rec["end"] == len(names) and rec["index"] == 1, f"the glyph's record is {rec}")
    check(N.names(0xC0, "parts") == ["Pa_ReplaceIcon_00", gen.BADGE], "the glyph is not the slot's second part")
    part = N._entries(0xC0, "parts")[1][0]
    check(N.text(part.ptrs[0][1]) == gen.BADGE_PART and struct.unpack_from("<I", part.data, 0x40)[0] == len(names) - 1 and
          N._linked(part, 0x38) is not N._linked(N._entries(0xC0, "parts")[0][0], 0x38), "the glyph's part is not its own")
    check([N.pane(i)["end"] for i in (0, top)] == [len(names)] * 2 and
          all(N.pane(i) == O.pane(i) for i in range(len(O.names())) if i not in (0, top)),
          "a pane there was is not as it was (only the root's and N_All_00's ends grow)")
    same(old, new, "the slot")
    for bad, what in ((slot(after=True), "N_All_00 not holding the last pane"), (slot(hit="N_Hit_00"), "no hit pane")):
        try:
            gen.item_slot(bad)
            check(False, f"a slot with {what} was taken")
        except buil.LayoutError:
            pass


def plain(name):
    return made_layout(name, [("RootPane", -1, "null", {}), ("N_Pane_00", 0, "null", {})])


def same(old, new, what):
    """every pane of old is in new as it was, and every animation drives what it drove"""
    a, b = rules.shape(old), rules.shape(new)
    moved = [p for p, v in a["panes"].items() if b["panes"].get(p) != v]
    check(not moved and a["targets"] == b["targets"] and a["links"] == b["links"],
          f"{what}: panes moved {moved}, or the animations changed: {a['targets']} {b['targets']} {a['links']} {b['links']}")
    check(rules.layout(new) == [], f"{what} breaks the game's rules: {rules.layout(new)[:3]}")
    check(buil.Layout(new).write() == new, f"{what} does not come back byte for byte")


def tree(L):
    return [(L.pane(i)["parent"], L.pane(i)["end"]) for i in range(len(L.names()))]


def inserts():
    """copies and panes put in among the others, on a made-up layout with every kind of index the game keeps"""
    panes = [("RootPane", -1, "null", {}), ("N_A_00", 0, "null", {}), ("Pa_P_00", 1, "parts", {"lists": [["#"], ["#", "Pa_In"]]}),
             ("T_T_00", 1, "text", SUBS), ("C_C_00", 0, "capture", {}), ("N_B_00", 0, "null", {}), ("P_Q_00", 5, "picture", {}),
             ("Pa_R_00", 5, "parts", {"lists": [["#"]]})]
    lay = made_layout("Pa_Test_00", panes, [("Move", [(3, 1), (6, 1), (4, 4), (7, 2)], [("Sub", 2), ("Sub", 7)])])
    check(rules.layout(lay) == [], f"the made-up layout breaks the game's rules: {rules.layout(lay)}")
    # a parts pane copied into N_A_00, at its end (4): C_C_00, N_B_00, P_Q_00 and Pa_R_00 move up
    L = buil.Layout(lay)
    check(L.copy_pane(2, "Pa_P_01", 1) == 4, "the copy is not at N_A_00's end")
    one = L.write()
    N = buil.Layout(one)
    check(N.names() == ["RootPane", "N_A_00", "Pa_P_00", "T_T_00", "Pa_P_01", "C_C_00", "N_B_00", "P_Q_00", "Pa_R_00"],
          f"the panes are {N.names()}")
    check(tree(N) == [(-1, 9), (0, 5), (1, 3), (1, 4), (1, 5), (0, 6), (0, 9), (6, 8), (6, 9)], f"the tree is {tree(N)}")
    same(lay, one, "a parts pane put in")
    lists = {nm: [[N.text(t[1]) for _, t in sorted(N._linked(lst, 0).ptrs.items())] for lst in N._items(part, 0x18)]
             for nm, (part, _) in zip(N.names(0xC0, "parts"), N._entries(0xC0, "parts"))}
    check(lists == {"Pa_P_00": [["2"], ["2", "Pa_In"]], "Pa_R_00": [["8"]], "Pa_P_01": [["4"], ["4", "Pa_In"]]},
          f"the parts' string lists are {lists}")
    check(N.pane(4)["index"] == 2 and N.pane(4)["flags"] == FLAGS["parts"], "the copy is not the parts' third entry")
    # a text pane copied into N_B_00, at the end: a drawable, five materials and a text box of its own
    t = N.copy_pane(3, "T_T_01", 6)
    two = N.write()
    T = buil.Layout(two)
    check(t == 9 and T.names()[-1] == "T_T_01" and tree(T)[6] == (0, 10), "the text pane's copy is not N_B_00's last child")
    rec = T.pane(9)
    check(rec["drawable"] == 3 and rec["index"] == 1, f"the text pane's copy draws {rec['drawable']}, text box {rec['index']}")
    box = T._entries(0x80, "text boxes")[1][0]
    check(struct.unpack_from("<II", box.data, 0x88) == (3, 9), "the copy's text box names another drawable or pane")
    mats = T._items(T.root, 0x130)   # (the text pane's five, the capture's, the picture's, then the copy's five)
    check(len(mats) == 12 and [struct.unpack_from("<I", m.data, 0x60)[0] for m in mats[7:]] == [0x10205] + list(SUBS["subs"]),
          "the copy's five materials are not added")
    check(struct.unpack_from("<I", T._entries(0x40, "drawables")[3][0].data, 0x14)[0] == 7, "the copy's drawable's material")
    check(len(T._items(T.root, 0x130)[0].data) == 0x88 and mats[7] is not mats[0], "the copy's material is not its own")
    same(one, two, "a text pane copied")
    # a picture copied into N_A_00 again, and a null pane put in: the same, twice over
    P = buil.Layout(two)
    q = P.copy_pane(7, "P_Q_01", 1)
    g = P.add_pane("N_New_00", 1, FLAGS["hidden"], (1, 2), (3, 4), 0.5)
    three = P.write()
    check((q, g) == (5, 6) and buil.Layout(three).names()[5:8] == ["P_Q_01", "N_New_00", "C_C_00"], "the picture and the pane")
    same(two, three, "a picture copied and a pane put in")
    check(rules.shape(three)["targets"] == rules.shape(lay)["targets"], "the animations' targets moved")
    # a part whose string list is not its pane's index: refused when it would move
    bad = made_layout("Pa_Test_00", panes[:7] + [("Pa_R_00", 5, "parts", {"lists": [["3"]]})])
    try:
        buil.Layout(bad).copy_pane(2, "Pa_P_01", 1)
        check(False, "a part whose string list is not its index was moved")
    except buil.LayoutError:
        pass


def main():
    data = city_data(33 * 33 + 33)
    for i, want in enumerate(CITY):
        check(buil.key_hash(data[i * i:i * i + i]) == want, f"CityHash64 of {i} bytes is not city-test.cc's")
    try:
        buil.key_hash(b"x" * 33)
        check(False, "a 33-byte key was hashed")
    except buil.LayoutError:
        pass

    # ---- a layout by hand: read and written again; refused when changed where the schema says no
    lay = hud(2)
    L = buil.Layout(lay)
    check(L.write() == lay, "the hand-made layout does not come back byte for byte")
    check(rules.layout(lay) == [], f"the hand-made layout breaks the game's rules: {rules.layout(lay)}")
    hashes = struct.unpack_from("<Q", lay, 0xF8 + 0x30)[0]   # (the panes')
    gap = [k.off + len(k.data) for k, n in zip(L.order, L.order[1:]) if k.off + len(k.data) < n.off]   # (padding)
    check(gap, "the hand-made layout has no padding between blocks")
    for what, at in (("a byte in no block", gap[0]), ("a key's hash", hashes), ("the version", 0xF8 + 8)):
        bad = bytearray(lay)
        bad[at] ^= 1
        try:
            buil.Layout(bytes(bad))
            check(False, f"a layout with {what} changed was read")
        except buil.LayoutError:
            pass

    # ---- panes added: a hidden group, the last child of N_All_00 (which ends at the last pane), and two parts in it
    names = L.names()
    group = L.add_pane("N_Group_00", names.index("N_All_00"), FLAGS["hidden"], (1260, 820), (60, 80), 0.29)
    a = L.add_part("Pa_A_00", group, FLAGS["parts"], (380, 0), (380, 492), 1.0, "PaItemBtn_00")
    b = L.add_part("Pa_B_00", group, FLAGS["parts"], (0, -380), (380, 492), 1.0, "PaOther_00")
    new = L.write()
    N = buil.Layout(new)
    check(N.names() == names + ["N_Group_00", "Pa_A_00", "Pa_B_00"], f"the panes are {N.names()}")
    check(N.names(0xC0, "parts") == [gen.BUTTON_LIKE, "Pa_A_00", "Pa_B_00"], "the parts dictionary is not the three parts")
    check([N.pane(i)["parent"] for i in (group, a, b)] == [names.index("N_All_00"), group, group] and
          N.pane(0)["end"] == len(names) + 3 and N.pane(names.index("N_All_00"))["end"] == len(names) + 3, "the tree")
    g = N.pane(group)
    check((g["flags"], g["at"], g["index"]) == (FLAGS["hidden"], (1260, 820), 0) and abs(g["scale"][0] - 0.29) < 1e-6,
          f"the group's record is {g}")
    check([N.pane(i)["index"] for i in (a, b)] == [1, 2], "the parts panes are not the parts' entries 1 and 2")
    check(new.count(b"\0PaItemBtn_00\0") == 1, "the part's layout name is not shared with the one before")
    same(lay, new, "the group and its parts")
    inserts()

    # ---- the generator's layouts on made-up ones, then the archive: three copies in the room of four
    game_hud, game_menu = hud(80), menu()
    new_hud, new_menu = gen.item_buttons(game_hud), gen.menu_guides(game_menu)
    H, S = buil.Layout(new_hud), buil.Layout(new_menu)
    check(H.names()[-11:] == [gen.GROUP] + [n for n, _ in gen.BUTTONS] + list(gen.HINT.values()),
          "the HUD's new panes are not the group, the boxes and the hint")
    group = len(H.names()) - 11
    check(H.pane(group)["flags"] == gen.GROUP_FLAGS and not gen.GROUP_FLAGS & buil.VISIBLE, "the group is not hidden")
    hint = H.names().index("N_ItemButtonsHint_00")
    check(H.pane(hint)["parent"] == group and H.pane(hint)["at"] == gen.HINT_AT and H.pane(group)["end"] == len(H.names()),
          "the hint's copy is not the group's last child, above it")
    check(H.pane(H.names().index("T_ItemButtonsHint_00"))["parent"] == hint, "the hint's glyph is not in the hint")
    same(game_hud, new_hud, "the HUD")
    row = S.names().index(gen.ROW)
    check(S.names()[row + 1:row + 7] == [gen.GUIDE_LIKE] + list(gen.GUIDES) and S.names()[-2:] == ["P_MaskR_00", "P_MaskL_00"],
          f"the menu's panes are {S.names()}")
    check(all(S.pane(i)["parent"] == row and not S.pane(i)["flags"] & buil.VISIBLE for i in range(row + 2, row + 7)),
          "the guides are not hidden in the row")
    same(game_menu, new_menu, "the menu")
    game_overlay = overlay()
    new_overlay = gen.overlay_guides(game_overlay)
    overlay_checks(game_overlay, new_overlay)
    game_slot = slot()
    new_slot = gen.item_slot(game_slot)
    slot_checks(game_slot, new_slot)
    others = ["DoCommand_00", "PaItemBtn_00", gen.BADGE_PART] + list(prompt_assets.HINTS)
    files = [(n + ".buil", plain(n)) for n in others for _ in range(4)]
    files += [("PlayerStatus_00.buil", game_hud)] * 4 + [("ShortCut_01.buil", game_menu)] * 4
    files += [("MenuOverlay_00.buil", game_overlay)] * 4 + [(gen.SLOT + ".buil", game_slot)] * 4
    game = made_sarc(files)
    check(rules.check_archive(game) == [], f"the made-up archive breaks the rules: {rules.check_archive(game)}")
    out, lays = gen.build(game)
    new_lays = {"PlayerStatus_00": new_hud, "ShortCut_01": new_menu, "MenuOverlay_00": new_overlay, gen.SLOT: new_slot}
    changed = {nm + ".buil": lay for nm, lay in new_lays.items()}
    check({nm: lay for nm, (lay, _) in lays.items()} == new_lays and
          all(c == 3 for _, c in lays.values()) and len(out) == len(game), f"{lays.keys()}, {len(out)} bytes of {len(game)}")
    sg, so = rules.archive(game), rules.archive(out)
    check(len(so["entries"]) == len(files) - 4 and so["data"] == sg["data"], "not four entries fewer, the data where it was")
    kept = [(rules.name_of(out, so, w), st, en) for _, w, st, en in so["entries"]]
    was = [(rules.name_of(game, sg, w), st, en) for _, w, st, en in sg["entries"]]
    check([e for e in kept if e[0] not in changed] == [e for e in was if e[0] not in changed], "another file moved")
    check(all(out[so["data"] + st:so["data"] + en] == game[sg["data"] + st:sg["data"] + en] for nm, st, en in was
              if nm not in changed), "another file's bytes changed")
    for nm, lay in changed.items():
        mine = [(st, en) for n, st, en in kept if n == nm]
        check(len({st for st, _ in mine}) == 3 and all(out[so["data"] + st:so["data"] + en] == lay for st, en in mine),
              f"the entries of {nm} are not three copies of their own")
    problems = gen.check(game, out, new_lays)
    check(problems == [], f"the generator's checks: {problems}")
    check(gen.check(game, out, {"PlayerStatus_00": new_hud, "ShortCut_01": game_menu}) != [], "a layout not the one shipped passed")
    check(gen.check(game, out, dict(new_lays, MenuOverlay_00=game_overlay)) != [], "an overlay not the one shipped passed")
    check(gen.check(game, out, dict(new_lays, PaItemMenuBtn_00=game_slot)) != [], "a slot not the one shipped passed")
    shared = bytearray(game)   # (the second copy's entry on the first's bytes: relocated twice)
    first = [i for i, (nm, _, _) in enumerate(was) if nm == "PlayerStatus_00.buil"]
    struct.pack_into("<II", shared, sg["nodes"] + 0x10 * first[1] + 8, *was[first[0]][1:])
    check(any("share bytes" in p for p in rules.check_archive(bytes(shared))), "two entries on one range were taken")
    try:
        gen.same_size(game, "PlayerStatus_00.buil", game_hud * 5)
        check(False, "a layout larger than the room of its copies was placed")
    except buil.LayoutError:
        pass
    try:   # (the fishing group not hidden: not the layout known)
        gen.item_buttons(hud(0).replace(struct.pack("<I", FLAGS["hidden"]), struct.pack("<I", FLAGS["null"])))
        check(False, "a HUD whose fishing group is visible was taken")
    except buil.LayoutError:
        pass

    # ---- the output: the archive, then its stamp; an old stamp first gone
    with tempfile.TemporaryDirectory() as tmp:
        folder = os.path.join(tmp, "item_buttons")
        os.makedirs(folder)
        with open(os.path.join(folder, gen.STAMP), "w") as f:
            f.write("stale\n")
        gen.write(folder, out)
        check(sorted(os.listdir(folder)) == [gen.ARCHIVE, gen.STAMP], f"the folder holds {os.listdir(folder)}")
        check(Path(folder, gen.ARCHIVE).read_bytes() == out, "the archive written is not the one made")
        check(Path(folder, gen.STAMP).read_bytes() == f"{len(out)} {hashlib.sha256(out).hexdigest()}\n".encode(),
              "the stamp is not the archive's size and SHA-256")
        run_script(tmp, game, out)
    print(f"ok: CityHash64 of 0..32 bytes, a hand-made layout read and written, panes added and put in with every index kept "
          f"moved, {len(H.names())} panes in the HUD, {len(S.names())} in the menu, {len(buil.Layout(new_overlay).names())} in "
          f"the overlay and {len(buil.Layout(new_slot).names())} in the slot, 3 copies of each in the room of 4, "
          f"{len(so['entries'])} entries, the stamp")


def run_script(tmp, game, out):
    """the script itself: a made-up RomFS (Pack/ZsDic.pack.zs, a SARC holding zs.zsdic; the archive compressed with that
    dictionary), and one without the archive"""
    script = [sys.executable, "-I", "-B", str(ROOT / "nx2" / "item_buttons_layout.py")]
    empty = os.path.join(tmp, "empty")
    os.makedirs(empty)
    r = subprocess.run(script + ["--romfs", empty, "--out", os.path.join(tmp, "none")], capture_output=True, text=True)
    lines = r.stderr.strip().splitlines()
    check(r.returncode != 0 and len(lines) == 1 and lines[0].startswith("item buttons: ") and
          not os.path.exists(os.path.join(tmp, "none")), f"a RomFS without the archive: exit {r.returncode}, {r.stderr!r}")
    try:
        import zstandard
    except ImportError:
        print("(no zstandard: the script was run only on a RomFS without the archive)")
        return
    romfs = os.path.join(tmp, "romfs")
    dic = bytes(range(256)) * 16
    os.makedirs(os.path.join(romfs, "Pack"))
    with open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "wb") as f:
        f.write(zstandard.ZstdCompressor().compress(made_sarc([("zs.zsdic", dic)])))
    path = os.path.join(romfs, prompt_assets.LAYOUTS)
    os.makedirs(os.path.dirname(path))
    with open(path, "wb") as f:
        f.write(zstandard.ZstdCompressor(dict_data=zstandard.ZstdCompressionDict(dic)).compress(game))
    folder = os.path.join(tmp, "game", "item_buttons")
    r = subprocess.run(script + ["--romfs", romfs, "--out", folder], capture_output=True, text=True)
    check(r.returncode == 0 and Path(folder, gen.ARCHIVE).read_bytes() == out, f"the script: exit {r.returncode}, {r.stderr!r}")
    check(Path(folder, gen.STAMP).read_text().split()[0] == str(len(out)), "the script's stamp")


if __name__ == "__main__":
    main()
