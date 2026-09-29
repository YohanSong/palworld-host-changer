# -*- coding: utf-8 -*-
"""
팰월드 호스트 변경기
- 세이브 폴더에서 플레이어 명단을 뽑아 보여주고, 고른 캐릭터를 호스트(UID 001)로 만든다.
- 원본은 건드리지 않고 "<원본>_호스트_<닉네임>" 폴더를 새로 만든다.
- 필요 파일: 같은 폴더의 ooz.dll (Oodle Kraken 압축 해제용, third_party/ooz 에서 빌드)
- 압축 쓰기는 PlZ(zlib) — 게임이 읽고 자기 포맷으로 재발행함 (2026-09-03 실증).
"""
__version__ = "1.0.0"

import ctypes, os, re, shutil, struct, sys, zlib
from bisect import bisect_right

def _res_dir():
    """리소스(ooz.dll) 위치 — PyInstaller onefile exe면 _MEIPASS, 아니면 스크립트 폴더."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

HERE = _res_dir()
HOST_GUID = b"\x00" * 12 + b"\x01\x00\x00\x00"
ANCHOR = b"PlayerUId\x00"


# ───────────────────────── 압축 컨테이너 ─────────────────────────
def load_ooz():
    dll = ctypes.CDLL(os.path.join(HERE, "ooz.dll"))
    dll.Kraken_Decompress.restype = ctypes.c_int
    dll.Kraken_Decompress.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
    return dll

_OOZ = None

def sav_decompress(path):
    global _OOZ
    d = open(path, "rb").read()
    ulen, clen = struct.unpack_from("<II", d, 0)
    magic = d[8:12]
    if magic == b"PlZ1":
        out = zlib.decompress(d[12:])
    elif magic == b"PlZ2":
        out = zlib.decompress(zlib.decompress(d[12:]))
    elif magic in (b"PlM1", b"PlM2"):
        if _OOZ is None:
            _OOZ = load_ooz()
        buf = ctypes.create_string_buffer(ulen + 64)  # 디코더 여유 공간
        n = _OOZ.Kraken_Decompress(d[12:], len(d) - 12, buf, ulen)
        if n != ulen:
            raise RuntimeError(f"{os.path.basename(path)}: Kraken 해제 실패 ({n} != {ulen})")
        out = buf.raw[:ulen]
    else:
        raise RuntimeError(f"{os.path.basename(path)}: 알 수 없는 매직 {magic!r}")
    if len(out) != ulen:
        raise RuntimeError(f"{os.path.basename(path)}: 크기 불일치 {len(out)} != {ulen}")
    return out


def sav_compress_plz(data):
    comp = zlib.compress(data)
    return struct.pack("<II", len(data), len(comp)) + b"PlZ" + b"\x31" + comp


# ───────────────────────── GUID 사이트 스캔 ─────────────────────────
def guid_sites(d):
    """PlayerUId/OwnerPlayerUId 속성의 GUID 값 오프셋 목록 (레이아웃 검증 통과분만)."""
    sites = []
    pos = 0
    while True:
        t = d.find(ANCHOR, pos)
        if t < 0:
            break
        pos = t + 1
        if (d[t+10:t+14] == struct.pack("<i", 15)
                and d[t+14:t+29] == b"StructProperty\x00"
                and struct.unpack_from("<Q", d, t+29)[0] == 16
                and d[t+37:t+41] == struct.pack("<i", 5)
                and d[t+41:t+46] == b"Guid\x00"):
            sites.append(t + 63)  # 16바이트 GUID 값 위치
    return sites


def swap_guids(d, a, b, sites=None):
    """모든 검증 사이트에서 a↔b 맞교환. (구식 — 팰 키 센티넬까지 바꿔 팰이 사라짐.
    호스트 이관에는 swap_host 사용. 왕복 검증 등 내부 용도로만 유지.)"""
    if sites is None:
        sites = guid_sites(d)
    out = bytearray(d)
    na = nb = 0
    for off in sites:
        v = bytes(out[off:off+16])
        if v == a:
            out[off:off+16] = b
            na += 1
        elif v == b:
            out[off:off+16] = a
            nb += 1
    return bytes(out), na, nb


def _anchor_sites(d):
    """PlayerUId 계열 앵커 목록. 각 항목 (value_off, anchor_off, is_owner)."""
    sites = []
    pos = 0
    while True:
        t = d.find(ANCHOR, pos)
        if t < 0:
            break
        pos = t + 1
        if (d[t+10:t+14] == struct.pack("<i", 15)
                and d[t+14:t+29] == b"StructProperty\x00"
                and struct.unpack_from("<Q", d, t+29)[0] == 16
                and d[t+37:t+41] == struct.pack("<i", 5)
                and d[t+41:t+46] == b"Guid\x00"):
            is_owner = (t >= 5 and d[t-5:t] == b"Owner")
            sites.append((t + 63, t, is_owner))
    return sites


def swap_host(d, host, target):
    """호스트(host=001) ↔ target(게스트 uid) 이관 — 팰 보존형 정밀 스왑.

    핵심(2026-09 실측): 캐릭터맵에서 **팰의 키 PlayerUId = 001(호스트 슬롯 상수)**.
    실소유는 별도 OwnerPlayerUId에 있다. 구식 swap_guids는 이 팰 키 001까지 target으로
    바꿔 컨테이너가 팰을 못 찾게 만들었다(팰 증발). 그래서:
      - OwnerPlayerUId 사이트: host↔target 항상 맞교환 (개인 소유는 사람을 따라감).
      - 단독 PlayerUId 사이트:
          value==target → host 로 (게스트 uid는 절대 팰 센티넬이 아님, 항상 안전).
          value==host   → target 으로 '**그 엔트리에 IsPlayer가 있을 때만**'
                          (실제 플레이어 캐릭터 키). IsPlayer 없으면 팰 키 센티넬 → 보존.
    자기역함수라 두 번 적용하면 원본과 바이트 일치."""
    out = bytearray(d)
    sites = _anchor_sites(d)
    starts = [t for (_v, t, _o) in sites]
    LEN10 = struct.pack("<i", 10)                   # 정확히 "PlayerUId"(9+null) fstring 길이
    n_id = n_player = n_target = kept = 0
    for idx, (off, t, _o) in enumerate(sites):
        v = bytes(out[off:off+16])
        # 이 앵커가 '정확한 단독 PlayerUId 맵 키'인가, 아니면 복합 신원필드
        # (OwnerPlayerUId / LostPlayerUId / …)인가 — 길이 프리픽스로 판별.
        is_mapkey = (out[t-4:t] == LEN10)
        if not is_mapkey:
            # 신원참조: 사람을 따라감 → 항상 맞교환
            if v == host:
                out[off:off+16] = target; n_id += 1
            elif v == target:
                out[off:off+16] = host; n_id += 1
            continue
        # 캐릭터맵 키
        if v == target:
            out[off:off+16] = host; n_target += 1
        elif v == host:
            nxt = starts[idx + 1] if idx + 1 < len(starts) else len(out)
            if out.find(b"IsPlayer\x00", t, nxt) != -1:
                out[off:off+16] = target; n_player += 1   # 실제 플레이어 캐릭터 키
            else:
                kept += 1                                  # 팰 키 센티넬 — 보존
    return bytes(out), {"identity": n_id, "player_key": n_player,
                        "target->host": n_target, "pal_key_kept": kept}


# ───────────────────────── 문자열/명단 ─────────────────────────
def read_fstring(d, off):
    (ln,) = struct.unpack_from("<i", d, off)
    if ln == 0:
        return "", off + 4
    if ln > 0:
        return d[off+4:off+4+ln-1].decode("utf-8", "replace"), off + 4 + ln
    n = -ln
    return d[off+4:off+4+n*2-2].decode("utf-16-le", "replace"), off + 4 + n*2


def find_level_after(d, start, limit=8192):
    """캐릭터 Level 속성값 — SaveParameter 안에서 Level은 NickName보다 앞에 온다."""
    pos = max(0, start - 512)
    end = min(len(d), start + limit)
    while pos < end:
        i = d.find(b"Level\x00", pos, end)
        if i < 0:
            return None
        pos = i + 1
        if d[i-4:i] != struct.pack("<i", 6):  # 정확히 "Level" 속성명일 것 (HostPlayerLevel 등 배제)
            continue
        tname, voff = read_fstring(d, i + 6)
        if tname == "IntProperty":
            return struct.unpack_from("<i", d, voff + 9)[0]
        if tname == "ByteProperty":
            (elen,) = struct.unpack_from("<i", d, voff + 8)
            return d[voff + 12 + elen + 1]
    return None


def roster(level_gvas):
    """Level.sav 안의 실제 플레이어 목록: [(uid16, 닉네임, 레벨)]"""
    sites = guid_sites(level_gvas)
    offs = sites
    players = {}
    pos = 0
    while True:
        i = level_gvas.find(b"NickName\x00", pos)
        if i < 0:
            break
        pos = i + 1
        tname, voff = read_fstring(level_gvas, i + 9)
        if tname != "StrProperty":
            continue
        name, _ = read_fstring(level_gvas, voff + 9)
        # 플레이어만 (이름 붙인 팰 배제): 근방에 IsPlayer 플래그 필수
        w_s, w_e = max(0, i - 4096), min(len(level_gvas), i + 4096)
        if level_gvas.find(b"IsPlayer\x00", w_s, w_e) < 0:
            continue
        # 직전의 검증된 GUID 사이트 = 이 캐릭터의 PlayerUId
        k = bisect_right(offs, i) - 1
        if k < 0 or i - offs[k] > 8192:
            continue
        uid = bytes(level_gvas[offs[k]:offs[k]+16])
        if uid in players:
            continue
        lv = find_level_after(level_gvas, i)
        players[uid] = (name, lv)
    return [(uid, nm, lv) for uid, (nm, lv) in players.items()]


def uid_to_filename(uid):
    """저장 파일명 = GUID 각 u32 컴포넌트를 빅엔디안 hex로."""
    a, b, c, e = struct.unpack("<IIII", uid)
    return f"{a:08X}{b:08X}{c:08X}{e:08X}"


# ───────────────────────── 길드(그룹) 블롭 보정 ─────────────────────────
# 거점·배치 팰은 길드 소속. 길드 데이터는 GroupSaveDataMap의 RawData(비GVAS
# 바이너리)에 있어 PlayerUId 앵커 스왑이 못 미친다. 여기서 구조 파싱으로
# admin_player_uid / players[].player_uid / 길드명(uid 문자열)만 정밀 스왑.
# 블롭 내 레이아웃(2026-09 게임 실측): ...[admin uid16][멤버수 u32]
#   [멤버: uid16 + last_online i64 + 이름 fstring]... — 이 블록을 검증 파싱.

def _iter_group_rawdata(d):
    """GroupSaveDataMap의 각 RawData 블롭 (시작, 끝, 그룹타입) 생성."""
    i = d.find(b"GroupSaveDataMap\x00")
    if i < 0:
        return
    p = i + 17
    _, p = read_fstring(d, p)                    # "MapProperty"
    p += 8                                        # size
    _, p = read_fstring(d, p)                     # key type
    _, p = read_fstring(d, p)                     # value type
    p += 1
    _, cnt = struct.unpack_from("<II", d, p)
    p += 8
    for _ in range(cnt):
        p += 16                                   # key guid
        gtype = "?"
        while True:
            name, p = read_fstring(d, p)
            if name == "None":
                break
            typ, p = read_fstring(d, p)
            p += 8                                # property size
            if typ == "EnumProperty":
                _, p2 = read_fstring(d, p)
                p2 += 1
                val, p2 = read_fstring(d, p2)
                if name == "GroupType":
                    gtype = val
                p = p2
            elif typ == "ArrayProperty":
                _, p2 = read_fstring(d, p)
                p2 += 1
                (bc,) = struct.unpack_from("<I", d, p2)
                p2 += 4
                if name == "RawData":
                    yield p2, p2 + bc, gtype
                p = p2 + bc
            else:
                raise RuntimeError(f"그룹 파싱: 예상 밖 타입 {typ} @{p:#x}")


def _find_players_block(d, s, e):
    """길드 블롭 꼬리에 있는 [admin uid16][멤버수 i32][멤버…][고정 트레일러]를
    뒤에서부터 앵커링해 찾는다. 성공 시 (admin위치, [멤버uid위치…]), 실패 시 (None,None).
    멤버 구조: uid16 + last_online i64 + 이름 fstring. 블록 뒤 트레일러(≈31B)는 허용."""
    hdr_min = s + 20
    for q in range(e - 24, hdr_min, -1):
        (cnt,) = struct.unpack_from("<i", d, q + 16)
        if not (1 <= cnt <= 8):
            continue
        p = q + 20
        poss = []
        ok = True
        for _ in range(cnt):
            if p + 28 > e:
                ok = False
                break
            poss.append(p)
            p += 24                               # uid16 + last_online i64
            (ln,) = struct.unpack_from("<i", d, p)
            if ln == 0 or not (-128 <= ln <= 128):
                ok = False
                break
            if ln > 0:
                if p + 4 + ln > e or d[p + 4 + ln - 1] != 0:
                    ok = False
                    break
                p += 4 + ln
            else:
                n = -ln
                if p + 4 + 2*n > e or d[p + 4 + 2*n - 2:p + 4 + 2*n] != b"\x00\x00":
                    ok = False
                    break
                p += 4 + 2*n
        if ok and 0 <= e - p <= 48:               # 뒤 고정 트레일러 허용
            return q, poss
    return None, None


def _player_instances(d):
    """캐릭터맵에서 실제 플레이어들의 (현재 uid, InstanceId) 목록."""
    out = []
    seen = set()
    sites = guid_sites(d)
    from bisect import bisect_right
    pos = 0
    while True:
        i = d.find(b"NickName\x00", pos)
        if i < 0:
            break
        pos = i + 1
        t, o2 = read_fstring(d, i + 9)
        if t != "StrProperty":
            continue
        ws = max(0, i - 4096)
        if d.find(b"IsPlayer\x00", ws, i + 4096) < 0:
            continue
        k = bisect_right(sites, i) - 1
        if k < 0 or i - sites[k] > 8192:
            continue
        uid = bytes(d[sites[k]:sites[k]+16])
        j = d.rfind(b"InstanceId\x00", ws, i)
        if j < 0:
            continue
        t2 = j + 11
        if d[t2:t2+4] != struct.pack("<i", 15) or d[t2+4:t2+19] != b"StructProperty\x00":
            continue
        inst = bytes(d[t2+53:t2+69])
        if inst in seen:
            continue
        seen.add(inst)
        out.append((uid, inst))
    return out


def fix_group_blobs(data, a, b):
    """그룹(길드) 데이터 정합 보정. swap_guids(캐릭터맵) 다음에 호출한다.
    returns (bytes, 보고문자열).

    구조 실측(2026-09): 길드 블롭 =
      group_id(16) + group_name(fstring) + handles[cnt]{guid16, instance16}
      + org_type(1) + base_ids[…] + base_camp_level(i32) + map_object[…]
      + guild_name(fstring) + admin_uid(16) + players[cnt]{uid16,i64,name}
      + 고정 트레일러(31B)

    보정 3종(팰 센티넬 절대 미접촉):
    A) admin_player_uid, players[].player_uid : a↔b 맞교환 → 호스트 소속 길드 결정.
       미보정 시 001 중복 admin으로 '엉뚱한 길드 흡수' 발생.
    B) group_name/guild_name 이 uid hex32 문자열이면 a_hex↔b_hex 교환(식별자).
    C) 플레이어 핸들의 guid16 = 그 플레이어 본인 uid → 캐릭터맵 최신 uid로 재기입.
       팰 핸들은 guid16=001 상수(전 길드 공통)라 손대면 팰이 사라진다 → 인스턴스로
       플레이어 핸들만 골라 수정."""
    d = bytearray(data)
    rep = []
    a_hex = uid_to_filename(a).encode("ascii")
    b_hex = uid_to_filename(b).encode("ascii")
    players = _player_instances(d)                 # (최신 uid, instance)
    inst_to_uid = {inst: uid for uid, inst in players}

    for s, e, gtype in _iter_group_rawdata(d):
        if "Guild" not in gtype:
            continue
        did = []

        # ── 헤더 파싱: 핸들 영역 확정 ──
        p = s + 16                                 # group_id
        _, p = read_fstring(d, p)                  # group_name
        (hcnt,) = struct.unpack_from("<I", d, p)
        hstart = p + 4
        hend = hstart + hcnt * 32

        # (C) 플레이어 핸들 guid 재기입
        hfix = 0
        for hp in range(hstart, hend, 32):
            inst = bytes(d[hp+16:hp+32])
            u = inst_to_uid.get(inst)
            if u is not None and bytes(d[hp:hp+16]) != u:
                d[hp:hp+16] = u
                hfix += 1
        if hfix:
            did.append(f"플레이어핸들 {hfix}")

        # (A) admin/players 꼬리 블록 스왑
        aq, poss = _find_players_block(d, s, e)
        if aq is not None:
            ab = 0
            for pos in [aq] + poss:
                cur = bytes(d[pos:pos+16])
                if cur == a:
                    d[pos:pos+16] = b
                    ab += 1
                elif cur == b:
                    d[pos:pos+16] = a
                    ab += 1
            if ab:
                did.append(f"admin/멤버 {ab}")
        else:
            did.append("!!admin블록 못찾음")

        # (B) 이름 문자열(uid hex32) 교환 — 블롭 국한, 크기 불변
        seg = bytearray(d[s:e])
        nb = 0
        i = 0
        while i <= len(seg) - 32:
            chunk = bytes(seg[i:i+32])
            if chunk == a_hex:
                seg[i:i+32] = b_hex
                nb += 1
                i += 32
                continue
            if chunk == b_hex:
                seg[i:i+32] = a_hex
                nb += 1
                i += 32
                continue
            i += 1
        if nb:
            d[s:e] = seg
            did.append(f"이름 {nb}")

        if did:
            rep.append(f"{gtype.split('::')[-1]}@{s:#x}: " + ", ".join(did))

    return bytes(d), ("; ".join(rep) if rep else "교환 대상 없음")


# ───────────────────────── 맵 시야(탐색 안개) 이식 ─────────────────────────
# 실측(2026-09-04): 탐색 시야는 LocalData.sav 의
#   WorldMapUISaveDataMap → { 'MainMap': 2048²=4,194,304B, 'Tree': 1024²=1,048,576B }
#   → 각 엔트리의 MaskTextureData (ArrayProperty<ByteProperty>) 바이트 배열.
# LocalData 는 "공유 세이브"가 아니라 **각 PC의 로컬 데이터**다. 호스트든 게스트든
# 자기 PC의 LocalData 시야를 읽는다(실증). 그래서 이 배열만 옮기면 남의 탐험을
# 그대로 물려받는다. 배열 크기가 고정이라 재인코딩 없이 바이트 교체로 안전.

def find_map_masks(local_gvas):
    """LocalData GVAS 안의 MaskTextureData 배열들. [{anchor,data_off,count}]"""
    out = []
    pos = 0
    while True:
        i = local_gvas.find(b"MaskTextureData\x00", pos)
        if i < 0:
            break
        pos = i + 1
        p = i + 16
        t, p = read_fstring(local_gvas, p)
        if t != "ArrayProperty":
            continue
        (psize,) = struct.unpack_from("<Q", local_gvas, p); p += 8
        et, p = read_fstring(local_gvas, p)
        if et != "ByteProperty":
            continue
        p += 1                                    # terminator
        (count,) = struct.unpack_from("<I", local_gvas, p); p += 4
        if p + count > len(local_gvas):
            continue
        out.append({"anchor": i, "data_off": p, "count": count})
    return out


def map_explored_ratio(local_gvas):
    """탐험률(0이 아닌 바이트 비율) — 마스크별 리스트."""
    res = []
    for m in find_map_masks(local_gvas):
        blob = local_gvas[m["data_off"]:m["data_off"] + m["count"]]
        nz = sum(1 for b in blob if b)
        res.append((m["count"], nz, nz * 100.0 / m["count"] if m["count"] else 0.0))
    return res


def transplant_map(dst_gvas, src_gvas, merge=False):
    """src LocalData 의 탐색 시야를 dst LocalData 로 이식.
    merge=False → 통째 덮어쓰기(= src 탐험 그대로)
    merge=True  → 바이트별 max (= 두 사람 탐험 합집합)
    크기가 같은 마스크끼리만 짝지어 교체하므로 구조는 절대 안 깨진다.
    returns (bytes, 보고문자열)"""
    d = bytearray(dst_gvas)
    dms = find_map_masks(d)
    sms = find_map_masks(src_gvas)
    if not dms or not sms:
        raise RuntimeError("MaskTextureData(맵 시야)를 못 찾음 — LocalData.sav 가 맞는지 확인")
    rep = []
    used = set()
    for dm in dms:
        # 같은 크기의 src 마스크를 순서대로 매칭
        cand = next((k for k, sm in enumerate(sms)
                     if k not in used and sm["count"] == dm["count"]), None)
        if cand is None:
            rep.append(f"{dm['count']:,}B 마스크: 짝 없음(건너뜀)")
            continue
        used.add(cand)
        sm = sms[cand]
        src_blob = src_gvas[sm["data_off"]:sm["data_off"] + sm["count"]]
        off, n = dm["data_off"], dm["count"]
        if merge:
            cur = d[off:off + n]
            merged = bytes(max(a, b) for a, b in zip(cur, src_blob))
            d[off:off + n] = merged
            after = sum(1 for b in merged if b)
        else:
            d[off:off + n] = src_blob
            after = sum(1 for b in src_blob if b)
        rep.append(f"{n:,}B 마스크 → 탐험 {after * 100.0 / n:.1f}%")
    return bytes(d), ("; ".join(rep))


# ───────────────────────── LevelMeta ─────────────────────────
def patch_levelmeta(meta_gvas, host_name, host_level):
    from palworld_save_tools.gvas import GvasFile
    g = GvasFile.read(meta_gvas)
    sd = g.properties["SaveData"]["value"]
    sd["HostPlayerName"]["value"] = host_name
    if host_level is not None and "HostPlayerLevel" in sd:
        sd["HostPlayerLevel"]["value"] = int(host_level)
    return g.write({})


# ───────────────────────── 메인 ─────────────────────────
def main():
    print("=" * 46)
    print(f"  팰월드 호스트 변경기 v{__version__}")
    print("=" * 46)

    src = sys.argv[1].strip('"') if len(sys.argv) > 1 else input("세이브 폴더 경로 (32자리 월드 폴더): ").strip('"').strip()
    src = os.path.abspath(src)
    lv_path = os.path.join(src, "Level.sav")
    if not os.path.isfile(lv_path):
        sys.exit(f"[오류] Level.sav 없음: {src}")

    print(f"\n[1/5] 해체 중: {lv_path}")
    lv = sav_decompress(lv_path)
    print(f"      Level.sav {len(lv):,}B 해제 완료")

    print("[2/5] 플레이어 명단 추출 중...")
    ppl = roster(lv)
    if not ppl:
        sys.exit("[오류] 플레이어를 못 찾음 — 세이브 손상?")
    for n, (uid, nm, lvv) in enumerate(ppl, 1):
        tag = "  ← 현재 호스트" if uid == HOST_GUID else ""
        lvs = f"Lv.{lvv}" if lvv is not None else "Lv.?"
        print(f"   {n}) {nm}  {lvs}  [{uid_to_filename(uid)[:8]}]{tag}")

    while True:
        try:
            raw = sys.argv[2] if len(sys.argv) > 2 else input("\n호스트로 만들 번호: ")
            pick = int(re.sub(r"[^0-9]", "", raw))  # BOM/공백/개행 무시
            if 1 <= pick <= len(ppl):
                break
        except ValueError:
            pass
        if len(sys.argv) > 2:
            sys.exit(f"[오류] 잘못된 번호 인자: {sys.argv[2]}")
        print("   번호 다시.")
    t_uid, t_name, t_level = ppl[pick - 1]

    if t_uid == HOST_GUID:
        sys.exit(f"\n'{t_name}' 이미 호스트다. 할 일 없음.")

    old_host = next(((u, n, l) for u, n, l in ppl if u == HOST_GUID), None)
    print(f"\n   교체: 호스트(001) [{old_host[1] if old_host else '없음'}]  ↔  {t_name}")

    # 플레이어 파일 확인
    pdir = os.path.join(src, "Players")
    t_file = os.path.join(pdir, uid_to_filename(t_uid) + ".sav")
    h_file = os.path.join(pdir, "0" * 31 + "1.sav")
    for p in (t_file, h_file):
        if not os.path.isfile(p):
            sys.exit(f"[오류] 플레이어 파일 없음: {p}")

    print("[3/5] UID 맞교환 중 (Level.sav) — 팰 키 보존형...")
    lv2, st = swap_host(lv, HOST_GUID, t_uid)
    print(f"      신원 {st['identity']} / 플레이어키 {st['player_key']} / {t_name}→001 {st['target->host']} / 팰키보존 {st['pal_key_kept']}")
    if st['player_key'] == 0 and st['target->host'] == 0:
        sys.exit("[오류] 대상 캐릭터 UID가 월드에 없음 — 중단")
    lv2, grp = fix_group_blobs(lv2, HOST_GUID, t_uid)
    print(f"      길드(거점 소유) 보정: {grp}")

    print("[4/5] 플레이어 파일/겉표지 처리 중...")
    # 플레이어 .sav엔 Level.sav식 팰키 센티넬(001)이 없다 → 전체 스왑(swap_guids).
    # (swap_host를 쓰면 옛 호스트 파일의 자기 uid 001을 팰키로 오인 보존해 파일명과 불일치)
    h_gvas, _, _ = swap_guids(sav_decompress(h_file), HOST_GUID, t_uid)   # 옛 호스트 캐릭 → 게스트 자리로
    t_gvas, _, _ = swap_guids(sav_decompress(t_file), HOST_GUID, t_uid)   # 새 호스트 캐릭 → 001로
    meta_path = os.path.join(src, "LevelMeta.sav")
    meta_out = patch_levelmeta(sav_decompress(meta_path), t_name, t_level) if os.path.isfile(meta_path) else None

    # 출력 폴더
    safe = re.sub(r'[\\/:*?"<>| ]+', "_", t_name)[:20]
    out_dir = src.rstrip("\\/") + f"_호스트_{safe}"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(os.path.join(out_dir, "Players"))

    print(f"[5/5] 재포장 → {out_dir}")
    open(os.path.join(out_dir, "Level.sav"), "wb").write(sav_compress_plz(lv2))
    if meta_out is not None:
        open(os.path.join(out_dir, "LevelMeta.sav"), "wb").write(sav_compress_plz(meta_out))
    # 새 호스트 캐릭 = 001 파일명 / 옛 호스트 캐릭 = 대상의 옛 파일명으로 주차
    open(os.path.join(out_dir, "Players", "0" * 31 + "1.sav"), "wb").write(sav_compress_plz(t_gvas))
    open(os.path.join(out_dir, "Players", uid_to_filename(t_uid) + ".sav"), "wb").write(sav_compress_plz(h_gvas))
    # 나머지 플레이어/부속 파일 그대로 복사 (backup 폴더는 제외)
    for f in os.listdir(pdir):
        if f.lower().endswith(".sav") and f not in (os.path.basename(t_file), os.path.basename(h_file)):
            shutil.copy2(os.path.join(pdir, f), os.path.join(out_dir, "Players", f))
    for f in ("WorldOption.sav", "LocalData.sav"):
        p = os.path.join(src, f)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(out_dir, f))

    print("\n" + "=" * 46)
    print(f"  완료! 새 호스트: {t_name}" + (f" (Lv.{t_level})" if t_level is not None else ""))
    print(f"  결과 폴더: {out_dir}")
    print("-" * 46)
    print("  사용법: 이 폴더를 호스트 될 사람 PC의")
    print(r"  %LOCALAPPDATA%\Pal\Saved\SaveGames\(숫자)\ 아래에")
    print(f"  원래 이름({os.path.basename(src)})으로 바꿔 넣는다.")
    print("  ※ 기존 폴더는 반드시 백업 후 교체. 게임 꺼진 상태에서.")
    print("=" * 46)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code and str(e.code) != "0":
            print(e.code if isinstance(e.code, str) else "")
    except Exception as ex:
        print(f"\n[예외] {type(ex).__name__}: {ex}")
    finally:
        pass
