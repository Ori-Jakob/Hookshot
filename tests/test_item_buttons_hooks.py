"""Item assignable buttons (host/oot_item_buttons.c, host/oot_item_buttons_hud.c) hook ten functions of the lifted game.

nx2/oot_patches.py's IB_HOOKS: each call goes first in its function, or right after one line of it (requestTransition's label,
bare or with the poll after it; Screen::calc's call of the screen's update; onBindItem's setInvalid), once, with its declaration
once in the file. A file without the function, or without that line once, is left alone; a file patched before is given back
as it is (a lift patched again). Screen::calc keeps the menus' hook first (tests/test_menu_hooks.py). apply makes them only in the
supported build's lift (protect_hearts), and warns for each one not found once. Where host/*.c defines a hook, it takes what
the lifted file's declaration says.

python -I -B tests/test_item_buttons_hooks.py
"""
import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

BEFORE = "    c->x[19]=c->x[0];\n    c->x[8]=recomp_load64(c,c->x[19] + 56);\n"
AFTER = "    c->x[0]=recomp_load64(c,c->x[19] + 8);\nreturn;\n}\n"
TICK = "    hos_oot_menu_tick(c, c->x[0]);"


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def function(hook, anchor=None):
    """the hook's function as the lift writes it (a made-up body), with its line when it goes after one"""
    _, head, anchors, _, _ = hook
    if anchor is None and anchors:
        anchor = anchors[0]
    return head + BEFORE + (anchor or "") + AFTER


def lifted(*functions):
    return '#include "a64.h"\n' + "".join(functions)


def proto(hook):
    """the function's declaration, as the files that call it have it: not its head"""
    return hook[1].replace("*__restrict A64_NOESC c) {\n", "*A64_NOESC);\n")


def line(hook):
    return "    " + hook[3] + "   /* (nx2/oot_patches.py: item buttons) */\n"


def hooked(hook):
    what, head, anchors, call, decl = hook
    for anchor in anchors or (None,):
        text = lifted(proto(hook), function(hook, anchor))
        out = oot_patches.patch_item_button(text, hook)
        check(out is not None and out.count(call) == 1, "the %s hook is not in its function once" % what)
        check((anchor or head) + line(hook) in out, "the %s hook is not %s" % (what, "after %r" % anchor if anchor else "first"))
        check(out.count(decl) == 1 and out.index(decl) < out.index(head), "the %s hook is not declared once, first" % what)
        check(out.replace(decl, "", 1).replace(line(hook), "", 1) == text, "the %s hook changed its function's body" % what)
        check(oot_patches.patch_item_button(out, hook) == out, "a file patched before got the %s hook again" % what)
    other = "void f_80000020(Ctx *__restrict A64_NOESC c) {\n"
    check(oot_patches.patch_item_button(lifted(function(hook).replace(head, other)), hook) is None,
          "a file without the %s hook's function was patched" % what)
    check(oot_patches.patch_item_button(lifted(proto(hook)), hook) is None, "a declaration got the %s hook" % what)
    if anchors:
        bare = lifted(head + BEFORE + AFTER)
        check(oot_patches.patch_item_button(bare, hook) is None, "the %s hook was made without its line" % what)
        twice = lifted(head + BEFORE + anchors[0] + BEFORE + anchors[0] + AFTER)
        check(oot_patches.patch_item_button(twice, hook) is None, "the %s hook was made at a line found twice" % what)
        after = lifted(head + BEFORE + AFTER + "void f_80000010(Ctx *__restrict A64_NOESC c) {\n" + anchors[0] + AFTER)
        check(oot_patches.patch_item_button(after, hook) is None, "the %s hook went after its line in another function" % what)


def screen_and_tick():
    """Screen::calc: the menus' hook first, the item buttons' after the screen's update, either made first"""
    hook = next(h for h in oot_patches.IB_HOOKS if h[1] == oot_patches.MENU_TICK_HEAD)
    text = lifted(function(hook))
    for out in (oot_patches.patch_item_button(oot_patches.patch_menu_tick(text), hook),
                oot_patches.patch_menu_tick(oot_patches.patch_item_button(text, hook))):
        check(out.count(TICK) == 1 and oot_patches.MENU_TICK_HEAD + TICK in out, "the menus' hook is not first in Screen::calc")
        check(out.count(hook[3]) == 1 and hook[2][0] + line(hook) in out, "the item buttons' hook is not after the update")
        check(oot_patches.patch_menu_tick(out) == out and oot_patches.patch_item_button(out, hook) == out,
              "Screen::calc patched again was changed")


def shared_file():
    """onBindItem, decide and initLayout are in one lifted file: three calls, three declarations, each once"""
    hooks = [h for h in oot_patches.IB_HOOKS if h[1].startswith(("void f_833e", "void f_8341"))]
    check(len(hooks) == 3, "decide, onBindItem and initLayout expected")
    out = lifted(*(function(h) for h in hooks))
    for h in hooks:
        out = oot_patches.patch_item_button(out, h)
    for h in hooks:
        check(out.count(h[3]) == 1 and out.count(h[4]) == 1, "the %s hook is not in a shared file once" % h[0])


def applied(gen, protect_hearts):
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        oot_patches.apply(gen, protect_hearts=protect_hearts)
    return log.getvalue()


def through_apply():
    hooks = oot_patches.IB_HOOKS
    with tempfile.TemporaryDirectory(prefix="item-buttons-") as gen:
        files = [Path(gen) / "code_000.c", Path(gen) / "code_001.c"]
        texts = [lifted(*(function(h) for h in hooks[:5])), lifted(*(function(h) for h in hooks[5:]))]
        for path, text in zip(files, texts):
            path.write_text(text, encoding="utf-8", newline="")
        log = applied(gen, False)
        check([p.read_text(encoding="utf-8") for p in files] == texts, "another build's lift got the item buttons' hooks")
        check("item buttons'" not in log, "another build's lift was looked at for the item buttons' hooks")
        log = applied(gen, True)
        made = "".join(p.read_text(encoding="utf-8") for p in files)
        for h in hooks:
            check(made.count(h[3]) == 1 and made.count(h[4]) == 1, "the supported build's lift has the %s hook not once" % h[0])
            check("the item buttons' %s hook in code_00" % h[0] in log, "no line for the %s hook" % h[0])
        check(made.count(TICK) == 1, "the menus' hook is not in Screen::calc beside the item buttons'")
        check("WARNING: the item buttons'" not in log, "a hook found once was warned about")
        before = [p.read_text(encoding="utf-8") for p in files]
        applied(gen, True)
        check([p.read_text(encoding="utf-8") for p in files] == before, "a second run changed the lift")
        files[1].write_text(lifted(*(function(h) for h in hooks[5:-1])), encoding="utf-8", newline="")
        log = applied(gen, True)
        check("WARNING: the item buttons' %s hook was found 0 times" % hooks[-1][0] in log, "no warning for a missing hook")


def host_definitions():
    """a hook defined in host/*.c takes the types its declaration in the lifted file gives (C does not check that at link)"""
    def types(params):   # (each parameter's type without its name: "Ctx *c" is Ctx*)
        out = []
        for p in params.split(","):
            m = re.fullmatch(r"(.*?[\w*])\s*\b\w+", " ".join(p.split()))
            out.append((m.group(1) if m else p).replace(" ", ""))
        return out
    defined = {}
    for path in sorted((ROOT / "host").glob("*.c")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"^(\w+)\s+(hos_oot_ib_\w+)\(([^)]*)\)\s*\{", text, re.M):
            defined.setdefault(m.group(2), []).append((path.name, m.group(1), types(m.group(3))))
    for h in oot_patches.IB_HOOKS:
        m = re.fullmatch(r"extern (\w+) (hos_oot_ib_\w+)\(([^)]*)\);\n", h[4])
        check(m is not None, "the %s hook's declaration is not one extern line" % h[0])
        for name, ret, params in defined.get(m.group(2), ()):
            check((ret, params) == (m.group(1), types(m.group(3))), "%s defines %s otherwise than the lifted file declares it"
                  % (name, m.group(2)))
        check(m.group(2) + "(" in h[3], "the %s hook calls another function than it declares" % h[0])


def main():
    check(len(oot_patches.IB_HOOKS) == 10 and len({h[1] + h[3] for h in oot_patches.IB_HOOKS}) == 10, "ten hooks expected")
    for hook in oot_patches.IB_HOOKS:
        hooked(hook)
    screen_and_tick()
    shared_file()
    through_apply()
    host_definitions()
    print("PASS: the item buttons' hooks go once where they belong, only in the supported build's lift")


if __name__ == "__main__":
    main()
