"""The Insert menu's Item assignable buttons rows (Controls tab, after Rumble strength): Item assignable buttons (Off,
On) and Item button hotkey (L, R), which the host reads as options 12 and 13 (host/oot_item_buttons.c).

The two rows, their labels and hints, gpu/vk/vk_menu.cpp's ini_key, menu_init's reading loop and row_fixed are compiled
from the source with stand-ins and run: the keys they are saved under, a hand-edited value clamped to the row, the
hotkey row fixed (shown dim, the arrows leave it alone) while Item assignable buttons is Off, and every hint ending
(measure_help walks them until nullptr). The renderer's option table answers 12 and 13 from the two rows, as numbers (a
name in vk_api.h would change the shader cache's stamp); only the feature's host files (and host/nn_hid.c's controller
read) read either, and nothing sets them.

    python -I -B tests/test_item_buttons_menu.py [--cxx g++]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]
ROWS = (("Item assignable buttons", "item_buttons"), ("Item button hotkey", "item_hotkey"))


def read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def block(text, marker):
    """text from marker to the end of the first {...} after it"""
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


FIXTURE = r"""
#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL %%d %%s\n", __LINE__, #x); std::exit(1); } } while (0)
%(options)s
Options opts;
%(tabs)s
%(row)s;
%(hints)s
%(onoff)s
%(tx_hotkey)s
%(hn_buttons)s
%(hn_hotkey)s
/* (row_fixed's other rows, the Upscaler's: never fixed here) */
bool filter_needed() { return true; }
unsigned upscalers_available() { return 1; }
int upscaler() { return 0; }
const char* dlss_preset_env() { return nullptr; }
namespace ur {
template <class... A> bool upscaler_fixed(A...) { return false; }
template <class... A> bool render_fixed(A...) { return false; }
template <class... A> bool model_fixed(A...) { return false; }
}
%(row_fixed)s
/* (menu_init reads the Output resolution row by its own parser: not one of these rows) */
static int parse_output(const char* text) { return std::atoi(text); }
Row rows[] = {
%(rows)s
};
%(ini_key)s
/* (menu_init's loop over one line of hookshot_options.ini) */
static void parse(const char* text) {
    char line[80];
    std::snprintf(line, sizeof line, "%%s", text);
    char* eq = std::strchr(line, '=');
    *eq = 0;
    %(loop)s
}
int main() {
    const Row &on = rows[0], &key = rows[1];
    CHECK(!std::strcmp(ini_key(on), "item_assignable_buttons") && !std::strcmp(ini_key(key), "item_button_hotkey"));
    for (const Row& r : rows) {
        CHECK(r.tab == TAB_CONTROLS && r.lo == 0 && r.hi == 1 && r.step == 1);   /* (two values: drawn as two halves) */
        CHECK(r.preset_exempt && !r.restart && r.cheat < 0 && !r.heading);   /* (a control, read as it changes) */
        CHECK(r.help && r.text && r.hint);
        for (int v = r.lo; v <= r.hi; v++) {   /* (measure_help's walk: each value's hints end) */
            int k = 0;
            while (r.hint(v, k)) CHECK(++k < 8);
            CHECK(k >= 1 && r.hint(v, -1));
        }
    }
    CHECK(!std::strcmp(on.text(0), "Off") && !std::strcmp(on.text(1), "On"));
    CHECK(!std::strcmp(key.text(0), "L") && !std::strcmp(key.text(1), "R"));
    CHECK(std::strcmp(on.hint(0, -1), on.hint(1, -1)));
    /* out of the box: Off, on L */
    CHECK(opts.item_buttons == 0 && opts.item_hotkey == 0);
    /* the ini: each key to its own row, clamped to 0..1; another key, or junk, changes nothing or reads as 0 */
    parse("item_assignable_buttons=1\n");
    CHECK(opts.item_buttons == 1 && opts.item_hotkey == 0);
    parse("item_button_hotkey=1\n");
    CHECK(opts.item_buttons == 1 && opts.item_hotkey == 1);
    parse("item_button_hotkey=-3\n");
    CHECK(opts.item_hotkey == 0);
    parse("item_button_hotkey=7\n");
    CHECK(opts.item_hotkey == 1);
    parse("item_buttons=0\n"), parse("item_hotkey=0\n");
    CHECK(opts.item_buttons == 1 && opts.item_hotkey == 1);
    parse("item_assignable_buttons=x\n");
    CHECK(opts.item_buttons == 0 && opts.item_hotkey == 1);
    /* Off: the hotkey's row is fixed, whatever its value, and its hint says what it waits for */
    for (int v = 0; v <= 1; v++) {
        opts.item_buttons = 0, opts.item_hotkey = v;
        CHECK(row_fixed(key.value) && !row_fixed(on.value));
        CHECK(std::strstr(key.hint(v, -1), "Item assignable buttons"));
        opts.item_buttons = 1;
        CHECK(!row_fixed(key.value) && !row_fixed(on.value));
        CHECK(!std::strstr(key.hint(v, -1), "Item assignable buttons"));
    }
    CHECK(std::strcmp(key.hint(0, -1), key.hint(1, -1)));   /* (On: the hint follows the button chosen) */
    std::printf("menu: item_assignable_buttons and item_button_hotkey, 0..1, Off/On and L/R; hotkey fixed while Off\n");
    return 0;
}
"""


def controls_order(menu):
    """the two rows on the Controls tab, in that order, right after Rumble strength"""
    table = block(menu, "Row rows[] = {")
    names = [m.groups() for m in re.finditer(r'\n    \{(TAB_\w+), "([^"]*)"', table)]
    controls = [name for tab, name in names if tab == "TAB_CONTROLS"]
    check("Rumble strength" in controls, "the Controls tab lost its Rumble strength row")
    at = controls.index("Rumble strength") + 1
    check(controls[at:at + 2] == [name for name, _ in ROWS],
          "the Controls tab does not have Item assignable buttons, then Item button hotkey, after Rumble strength: %s"
          % controls)
    for tab, name in names:
        check(tab == "TAB_CONTROLS" or name not in dict(ROWS), "%s is on %s, not the Controls tab" % (name, tab))


def menu_fixture(menu, header):
    rows = []
    start = menu.index("Row rows[] = {")
    for name, field in ROWS:
        found = re.search(r'\n    (\{TAB_CONTROLS, "%s", &opts\.%s, )' % (re.escape(name), field), menu[start:])
        check(found is not None, "the menu has no %s row for opts.%s" % (name, field))
        rows.append("    " + block(menu[start + found.start(1):], "{") + ",")
        check(menu.count('"%s"' % name) == 1, "the menu has two rows named %s" % name)
    hints = re.search(r"MENU_HINTS\(hn_item_buttons,.*?\)\n(?=\S)", menu, re.S)
    check(hints is not None, "the menu has no hn_item_buttons")
    onoff = re.search(r"^const char\* tx_onoff\(int v\) \{.*\}$", menu, re.M)
    check(onoff is not None, "the menu has no one-line tx_onoff")
    init = block(menu, "void menu_init(")
    loop = block(init, "for (Row& r : rows) {")
    check("ini_key(r)" in loop, "menu_init's options loop no longer reads rows by ini_key")
    first = re.search(r"void set_row\([^)]*\) \{\s*(?://[^\n]*\n\s*)*(\S[^\n]*)", menu)
    check(first is not None and first.group(1) == "if (row_fixed(r.value)) return;",
          "set_row does not leave a fixed row (and its saved value) alone before anything else")
    return FIXTURE % {
        "options": re.search(r"struct Options \{.*?\n\};", header, re.S).group(0),
        "tabs": re.search(r"enum MenuTab \{.*?\};", menu, re.S).group(0),
        "row": block(menu, "struct Row {"),
        "hints": menu[menu.index("/// A row's hints from a table"):menu.index("const char* tx_framegen(")],
        "onoff": onoff.group(0),
        "tx_hotkey": block(menu, "const char* tx_item_hotkey("),
        "hn_buttons": hints.group(0),
        "hn_hotkey": block(menu, "const char* hn_item_hotkey("),
        "row_fixed": block(menu, "bool row_fixed("),
        "rows": "\n".join(rows),
        "ini_key": block(menu, "const char* ini_key("),
        "loop": loop,
    }


def option_ids():
    """12 and 13 answered from the two rows, as numbers; no name or other reader takes them"""
    replay, api = read("gpu", "vk", "vk_replay.cpp"), read("gpu", "vk", "vk_api.h")
    table = block(replay, "t.option = [](int id) -> int {")
    for number, (name, field) in zip((12, 13), ROWS):
        check(re.search(r"\bid == %d(?:\) return | \? )opts\.%s\b" % (number, field), table),
              "vk_replay.cpp: option %d is not the menu's %s (opts.%s)" % (number, name, field))
        check(len(re.findall(r"\bid == %d\b" % number, table)) == 1, "vk_replay.cpp: option %d is read twice" % number)
    value = {}   # (every HOS_OPT_* enum: none may land on 12 or 13)
    for body in re.findall(r"enum \{([^}]*)\}", api):
        at = None
        body = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
        for item in (i.strip() for i in body.split(",")):
            m = re.match(r"(HOS_OPT_\w+)(?:\s*=\s*(\d+))?$", item)
            if not m:
                at = None
                continue
            at = int(m.group(2)) if m.group(2) else (at + 1 if at is not None else None)
            value[m.group(1)] = at
    taken = sorted(n for n, v in value.items() if v in (12, 13))
    check(not taken, "vk_api.h: %s also take option 12 or 13" % taken)
    readers, setters = set(), set()
    for folder in ("host", "gpu"):
        for path in (ROOT / folder).rglob("*.c*"):
            text = path.read_text(encoding="utf-8", errors="replace")
            name = path.relative_to(ROOT).as_posix()
            if re.search(r"\brx_option\(\s*1[23]\s*,", text):
                readers.add(name)
            if re.search(r"\brx_option_set\(\s*1[23]\s*,", text):
                setters.add(name)
    # (the feature's own files, and the controller's read in host/nn_hid.c, which may ask where the hotkey is)
    others = sorted(u for u in readers if not re.fullmatch(r"host/oot_item_buttons\w*\.c|host/nn_hid\.c", u))
    check(not others, "options 12 and 13 are read outside the item buttons' host files: %s" % others)
    check(not setters, "options 12 and 13 are the menu's, but are set from %s" % sorted(setters))


def docs():
    readme, guide = read("readme.md"), read("docs", "development.md")
    check("| | Rumble strength | Off, 25% to 150%, in steps of 25 | 100% |\n"
          "| | Item assignable buttons | Off, On | Off |\n"
          "| | Item button hotkey | L, R (used while Item assignable buttons is On) | L |\n" in readme,
          "readme.md's option table does not have the two rows after Rumble strength")
    check("item_buttons.ini" in readme, "readme.md does not say where the items are kept")
    for key in ("item_assignable_buttons", "item_button_hotkey"):
        check(re.search(r"^\| `%s` \|" % key, guide, re.M), "docs/development.md's options table has no %s" % key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    args = parser.parse_args()
    menu, header = read("gpu", "vk", "vk_menu.cpp"), read("gpu", "vk", "vk_menu.h")
    controls_order(menu)
    option_ids()
    docs()
    with tempfile.TemporaryDirectory(prefix="item-buttons-menu-") as tmp:
        src, exe = Path(tmp) / "item_buttons_menu.cpp", Path(tmp) / "item_buttons_menu"
        src.write_text(menu_fixture(menu, header), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: the menu's Item assignable buttons rows, saved, fixed while Off, and options 12 and 13")


if __name__ == "__main__":
    main()
