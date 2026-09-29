# -*- coding: utf-8 -*-
"""
팰월드 호스트 변경기 — GUI판
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
from tkinter import filedialog, messagebox, ttk

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from host_changer import (__version__, HOST_GUID, fix_group_blobs, patch_levelmeta, roster,
                          sav_compress_plz, sav_decompress, swap_host, swap_guids,
                          uid_to_filename, transplant_map, map_explored_ratio)

PAL_ROOT = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Pal", "Saved", "SaveGames")
HEX32 = re.compile(r"^[0-9A-Fa-f]{32}$")
CREATE_NO_WINDOW = 0x08000000


def palworld_running():
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True,
                             creationflags=CREATE_NO_WINDOW).stdout
        return ("Palworld" in out) or ("Pal.exe" in out)
    except Exception:
        return False


# ───────────────── 엔진 오케스트레이션 (GUI 비의존, 테스트 가능) ─────────────────
def build_patched(src, t_uid, t_name, t_level, log):
    """새 호스트 기준의 파일셋 생성. returns (files: {상대경로: bytes}, copies: [상대경로])"""
    lv = sav_decompress(os.path.join(src, "Level.sav"))
    files, copies = {}, []
    pdir = os.path.join(src, "Players")

    if t_uid == HOST_GUID:
        log(f"'{t_name}' 이미 호스트 — 겉표지만 갱신")
        files["Level.sav"] = sav_compress_plz(lv)
        for f in os.listdir(pdir):
            if f.lower().endswith(".sav"):
                copies.append(os.path.join("Players", f))
    else:
        t_file = os.path.join(pdir, uid_to_filename(t_uid) + ".sav")
        h_file = os.path.join(pdir, "0" * 31 + "1.sav")
        for p in (t_file, h_file):
            if not os.path.isfile(p):
                raise RuntimeError(f"플레이어 파일 없음: {p}")
        log("UID 맞교환 중 (Level.sav) — 팰 키 보존형...")
        lv2, st = swap_host(lv, HOST_GUID, t_uid)
        log(f"  신원 {st['identity']} / 플레이어키 {st['player_key']} / {t_name}→001 {st['target->host']} / 팰키보존 {st['pal_key_kept']}")
        if st['player_key'] == 0 and st['target->host'] == 0:
            raise RuntimeError("대상 캐릭터 UID가 월드에 없음")
        lv2, grp = fix_group_blobs(lv2, HOST_GUID, t_uid)
        log(f"  길드(거점 소유) 보정: {grp}")
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
        log("선택창 표기(LevelMeta) 갱신...")
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
        raise RuntimeError("게스트 복원은 호스트(001)에 쓸 수 없다. 호스트 변경 기능을 써라.")
    if parked_uid == new_uid:
        raise RuntimeError("같은 캐릭터다.")
    lv = sav_decompress(os.path.join(src, "Level.sav"))
    pdir = os.path.join(src, "Players")
    pf_par = os.path.join(pdir, uid_to_filename(parked_uid) + ".sav")
    pf_new = os.path.join(pdir, uid_to_filename(new_uid) + ".sav")
    if not os.path.isfile(pf_par):
        raise RuntimeError(f"주차 캐릭 파일 없음: {os.path.basename(pf_par)}")

    log("UID 맞교환 중 (Level.sav)...")
    lv2, na, nb = swap_guids(lv, parked_uid, new_uid)
    log(f"  {uid_to_filename(parked_uid)[:8]}→{uid_to_filename(new_uid)[:8]} {na}곳")
    if na == 0:
        raise RuntimeError("주차 캐릭 UID가 월드에 없음")
    lv2, grp = fix_group_blobs(lv2, parked_uid, new_uid)
    log(f"  길드 보정: {grp}")

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
    log(f"기록 완료: {out_dir}")


def install_to_savegames(src, files, copies, steam_root, world_id, log):
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
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = os.path.join(steam_root, f"{world_id}_백업_{ts}")
        log(f"기존 폴더 백업: {os.path.basename(bak)}")
        os.rename(target, bak)
    write_fileset(src, files, copies, target, log)
    return target


# ───────────────────────────── GUI ─────────────────────────────
class App:
    def __init__(self, root):
        self.root = root
        root.title(f"팰월드 호스트 변경기 v{__version__}")
        root.geometry("720x580")
        root.minsize(700, 500)
        self.q = queue.Queue()
        self.src = None
        self.players = []      # [(uid, name, level)]
        self.busy = False

        pad = {"padx": 10, "pady": 4}

        # 1단계: 폴더
        f1 = ttk.LabelFrame(root, text=" 1. 받은 세이브 폴더 선택 ")
        f1.pack(fill="x", **pad)
        self.btn_pick = ttk.Button(f1, text="폴더 선택...", command=self.pick_folder)
        self.btn_pick.pack(side="left", padx=8, pady=8)
        self.lbl_src = ttk.Label(f1, text="(미선택)  — Level.sav 들어있는 32자리 월드 폴더", foreground="#666")
        self.lbl_src.pack(side="left", padx=4)

        # 2단계: 캐릭터
        f2 = ttk.LabelFrame(root, text=" 2. 호스트로 만들 캐릭터 클릭 ")
        f2.pack(fill="both", expand=True, **pad)
        cols = ("name", "level", "state")
        self.tree = ttk.Treeview(f2, columns=cols, show="headings", height=6, selectmode="browse")
        self.tree.heading("name", text="닉네임")
        self.tree.heading("level", text="레벨")
        self.tree.heading("state", text="상태")
        self.tree.column("name", width=260)
        self.tree.column("level", width=70, anchor="center")
        self.tree.column("state", width=140, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)

        # 3단계: 설치 위치
        f3 = ttk.LabelFrame(root, text=" 3. 실행 ")
        f3.pack(fill="x", **pad)
        row = ttk.Frame(f3)
        row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text="내 세이브 계정:").pack(side="left")
        self.cb_steam = ttk.Combobox(row, width=20, state="readonly")
        self.cb_steam.pack(side="left", padx=6)
        ttk.Label(row, text="월드 ID:").pack(side="left", padx=(12, 0))
        self.ent_world = ttk.Entry(row, width=34)
        self.ent_world.pack(side="left", padx=6, fill="x", expand=True)

        row2 = ttk.Frame(f3)
        row2.pack(fill="x", padx=8, pady=8)
        self.btn_install = ttk.Button(row2, text="★ 내 팰월드에 설치 (자동 백업)", command=self.do_install)
        self.btn_install.pack(side="left", padx=4)
        self.btn_export = ttk.Button(row2, text="전달용 폴더로 내보내기...", command=self.do_export)
        self.btn_export.pack(side="left", padx=4)
        self.btn_restore = ttk.Button(row2, text="게스트 캐릭터 복원…", command=self.do_restore)
        self.btn_restore.pack(side="left", padx=4)
        # 맵 시야는 폴더 선택과 무관하게 언제나 쓸 수 있다(항상 활성)
        self.btn_map = ttk.Button(row2, text="🗺 맵 시야 가져오기…", command=self.do_map)
        self.btn_map.pack(side="left", padx=4)

        # 로그
        f4 = ttk.LabelFrame(root, text=" 진행 상황 ")
        f4.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(f4, height=8, state="disabled", font=("맑은 고딕", 9))
        self.txt.pack(fill="both", expand=True, padx=8, pady=6)

        self.refresh_steam_ids()
        self.set_ready(False)
        self.root.after(100, self.poll)
        self.log("폴더를 선택하면 캐릭터 목록이 자동으로 뜬다.")

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
                    messagebox.showerror("오류", payload)
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
        d = filedialog.askdirectory(title="받은 세이브 폴더 (Level.sav 들어있는 곳)")
        if not d:
            return
        d = os.path.normpath(d)
        if not os.path.isfile(os.path.join(d, "Level.sav")):
            messagebox.showerror("오류", "이 폴더엔 Level.sav가 없다.\n32자리 이름의 월드 폴더를 골라야 한다.")
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
        self.log(f"분석 시작: {d}")
        threading.Thread(target=self.worker_scan, daemon=True).start()

    def worker_scan(self):
        try:
            lv = sav_decompress(os.path.join(self.src, "Level.sav"))
            self.log(f"Level.sav 해제 {len(lv):,}B — 명단 추출 중...")
            ppl = roster(lv)
            if not ppl:
                raise RuntimeError("플레이어를 못 찾음 (세이브 손상?)")
            self.q.put(("players", ppl))
            self.log(f"플레이어 {len(ppl)}명 발견. 캐릭터를 클릭하고 버튼을 눌러라.")
        except Exception as ex:
            self.q.put(("error", f"{type(ex).__name__}: {ex}"))
        finally:
            self.q.put(("done", None))

    def fill_players(self, ppl):
        self.players = ppl
        for idx, (uid, name, lvv) in enumerate(ppl):
            state = "현재 호스트" if uid == HOST_GUID else ""
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
            messagebox.showwarning("선택", "캐릭터를 먼저 클릭해라.")
            return None
        return self.players[int(sel[0])]

    def do_install(self):
        p = self.picked()
        if not p:
            return
        steam = self.cb_steam.get()
        world = self.ent_world.get().strip()
        if not steam:
            messagebox.showerror("오류", f"내 세이브 계정 폴더를 못 찾음:\n{PAL_ROOT}")
            return
        if not HEX32.match(world):
            messagebox.showerror("오류", "월드 ID는 32자리 영숫자여야 한다.\n(받은 폴더 이름 그대로가 보통 맞다)")
            return
        if palworld_running():
            messagebox.showerror("게임 실행 중", "팰월드를 완전히 끄고 다시 눌러라.")
            return
        uid, name, lvv = p
        target = os.path.join(PAL_ROOT, steam, world)
        if not messagebox.askyesno("확인",
                f"'{name}' (Lv.{lvv}) 를 호스트로 만들어\n{target}\n에 설치한다.\n"
                f"기존 폴더는 자동 백업된다. 진행?"):
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
            messagebox.showerror("오류", "월드 ID는 32자리 영숫자여야 한다.")
            return
        out_parent = filedialog.askdirectory(title="내보낼 위치 (바탕화면 등)")
        if not out_parent:
            return
        self.busy = True
        self.set_ready(False)
        threading.Thread(target=self.worker_apply, args=(p, "export", (out_parent, world)), daemon=True).start()

    def worker_apply(self, p, mode, dest):
        try:
            uid, name, lvv = p
            self.log(f"\n=== '{name}' 호스트 만들기 ===")
            files, copies = build_patched(self.src, uid, name, lvv, self.log)
            if mode == "install":
                steam_root, world = dest
                target = install_to_savegames(self.src, files, copies, steam_root, world, self.log)
                self.q.put(("popup", ("완료",
                    f"설치 완료!\n\n호스트: {name} (Lv.{lvv})\n위치: {target}\n\n"
                    f"팰월드 켜서 월드 선택창에 '{name}' 으로 뜨는지 확인하고 진입해라.")))
            else:
                out_parent, world = dest
                out_dir = os.path.join(out_parent, world)
                if os.path.exists(out_dir):
                    out_dir = out_dir + "_" + datetime.datetime.now().strftime("%H%M%S")
                write_fileset(self.src, files, copies, out_dir, self.log)
                self.q.put(("popup", ("완료",
                    f"내보내기 완료!\n\n{out_dir}\n\n이 폴더를 받는 사람이 자기 PC의\n"
                    f"%LOCALAPPDATA%\\Pal\\Saved\\SaveGames\\(숫자)\\ 안에\n"
                    f"넣으면 된다 (기존 폴더는 백업 후 교체, 게임 끈 상태).")))
            self.log("=== 끝 ===")
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
            messagebox.showerror("오류", "내 세이브 계정과 월드 ID를 먼저 확인해라.\n(보통 폴더 선택하면 자동으로 채워진다)")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("게스트 캐릭터 복원")
        dlg.geometry("460x300")
        dlg.transient(self.root)
        dlg.grab_set()
        opts = [f"{nm}  (Lv.{lvv if lvv is not None else '?'})  [{uid_to_filename(uid)[:8]}]"
                for uid, nm, lvv in self.players]

        ttk.Label(dlg, text="친구가 새로 접속해 Lv1 캐릭이 생겼을 때,\n"
                            "예전 고레벨 캐릭을 그 새 UID로 옮겨준다.",
                  justify="left").pack(padx=12, pady=(12, 8), anchor="w")
        ttk.Label(dlg, text="① 되살릴 캐릭터 (예전 고레벨 본체):").pack(anchor="w", padx=12)
        cb_src = ttk.Combobox(dlg, values=opts, state="readonly", width=52)
        cb_src.pack(padx=12, pady=(0, 8))
        ttk.Label(dlg, text="② 새로 접속한 캐릭터 (Lv1 빈 캐릭 = 그 친구):").pack(anchor="w", padx=12)
        cb_dst = ttk.Combobox(dlg, values=opts, state="readonly", width=52)
        cb_dst.pack(padx=12, pady=(0, 8))
        # 기본 추천: 최고레벨=src, 최저레벨=dst
        lv_list = [(i, (lvv or 0)) for i, (_, _, lvv) in enumerate(self.players)]
        if lv_list:
            cb_src.current(max(lv_list, key=lambda x: x[1])[0])
            cb_dst.current(min(lv_list, key=lambda x: x[1])[0])

        def go():
            si, di = cb_src.current(), cb_dst.current()
            if si < 0 or di < 0 or si == di:
                messagebox.showerror("오류", "서로 다른 두 캐릭터를 골라라.", parent=dlg)
                return
            src_uid = self.players[si][0]
            dst_uid = self.players[di][0]
            if src_uid == HOST_GUID or dst_uid == HOST_GUID:
                messagebox.showerror("오류", "호스트(001)는 이 기능 대상이 아니다.\n호스트 교체는 위의 설치 버튼을 써라.", parent=dlg)
                return
            if palworld_running():
                messagebox.showerror("게임 실행 중", "팰월드를 완전히 끄고 다시 눌러라.", parent=dlg)
                return
            if not messagebox.askyesno("확인",
                    f"'{self.players[si][1]}'(Lv.{self.players[si][2]}) 를\n"
                    f"'{self.players[di][1]}' 의 UID로 복원한다.\n기존 폴더는 자동 백업. 진행?", parent=dlg):
                return
            dlg.destroy()
            self.busy = True
            self.set_ready(False)
            threading.Thread(target=self.worker_restore,
                             args=(src_uid, dst_uid, os.path.join(PAL_ROOT, steam), world),
                             daemon=True).start()

        bar = ttk.Frame(dlg)
        bar.pack(pady=10)
        ttk.Button(bar, text="복원 실행", command=go).pack(side="left", padx=6)
        ttk.Button(bar, text="취소", command=dlg.destroy).pack(side="left", padx=6)

    # ── 맵 시야(탐색 안개) 가져오기 ──
    def do_map(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("맵 시야 가져오기")
        dlg.geometry("620x340")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, justify="left", text=
            "탐색한 맵(안개 걷힌 영역)은 각자 PC의 LocalData.sav 에 들어있다.\n"
            "남의 LocalData.sav 에서 시야만 뽑아 내 것에 이식한다.\n"
            "캐릭터·팰·아이템은 전혀 건드리지 않는다."
        ).pack(padx=12, pady=(12, 8), anchor="w")

        v_src = tk.StringVar()
        v_dst = tk.StringVar()
        v_mode = tk.StringVar(value="merge")

        f1 = ttk.Frame(dlg); f1.pack(fill="x", padx=12, pady=2)
        ttk.Label(f1, text="① 가져올 시야 (남의 LocalData.sav)").pack(anchor="w")
        r1 = ttk.Frame(f1); r1.pack(fill="x")
        ttk.Entry(r1, textvariable=v_src).pack(side="left", fill="x", expand=True)
        ttk.Button(r1, text="찾기", command=lambda: v_src.set(
            filedialog.askopenfilename(title="가져올 LocalData.sav",
                                       filetypes=[("LocalData.sav", "LocalData.sav"), ("sav", "*.sav")]) or v_src.get()
        )).pack(side="left", padx=4)

        f2 = ttk.Frame(dlg); f2.pack(fill="x", padx=12, pady=(8, 2))
        ttk.Label(f2, text="② 적용할 내 LocalData.sav (내 세이브의 월드 폴더 안)").pack(anchor="w")
        r2 = ttk.Frame(f2); r2.pack(fill="x")
        ttk.Entry(r2, textvariable=v_dst).pack(side="left", fill="x", expand=True)
        ttk.Button(r2, text="찾기", command=lambda: v_dst.set(
            filedialog.askopenfilename(title="내 LocalData.sav", initialdir=PAL_ROOT,
                                       filetypes=[("LocalData.sav", "LocalData.sav"), ("sav", "*.sav")]) or v_dst.get()
        )).pack(side="left", padx=4)

        f3 = ttk.LabelFrame(dlg, text=" 방식 ")
        f3.pack(fill="x", padx=12, pady=10)
        ttk.Radiobutton(f3, variable=v_mode, value="merge",
                        text="합치기 (내 탐험 + 남의 탐험 = 둘 다 유지)  ← 권장").pack(anchor="w", padx=8, pady=2)
        ttk.Radiobutton(f3, variable=v_mode, value="replace",
                        text="덮어쓰기 (남의 탐험으로 완전 교체)").pack(anchor="w", padx=8, pady=2)

        def go():
            s, t = v_src.get().strip(), v_dst.get().strip()
            if not (s and t):
                messagebox.showerror("오류", "두 파일 다 골라라.", parent=dlg); return
            if os.path.abspath(s) == os.path.abspath(t):
                messagebox.showerror("오류", "같은 파일이다.", parent=dlg); return
            if palworld_running():
                messagebox.showerror("게임 실행 중", "팰월드를 완전히 끄고 다시 눌러라.", parent=dlg); return
            dlg.destroy()
            self.busy = True; self.set_ready(False)
            self.btn_map.configure(state="disabled")
            threading.Thread(target=self.worker_map, args=(s, t, v_mode.get() == "merge"),
                             daemon=True).start()

        bar = ttk.Frame(dlg); bar.pack(pady=6)
        ttk.Button(bar, text="실행", command=go).pack(side="left", padx=6)
        ttk.Button(bar, text="취소", command=dlg.destroy).pack(side="left", padx=6)

    def worker_map(self, src_path, dst_path, merge):
        try:
            self.log(f"\n=== 맵 시야 {'합치기' if merge else '덮어쓰기'} ===")
            src = sav_decompress(src_path)
            dst = sav_decompress(dst_path)
            self.log(f"  가져올 시야: {[f'{p:.1f}%' for _, _, p in map_explored_ratio(src)]}")
            self.log(f"  현재 내 시야: {[f'{p:.1f}%' for _, _, p in map_explored_ratio(dst)]}")
            out, rep = transplant_map(dst, src, merge=merge)
            self.log(f"  {rep}")
            bak = dst_path + "_백업_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(dst_path, bak)
            self.log(f"  백업: {os.path.basename(bak)}")
            with open(dst_path, "wb") as fh:
                fh.write(sav_compress_plz(out))
            self.q.put(("popup", ("완료",
                f"맵 시야 이식 완료!\n\n{rep}\n\n"
                f"팰월드 켜서 지도 열어보면 반영돼 있다.\n원본 백업: {os.path.basename(bak)}")))
            self.log("=== 끝 ===")
        except Exception as ex:
            self.q.put(("error", f"{type(ex).__name__}: {ex}"))
        finally:
            self.q.put(("done", None))

    def worker_restore(self, src_uid, dst_uid, steam_root, world):
        try:
            self.log(f"\n=== 게스트 복원: {uid_to_filename(src_uid)[:8]} → {uid_to_filename(dst_uid)[:8]} ===")
            files, copies = build_guest_restore(self.src, src_uid, dst_uid, self.log)
            target = install_to_savegames(self.src, files, copies, steam_root, world, self.log)
            self.q.put(("popup", ("완료",
                f"복원 완료!\n\n위치: {target}\n\n"
                f"그 친구가 다시 접속하면 예전 캐릭터로 뜬다.")))
            self.log("=== 끝 ===")
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
