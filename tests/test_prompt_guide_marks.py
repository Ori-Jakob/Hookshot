"""The control guide's comma and plus in the button prompts' font (nx2/prompt_assets.py guide_marks), on fonts made up here: no
game file.

A made-up icon font, as faces_font leaves it (CFF, 1000 units an em, nominalWidthX 707 as the game's External font, each Switch
button's and d-pad icon's code point a glyph of its own, the pad icons at U+F700 on), and a made-up text font with a space, a
comma and a plus of CetraDisplayPro-Regular's metrics (192; 234, ink 10..164 x -156..92; 564, ink 50..514 x 78..546). The font
guide_marks makes maps U+002C to a comma of advance 282 (the glyph at the guide's word size, 1.17 x 48 / 102 of the text font's,
and a word space after it, 1.7 x 48 / 102 of the text font's space) on the baseline, and U+002B to a plus of advance 618 (a word
space either side) centred on the icons' middle (300), each charstring's width the same as hmtx's; every other code point keeps
its glyph and advance, and each Switch button's and d-pad icon's code point keeps a cmap segment of its own (host/prompts.c
points those at the face's icons by their idDelta). A text font without a comma is a KeyError, which main takes as the guide
keeping its spaces.

python -I -B tests/test_prompt_guide_marks.py   (needs fontTools)
"""
import io
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))

try:
    import fontTools  # noqa: F401
except ImportError:
    fontTools = None


def made_font(glyphs, cmap, nominal=0):
    """a CFF font: glyphs {name: (advance, ink rect or None)}, cmap {code: name}; its charstrings' widths less nominal, its
    nominalWidthX"""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    fb = FontBuilder(1000, isTTF=False)
    order = [".notdef"] + list(glyphs)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    strings, metrics = {}, {}
    for name in order:
        advance, rect = glyphs.get(name, (500, None))
        pen = T2CharStringPen(advance - nominal, None)
        if rect:
            x0, y0, x1, y1 = rect
            pen.moveTo((x0, y0)), pen.lineTo((x1, y0)), pen.lineTo((x1, y1)), pen.lineTo((x0, y1)), pen.closePath()
        strings[name] = pen.getCharString()
        metrics[name] = (advance, rect[0] if rect else 0)
    fb.setupCFF("Made", {"FullName": "Made"}, strings, {"nominalWidthX": nominal} if nominal else {})
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Made", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    out = io.BytesIO()
    fb.save(out)
    return out.getvalue()


def segments(otf):
    """the font's format 4 cmap segments: [(start, end)]"""
    from fontTools.ttLib import TTFont
    data = TTFont(io.BytesIO(otf)).reader["cmap"]
    n, = struct.unpack_from(">H", data, 2)
    for i in range(n):
        off, = struct.unpack_from(">I", data, 4 + 8 * i + 4)
        if struct.unpack_from(">H", data, off)[0] == 4:
            segs = struct.unpack_from(">H", data, off + 6)[0] // 2
            ends = struct.unpack_from(f">{segs}H", data, off + 14)
            starts = struct.unpack_from(f">{segs}H", data, off + 16 + 2 * segs)
            return list(zip(starts, ends))
    return []


@unittest.skipIf(fontTools is None, "no fontTools")
class GuideMarksTests(unittest.TestCase):
    def test_comma_and_plus(self):
        import prompt_assets as pa
        from fontTools.pens.boundsPen import BoundsPen
        from fontTools.ttLib import TTFont
        own = list(pa.SWITCH) + list(pa.STATIC)   # (the codes with segments of their own)
        icons = {f"icon_{i}": (640 + 40 * (i % 3), (40, 19, 600, 583)) for i in range(len(own) + len(pa.PADS))}
        names = list(icons)
        cmap = {c: names[i] for i, c in enumerate(own)}
        cmap.update({pa.PAD_BASE + i: names[len(own) + i] for i in range(len(pa.PADS))})
        icon_font = made_font(icons, cmap, nominal=707)   # (the game's External font's nominalWidthX)
        text_font = made_font({"space": (192, None), "comma": (234, (10, -156, 164, 92)), "plus": (564, (50, 78, 514, 546))},
                              {0x20: "space", 0x2C: "comma", 0x2B: "plus"})

        out = pa.guide_marks(icon_font, text_font)
        font = TTFont(io.BytesIO(out))
        got, gset, hmtx = font.getBestCmap(), font.getGlyphSet(), font["hmtx"]

        def charstring_width(code):
            """the advance the glyph's charstring holds (its width operand and nominalWidthX), as a CFF reader takes it"""
            from fontTools.misc.psCharStrings import T2WidthExtractor
            cs = font["CFF "].cff.topDictIndex[0].CharStrings[got[code]]
            p = cs.private
            ex = T2WidthExtractor(getattr(p, "Subrs", []), cs.globalSubrs, p.nominalWidthX, p.defaultWidthX)
            ex.execute(cs)
            return ex.width

        def ink(code):
            b = BoundsPen(gset)
            gset[got[code]].draw(b)
            return b.bounds

        scale = 1.17 * 48 / 102
        self.assertEqual(hmtx[got[0x2C]][0], 282, "the comma's advance is not the word's comma and a word space")
        self.assertEqual(hmtx[got[0x2B]][0], 618, "the plus's advance is not the word's plus and a word space each side")
        for code in (0x2C, 0x2B):
            self.assertEqual(charstring_width(code), hmtx[got[code]][0],
                             f"U+{code:04X}'s charstring holds another advance than hmtx's (its width less nominalWidthX)")
        self.assertEqual(charstring_width(pa.SWITCH[0]), hmtx[got[pa.SWITCH[0]]][0], "the made-up font's own widths are off")
        x0, y0, x1, y1 = ink(0x2C)
        for a, b in ((x0, 10 * scale), (y0, -156 * scale), (x1, 164 * scale), (y1, 92 * scale)):
            self.assertAlmostEqual(a, b, delta=1, msg="the comma is not the word's, on the baseline")
        x0, y0, x1, y1 = ink(0x2B)
        self.assertAlmostEqual(x0, 154 + 50 * scale, delta=1, msg="the plus has no word space before it")
        self.assertAlmostEqual(x1 - x0, 464 * scale, delta=1, msg="the plus is not at the word's size")
        self.assertAlmostEqual((y0 + y1) / 2, 300, delta=1, msg="the plus is not centred on the icons")
        before = TTFont(io.BytesIO(icon_font))
        for code, name in before.getBestCmap().items():
            self.assertEqual(got.get(code), name, f"U+{code:04X} moved")
            self.assertEqual(hmtx[got[code]], before["hmtx"][name], f"U+{code:04X}'s advance changed")
        self.assertEqual(set(got) - set(before.getBestCmap()), {0x2C, 0x2B}, "other code points were added")
        segs = segments(out)
        for code in own:
            self.assertIn((code, code), segs, f"U+{code:04X} lost its own segment (host/prompts.c binds by it)")

    def test_text_font_without_the_marks(self):
        """a text font without a comma: KeyError, which main takes as the guide keeping its spaces (the faces' font still
        made)"""
        import prompt_assets as pa
        icons = {f"icon_{i}": (640, (40, 19, 600, 583)) for i in range(len(pa.SWITCH))}
        icon_font = made_font(icons, {c: f"icon_{i}" for i, c in enumerate(pa.SWITCH)})
        text_font = made_font({"space": (192, None), "plus": (564, (50, 78, 514, 546))}, {0x20: "space", 0x2B: "plus"})
        with self.assertRaises(KeyError):
            pa.guide_marks(icon_font, text_font)
        main = (ROOT / "nx2" / "prompt_assets.py").read_text(encoding="utf-8").split("def main():", 1)[1]
        self.assertIn("plain = guide_marks(plain, cetra)\n        except (KeyError, ValueError, IndexError, struct.error)", main,
                      "main does not go on without the marks when the text font lacks them")


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
