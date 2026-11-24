# -*- coding: utf-8 -*-
"""
팰월드 호스트 변경기 — GUI판 (ko/en/zh/ja)
폴더 선택 → 캐릭터 목록에서 클릭 → [내 팰월드에 설치] 또는 [전달용 내보내기].
엔진은 host_changer.py 재사용 (왕복 바이트 일치 검증본).
"""
import datetime
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lang
from lang import t
from host_changer import (__version__, HOST_GUID, fix_group_blobs, patch_levelmeta, roster,
                          sav_compress_plz, sav_decompress, swap_host, swap_guids,
                          uid_to_filename, transplant_map, map_explored_ratio)

PAL_ROOT = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Pal", "Saved", "SaveGames")
# 백업은 SaveGames 밖에 둔다: 안에 두면 게임 월드 목록에 같은 월드가 여러 개 뜨고 스팀 클라우드로도 올라간다
BACKUP_ROOT = os.path.join(os.path.dirname(PAL_ROOT), "HostChangerBackups")
HEX32 = re.compile(r"^[0-9A-Fa-f]{32}$")
CREATE_NO_WINDOW = 0x08000000


def palworld_running():
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True,
                             creationflags=CREATE_NO_WINDOW).stdout
        return ("Palworld" in out) or ("Pal.exe" in out)
    except Exception:
        return False


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


# ───────────────── 엔진 오케스트레이션 (GUI 비의존, 테스트 가능) ─────────────────
def build_patched(src, t_uid, t_name, t_level, log):
    """새 호스트 기준의 파일셋 생성. returns (files: {상대경로: bytes}, copies: [상대경로])"""
    lv = sav_decompress(os.path.join(src, "Level.sav"))
    files, copies = {}, []
    pdir = os.path.join(src, "Players")

    if t_uid == HOST_GUID:
        log(t("already_host", name=t_name))
        files["Level.sav"] = sav_compress_plz(lv)
        for f in os.listdir(pdir):
            if f.lower().endswith(".sav"):
                copies.append(os.path.join("Players", f))
    else:
        t_file = os.path.join(pdir, uid_to_filename(t_uid) + ".sav")
        h_file = os.path.join(pdir, "0" * 31 + "1.sav")
        for p in (t_file, h_file):
            if not os.path.isfile(p):
                raise RuntimeError(t("err_player_file", path=p))
        log(t("log_swapping"))
        lv2, st = swap_host(lv, HOST_GUID, t_uid)
        log(t("log_swap_stats", identity=st["identity"], player_key=st["player_key"], name=t_name,
              to_host=st["target->host"], kept=st["pal_key_kept"]))
        if st["player_key"] == 0 and st["target->host"] == 0:
            raise RuntimeError(t("err_uid_missing"))
        lv2, grp = fix_group_blobs(lv2, HOST_GUID, t_uid)
        log(t("log_guild", report=grp))
        # 플레이어 .sav엔 팰키 센티넬이 없다 → 전체 스왑(swap_guids)
        h_gvas, _, _ = swap_guids(sav_decompress(h_file), HOST_GUID, t_uid)
        t_gvas, _, _ = swap_guids(sav_decompress(t_file), HOST_GUID, t_uid)
        files["Level.sav"] = sav_compress_plz(lv2)
        files[os.path.join("Players", "0" * 31 + "1.sav")] = sav_compress_plz(t_gvas)
        files[os.path.join("Players", uid_to_filename(t_uid) + ".sav")] = sav_compress_plz(h_gvas)
        for f in os.listdir(pdir):
            if f.lower().endswith(".sav") and f not in (os.path.basename(t_file), os.path.basename(h_file)):
                copies.append(os.path.join("Players", f))

    meta_path = os.path.join(src, "LevelMeta.sav")
    if os.path.isfile(meta_path):
        log(t("log_meta"))
        files["LevelMeta.sav"] = sav_compress_plz(
            patch_levelmeta(sav_decompress(meta_path), t_name, t_level))
    for f in ("WorldOption.sav", "LocalData.sav"):
        if os.path.isfile(os.path.join(src, f)):
            copies.append(f)
    return files, copies


def build_guest_restore(src, parked_uid, new_uid, log):
    """게스트 복원: 주차된 캐릭(parked_uid, 고레벨)을 새로 접속한 빈 UID(new_uid)로 옮긴다.
    둘 다 게스트(001 아님)라 팰키 센티넬(001) 미개입 → 전체 스왑으로 안전.
    returns (files, copies)."""
    if parked_uid == HOST_GUID or new_uid == HOST_GUID:
        raise RuntimeError(t("err_restore_host"))
    if parked_uid == new_uid:
        raise RuntimeError(t("err_same_char"))
    lv = sav_decompress(os.path.join(src, "Level.sav"))
    pdir = os.path.join(src, "Players")
    pf_par = os.path.join(pdir, uid_to_filename(parked_uid) + ".sav")
    pf_new = os.path.join(pdir, uid_to_filename(new_uid) + ".sav")
    if not os.path.isfile(pf_par):
        raise RuntimeError(t("err_parked_missing", file=os.path.basename(pf_par)))

    log(t("log_swapping_plain"))
    lv2, na, nb = swap_guids(lv, parked_uid, new_uid)
    log(t("log_moved", a=uid_to_filename(parked_uid)[:8], b=uid_to_filename(new_uid)[:8], n=na))
    if na == 0:
        raise RuntimeError(t("err_parked_uid"))
    lv2, grp = fix_group_blobs(lv2, parked_uid, new_uid)
    log(t("log_guild", report=grp))

    files, copies = {"Level.sav": sav_compress_plz(lv2)}, []
    # 주차 캐릭 파일 → 내부 uid를 new로, 파일명도 new
    par_gvas, _, _ = swap_guids(sav_decompress(pf_par), parked_uid, new_uid)
    files[os.path.join("Players", uid_to_filename(new_uid) + ".sav")] = sav_compress_plz(par_gvas)
    # 새로 접속한 빈 캐릭 파일이 있으면 주차 자리로(내부 uid parked) — 없으면 무시
    if os.path.isfile(pf_new):
        new_gvas, _, _ = swap_guids(sav_decompress(pf_new), parked_uid, new_uid)
        files[os.path.join("Players", uid_to_filename(parked_uid) + ".sav")] = sav_compress_plz(new_gvas)
    # 나머지 파일은 메모리로 읽어 files에 담는다 (src==설치대상일 때 백업 이동으로
    # 원본이 사라져도 안전하도록 copies 대신 files 사용).
    done = {uid_to_filename(parked_uid) + ".sav", uid_to_filename(new_uid) + ".sav"}
    for f in os.listdir(pdir):
        if f.lower().endswith(".sav") and f not in done:
            with open(os.path.join(pdir, f), "rb") as fh:
                files[os.path.join("Players", f)] = fh.read()
    for f in ("LevelMeta.sav", "WorldOption.sav", "LocalData.sav"):
        fp = os.path.join(src, f)
        if os.path.isfile(fp):
            with open(fp, "rb") as fh:
                files[f] = fh.read()
    return files, copies


def write_fileset(src, files, copies, out_dir, log):
    os.makedirs(os.path.join(out_dir, "Players"), exist_ok=True)
    for rel, data in files.items():
        p = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
    for rel in copies:
        p = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        shutil.copy2(os.path.join(src, rel), p)
    log(t("log_written", path=out_dir))


def install_to_savegames(src, files, copies, steam_root, world_id, log, backup_root=BACKUP_ROOT):
    target = os.path.join(steam_root, world_id)
    # 원본(src)이 설치 대상 자신이면 백업 이동 후 원본 경로가 사라진다
    # → 복사할 파일을 이동 전에 메모리로 읽어 둔다.
    if copies and os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(target)):
        files = dict(files)
        for rel in copies:
            with open(os.path.join(src, rel), "rb") as fh:
                files[rel] = fh.read()
        copies = []
    if os.path.isdir(target):
        bak = os.path.join(backup_root, os.path.basename(steam_root), f"{world_id}_{stamp()}")
        os.makedirs(os.path.dirname(bak), exist_ok=True)
        log(t("log_backup", name=bak))
        shutil.move(target, bak)
    write_fileset(src, files, copies, target, log)
    return target


# ───────────────────────────── GUI ─────────────────────────────
class App:
    def __init__(self, root):
        self.root = root
        root.geometry("760x600")
        root.minsize(720, 520)
        self.q = queue.Queue()
        self.src = None
        self.players = []      # [(uid, name, level)]
        self.busy = False
        self.build()
        self.root.after(100, self.poll)

    def apply_font(self):
        family = lang.FONTS[lang.current]
        for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
            try:
                tkfont.nametofont(name).configure(family=family)
            except tk.TclError:
                pass

    def build(self):
        """언어가 바뀌면 위젯을 통째로 다시 만든다 (상태는 self에 남아 있음)."""
        for w in self.root.winfo_children():
            w.destroy()
        self.apply_font()
        self.root.title(t("title", v=__version__))
        pad = {"padx": 10, "pady": 4}

        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=(6, 0))
        self.cb_lang = ttk.Combobox(top, values=list(lang.LANGS.values()), state="readonly", width=10)
        self.cb_lang.set(lang.LANGS[lang.current])
        self.cb_lang.pack(side="right")
        self.cb_lang.bind("<<ComboboxSelected>>", self.change_lang)
        ttk.Label(top, text="🌐 " + t("language")).pack(side="right", padx=4)

        # 1단계: 폴더
        f1 = ttk.LabelFrame(self.root, text=t("frame1"))
        f1.pack(fill="x", **pad)
        self.btn_pick = ttk.Button(f1, text=t("btn_pick"), command=self.pick_folder)
        self.btn_pick.pack(side="left", padx=8, pady=8)
        self.lbl_src = ttk.Label(f1, text=self.src or t("lbl_src_none"),
                                 foreground="#000" if self.src else "#666")
        self.lbl_src.pack(side="left", padx=4)

        # 2단계: 캐릭터
        f2 = ttk.LabelFrame(self.root, text=t("frame2"))
        f2.pack(fill="both", expand=True, **pad)
        cols = ("name", "level", "state")
        self.tree = ttk.Treeview(f2, columns=cols, show="headings", height=6, selectmode="browse")
        self.tree.heading("name", text=t("col_name"))
        self.tree.heading("level", text=t("col_level"))
        self.tree.heading("state", text=t("col_state"))
        self.tree.column("name", width=280)
        self.tree.column("level", width=70, anchor="center")
        self.tree.column("state", width=150, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)

        # 3단계: 설치 위치 + 버튼 (2x2 — 긴 번역도 잘리지 않게)
        f3 = ttk.LabelFrame(self.root, text=t("frame3"))
        f3.pack(fill="x", **pad)
        row = ttk.Frame(f3)
        row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text=t("lbl_account")).pack(side="left")
        self.cb_steam = ttk.Combobox(row, width=20, state="readonly")
        self.cb_steam.pack(side="left", padx=6)
        ttk.Label(row, text=t("lbl_world")).pack(side="left", padx=(12, 0))
        self.ent_world = ttk.Entry(row, width=34)
        self.ent_world.pack(side="left", padx=6, fill="x", expand=True)

        grid = ttk.Frame(f3)
        grid.pack(fill="x", padx=8, pady=8)
        grid.columnconfigure((0, 1), weight=1, uniform="b")
        self.btn_install = ttk.Button(grid, text=t("btn_install"), command=self.do_install)
        self.btn_export = ttk.Button(grid, text=t("btn_export"), command=self.do_export)
        self.btn_restore = ttk.Button(grid, text=t("btn_restore"), command=self.do_restore)
        # 맵 시야는 폴더 선택과 무관하게 언제나 쓸 수 있다
        self.btn_map = ttk.Button(grid, text=t("btn_map"), command=self.do_map)
        for i, b in enumerate((self.btn_install, self.btn_export, self.btn_restore, self.btn_map)):
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=2)

        # 로그
        f4 = ttk.LabelFrame(self.root, text=t("frame4"))
        f4.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(f4, height=8, state="disabled", font=(lang.FONTS[lang.current], 9))
        self.txt.pack(fill="both", expand=True, padx=8, pady=6)

        self.refresh_steam_ids()
        if self.src:
            base = os.path.basename(self.src)
            self.ent_world.insert(0, base if HEX32.match(base) else "")
        if self.players:
            self.fill_players(self.players)
        self.set_ready(bool(self.players))
        self.log(t("log_start"))

    def change_lang(self, _event=None):
        code = next(c for c, n in lang.LANGS.items() if n == self.cb_lang.get())
        if code == lang.current or self.busy:
            self.cb_lang.set(lang.LANGS[lang.current])
            return
        lang.current = code
        lang.save_lang(code)
        steam, world = self.cb_steam.get(), self.ent_world.get()
        self.build()
        if steam in self.cb_steam["values"]:
            self.cb_steam.set(steam)
        self.ent_world.delete(0, "end")
        self.ent_world.insert(0, world)

    # ── 유틸 ──
    def log(self, msg):
        self.q.put(("log", msg))

    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.txt.configure(state="normal")
                    self.txt.insert("end", payload + "\n")
                    self.txt.see("end")
                    self.txt.configure(state="disabled")
                elif kind == "players":
                    self.fill_players(payload)
                elif kind == "done":
                    self.busy = False
                    self.set_ready(bool(self.players))
                elif kind == "popup":
                    title, body = payload
                    messagebox.showinfo(title, body)
                elif kind == "error":
                    messagebox.showerror(t("err_title"), payload)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def set_ready(self, ok):
        st = "normal" if (ok and not self.busy) else "disabled"
        self.btn_install.configure(state=st)
        self.btn_export.configure(state=st)
        self.btn_restore.configure(state=st)
        # 맵 시야는 폴더 선택과 무관 — 작업 중만 아니면 항상 활성
        self.btn_map.configure(state="disabled" if self.busy else "normal")
        self.btn_pick.configure(state="disabled" if self.busy else "normal")
        self.cb_lang.configure(state="disabled" if self.busy else "readonly")

    def refresh_steam_ids(self):
        ids = []
        if os.path.isdir(PAL_ROOT):
            ids = [d for d in os.listdir(PAL_ROOT)
                   if d.isdigit() and os.path.isdir(os.path.join(PAL_ROOT, d))]
        self.cb_steam["values"] = ids
        if ids:
            self.cb_steam.current(0)

    # ── 1단계 ──
    def pick_folder(self):
        d = filedialog.askdirectory(title=t("dlg_pick_title"))
        if not d:
            return
        d = os.path.normpath(d)
        if not os.path.isfile(os.path.join(d, "Level.sav")):
            messagebox.showerror(t("err_title"), t("err_no_level"))
            return
        self.src = d
        self.lbl_src.configure(text=d, foreground="#000")
        base = os.path.basename(d)
        self.ent_world.delete(0, "end")
        self.ent_world.insert(0, base if HEX32.match(base) else "")
        self.players = []
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.busy = True
        self.set_ready(False)
        self.log(t("log_scan", path=d))
        threading.Thread(target=self.worker_scan, daemon=True).start()

    def worker_scan(self):
        try:
            lv = sav_decompress(os.path.join(self.src, "Level.sav"))
            self.log(t("log_decompressed", size=f"{len(lv):,}"))
            ppl = roster(lv)
            if not ppl:
                raise RuntimeError(t("err_no_players"))
            self.q.put(("players", ppl))
            self.log(t("log_found", n=len(ppl)))
        except Exception as ex:
            self.q.put(("error", f"{type(ex).__name__}: {ex}"))
        finally:
            self.q.put(("done", None))

    def fill_players(self, ppl):
        self.players = ppl
        for i in self.tree.get_children():
            self.tree.delete(i)
        for idx, (uid, name, lvv) in enumerate(ppl):
            state = t("state_host") if uid == HOST_GUID else ""
            self.tree.insert("", "end", iid=str(idx),
                             values=(name, lvv if lvv is not None else "?", state))
        # 호스트 아닌 첫 캐릭터 미리 선택
        for idx, (uid, _, _) in enumerate(ppl):
            if uid != HOST_GUID:
                self.tree.selection_set(str(idx))
                break

    # ── 3단계 ──
    def picked(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning(t("warn_select_title"), t("warn_select"))
            return None
        return self.players[int(sel[0])]

    def do_install(self):
        p = self.picked()
        if not p:
            return
        steam = self.cb_steam.get()
        world = self.ent_world.get().strip()
        if not steam:
            messagebox.showerror(t("err_title"), t("err_no_account", path=PAL_ROOT))
            return
        if not HEX32.match(world):
            messagebox.showerror(t("err_title"), t("err_world_id"))
            return
        if palworld_running():
            messagebox.showerror(t("running_title"), t("running"))
            return
        uid, name, lvv = p
        target = os.path.join(PAL_ROOT, steam, world)
        if not messagebox.askyesno(t("confirm_title"), t("confirm_install", name=name, lv=lvv, target=target)):
            return
        self.busy = True
        self.set_ready(False)
        threading.Thread(target=self.worker_apply, args=(p, "install", (os.path.join(PAL_ROOT, steam), world)), daemon=True).start()

    def do_export(self):
        p = self.picked()
        if not p:
            return
        world = self.ent_world.get().strip()
        if not HEX32.match(world):
            messagebox.showerror(t("err_title"), t("err_world_id"))
            return
        out_parent = filedialog.askdirectory(title=t("dlg_export_title"))
        if not out_parent:
            return
        self.busy = True
        self.set_ready(False)
        threading.Thread(target=self.worker_apply, args=(p, "export", (out_parent, world)), daemon=True).start()

    def worker_apply(self, p, mode, dest):
        try:
            uid, name, lvv = p
            self.log(t("log_make_host", name=name))
            files, copies = build_patched(self.src, uid, name, lvv, self.log)
            if mode == "install":
                steam_root, world = dest
                target = install_to_savegames(self.src, files, copies, steam_root, world, self.log)
                self.q.put(("popup", (t("done_title"), t("done_install", name=name, lv=lvv, target=target))))
            else:
                out_parent, world = dest
                out_dir = os.path.join(out_parent, world)
                if os.path.exists(out_dir):
                    out_dir = out_dir + "_" + datetime.datetime.now().strftime("%H%M%S")
                write_fileset(self.src, files, copies, out_dir, self.log)
                self.q.put(("popup", (t("done_title"), t("done_export", path=out_dir))))
            self.log(t("log_end"))
        except Exception as ex:
            self.q.put(("error", f"{type(ex).__name__}: {ex}"))
        finally:
            self.q.put(("done", None))

    # ── 게스트 캐릭터 복원 ──
    def do_restore(self):
        if not self.players:
            return
        steam = self.cb_steam.get()
        world = self.ent_world.get().strip()
        if not steam or not HEX32.match(world):
            messagebox.showerror(t("err_title"), t("err_check_account"))
            return
        dlg = tk.Toplevel(self.root)
        dlg.title(t("restore_title"))
        dlg.geometry("520x300")
        dlg.transient(self.root)
        dlg.grab_set()
        opts = [f"{nm}  (Lv.{lvv if lvv is not None else '?'})  [{uid_to_filename(uid)[:8]}]"
                for uid, nm, lvv in self.players]

        ttk.Label(dlg, text=t("restore_info"), justify="left").pack(padx=12, pady=(12, 8), anchor="w")
        ttk.Label(dlg, text=t("restore_src")).pack(anchor="w", padx=12)
        cb_src = ttk.Combobox(dlg, values=opts, state="readonly", width=60)
        cb_src.pack(padx=12, pady=(0, 8))
        ttk.Label(dlg, text=t("restore_dst")).pack(anchor="w", padx=12)
        cb_dst = ttk.Combobox(dlg, values=opts, state="readonly", width=60)
        cb_dst.pack(padx=12, pady=(0, 8))
        # 기본 추천: 최고레벨=src, 최저레벨=dst
        lv_list = [(i, (lvv or 0)) for i, (_, _, lvv) in enumerate(self.players)]
        if lv_list:
            cb_src.current(max(lv_list, key=lambda x: x[1])[0])
            cb_dst.current(min(lv_list, key=lambda x: x[1])[0])

        def go():
            si, di = cb_src.current(), cb_dst.current()
            if si < 0 or di < 0 or si == di:
                messagebox.showerror(t("err_title"), t("err_two_chars"), parent=dlg)
                return
            src_uid = self.players[si][0]
            dst_uid = self.players[di][0]
            if src_uid == HOST_GUID or dst_uid == HOST_GUID:
                messagebox.showerror(t("err_title"), t("err_restore_host_gui"), parent=dlg)
                return
            if palworld_running():
                messagebox.showerror(t("running_title"), t("running"), parent=dlg)
                return
            if not messagebox.askyesno(t("confirm_title"),
                    t("confirm_restore", a=self.players[si][1], lv=self.players[si][2], b=self.players[di][1]),
                    parent=dlg):
                return
            dlg.destroy()
            self.busy = True
            self.set_ready(False)
            threading.Thread(target=self.worker_restore,
                             args=(src_uid, dst_uid, os.path.join(PAL_ROOT, steam), world),
                             daemon=True).start()

        bar = ttk.Frame(dlg)
        bar.pack(pady=10)
        ttk.Button(bar, text=t("btn_run_restore"), command=go).pack(side="left", padx=6)
        ttk.Button(bar, text=t("btn_cancel"), command=dlg.destroy).pack(side="left", padx=6)

    # ── 맵 시야(탐색 안개) 가져오기 ──
    def do_map(self):
        dlg = tk.Toplevel(self.root)
        dlg.title(t("map_title"))
        dlg.geometry("680x360")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, justify="left", text=t("map_info")).pack(padx=12, pady=(12, 8), anchor="w")

        v_src = tk.StringVar()
        v_dst = tk.StringVar()
        v_mode = tk.StringVar(value="merge")

        f1 = ttk.Frame(dlg); f1.pack(fill="x", padx=12, pady=2)
        ttk.Label(f1, text=t("map_src")).pack(anchor="w")
        r1 = ttk.Frame(f1); r1.pack(fill="x")
        ttk.Entry(r1, textvariable=v_src).pack(side="left", fill="x", expand=True)
        ttk.Button(r1, text=t("btn_browse"), command=lambda: v_src.set(
            filedialog.askopenfilename(title=t("dlg_map_src"),
                                       filetypes=[("LocalData.sav", "LocalData.sav"), ("sav", "*.sav")]) or v_src.get()
        )).pack(side="left", padx=4)

        f2 = ttk.Frame(dlg); f2.pack(fill="x", padx=12, pady=(8, 2))
        ttk.Label(f2, text=t("map_dst")).pack(anchor="w")
        r2 = ttk.Frame(f2); r2.pack(fill="x")
        ttk.Entry(r2, textvariable=v_dst).pack(side="left", fill="x", expand=True)
        ttk.Button(r2, text=t("btn_browse"), command=lambda: v_dst.set(
            filedialog.askopenfilename(title=t("dlg_map_dst"), initialdir=PAL_ROOT,
                                       filetypes=[("LocalData.sav", "LocalData.sav"), ("sav", "*.sav")]) or v_dst.get()
        )).pack(side="left", padx=4)

        f3 = ttk.LabelFrame(dlg, text=t("map_mode"))
        f3.pack(fill="x", padx=12, pady=10)
        ttk.Radiobutton(f3, variable=v_mode, value="merge", text=t("map_merge")).pack(anchor="w", padx=8, pady=2)
        ttk.Radiobutton(f3, variable=v_mode, value="replace", text=t("map_replace")).pack(anchor="w", padx=8, pady=2)

        def go():
            s, d = v_src.get().strip(), v_dst.get().strip()
            if not (s and d):
                messagebox.showerror(t("err_title"), t("err_two_files"), parent=dlg); return
            if os.path.abspath(s) == os.path.abspath(d):
                messagebox.showerror(t("err_title"), t("err_same_file"), parent=dlg); return
            if palworld_running():
                messagebox.showerror(t("running_title"), t("running"), parent=dlg); return
            dlg.destroy()
            self.busy = True; self.set_ready(False)
            threading.Thread(target=self.worker_map, args=(s, d, v_mode.get() == "merge"),
                             daemon=True).start()

        bar = ttk.Frame(dlg); bar.pack(pady=6)
        ttk.Button(bar, text=t("btn_run"), command=go).pack(side="left", padx=6)
        ttk.Button(bar, text=t("btn_cancel"), command=dlg.destroy).pack(side="left", padx=6)

    def worker_map(self, src_path, dst_path, merge):
        try:
            self.log(t("log_map_head", mode=t("map_mode_merge" if merge else "map_mode_replace")))
            src = sav_decompress(src_path)
            dst = sav_decompress(dst_path)
            self.log(t("log_map_src", r=[f"{p:.1f}%" for _, _, p in map_explored_ratio(src)]))
            self.log(t("log_map_dst", r=[f"{p:.1f}%" for _, _, p in map_explored_ratio(dst)]))
            out, rep = transplant_map(dst, src, merge=merge)
            self.log(f"  {rep}")
            bak = f"{dst_path}_backup_{stamp()}"
            shutil.copy2(dst_path, bak)
            self.log(t("log_map_bak", name=os.path.basename(bak)))
            with open(dst_path, "wb") as fh:
                fh.write(sav_compress_plz(out))
            self.q.put(("popup", (t("done_title"), t("done_map", rep=rep, bak=os.path.basename(bak)))))
            self.log(t("log_end"))
        except Exception as ex:
            self.q.put(("error", f"{type(ex).__name__}: {ex}"))
        finally:
            self.q.put(("done", None))

    def worker_restore(self, src_uid, dst_uid, steam_root, world):
        try:
            self.log(t("log_restore_head", a=uid_to_filename(src_uid)[:8], b=uid_to_filename(dst_uid)[:8]))
            files, copies = build_guest_restore(self.src, src_uid, dst_uid, self.log)
            target = install_to_savegames(self.src, files, copies, steam_root, world, self.log)
            self.q.put(("popup", (t("done_title"), t("done_restore", target=target))))
            self.log(t("log_end"))
        except Exception as ex:
            self.q.put(("error", f"{type(ex).__name__}: {ex}"))
        finally:
            self.q.put(("done", None))


if __name__ == "__main__":
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()
