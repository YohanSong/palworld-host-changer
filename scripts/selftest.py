"""Self-test on a COPY of a real world save (the given folder is only read).

    python scripts\\selftest.py "<...>\\SaveGames\\<steamid>\\<32-char world id>"

Checks: player list, host change installed onto the opened folder itself, host change back
(every save file must be byte-identical to the original after decompression), export.
"""
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import host_changer as hc  # noqa: E402

_ld = importlib.machinery.SourceFileLoader("gui", os.path.join(ROOT, "src", "host_changer_gui.pyw"))
gui = importlib.util.module_from_spec(importlib.util.spec_from_loader("gui", _ld))
_ld.exec_module(gui)


def listing(folder):
    # the game's own backup\ subfolder is intentionally not carried over
    return sorted(r for r in (os.path.relpath(os.path.join(dp, f), folder)
                              for dp, _, fs in os.walk(folder) for f in fs)
                  if not r.lower().startswith("backup" + os.sep))


def decompressed(folder):
    return {r: hc.sav_decompress(os.path.join(folder, r)) for r in listing(folder) if r.lower().endswith(".sav")}


def main(orig):
    world = os.path.basename(os.path.normpath(orig))
    log = lambda m: None
    work = tempfile.mkdtemp(prefix="phc_selftest_")
    try:
        target = os.path.join(work, world)
        shutil.copytree(orig, target, ignore=shutil.ignore_patterns("backup"))
        files0, dec0 = listing(orig), decompressed(orig)
        magic = open(os.path.join(orig, "Level.sav"), "rb").read(12)[8:12].decode()
        ppl = hc.roster(dec0["Level.sav"])
        print(f"format {magic}, players {len(ppl)}: " + ", ".join(f"{n} Lv.{lv}" for _, n, lv in ppl))
        host = next(p for p in ppl if p[0] == hc.HOST_GUID)
        guest = next(p for p in ppl if p[0] != hc.HOST_GUID)

        files, copies = gui.build_patched(target, guest[0], guest[1], guest[2], log)
        gui.install_to_savegames(target, files, copies, work, world, log, backup_root=os.path.join(work, "_bak"))
        assert listing(target) == files0, "file set changed"
        ppl2 = hc.roster(hc.sav_decompress(os.path.join(target, "Level.sav")))
        assert next(p for p in ppl2 if p[0] == hc.HOST_GUID)[1] == guest[1], "new host is not the chosen character"
        back = next(p for p in ppl2 if p[0] == guest[0])
        assert back[1] == host[1], "old host not parked in the guest slot"
        print(f"[1] host -> {guest[1]}: OK")

        time.sleep(1.1)  # backup folder names have 1-second resolution
        files, copies = gui.build_patched(target, back[0], back[1], back[2], log)
        gui.install_to_savegames(target, files, copies, work, world, log, backup_root=os.path.join(work, "_bak"))
        dec2 = decompressed(target)
        diff = [k for k in dec0 if dec0[k] != dec2.get(k)]
        assert not diff, f"round trip differs: {diff}"
        print(f"[2] host -> {host[1]} again: all {len(dec0)} files byte-identical to the original")

        out = os.path.join(work, "export", world)
        files, copies = gui.build_patched(orig, guest[0], guest[1], guest[2], log)
        gui.write_fileset(orig, files, copies, out, log)
        assert listing(out) == files0, "export file set differs"
        print("[3] export: OK")
        print("PASS")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or not os.path.isfile(os.path.join(sys.argv[1], "Level.sav")):
        sys.exit(__doc__)
    main(sys.argv[1])
