Palworld Host Changer  —  https://github.com/YohanSong/palworld-host-changer
GPL-3.0-or-later. Unofficial fan tool, not affiliated with Pocketpair. Back up your saves first.

========================================================================
 English
========================================================================
1. Close Palworld completely.
2. Unzip this folder (don't run it from inside the zip), double-click PalworldHostChanger.bat.
   The language can be changed at the top right (한국어 / English / 简体中文 / 日本語).
3. [Select folder] -> the world folder you received:
   %LOCALAPPDATA%\Pal\Saved\SaveGames\<number>\<32-character world ID>   (contains Level.sav)
4. Click the character who should be the host (usually you).
5. [Install to my Palworld] - an existing copy of the world is moved to
   %LOCALAPPDATA%\Pal\Saved\HostChangerBackups first.
   Or [Export] a folder for someone else.
6. Start the game; the world list should show that character's name.
Friend gets the character creation screen?  They create any character and play a minute,
  then the host uses [Restore guest character] (old character -> new Lv1 character).
Map is black?  [Import map fog] with someone else's LocalData.sav (Merge keeps both).

========================================================================
 한국어
========================================================================
1. 팰월드를 완전히 끈다.
2. 압축을 푼 뒤(zip 안에서 실행 X) PalworldHostChanger.bat 더블클릭. 언어는 오른쪽 위에서 변경.
3. [폴더 선택] -> 받은 월드 폴더 (%LOCALAPPDATA%\Pal\Saved\SaveGames\<숫자>\<32자리 월드ID>, Level.sav 있는 곳)
4. 호스트가 될 캐릭터(보통 나) 클릭.
5. [내 팰월드에 설치] - 같은 월드가 있으면 %LOCALAPPDATA%\Pal\Saved\HostChangerBackups 로 옮겨 보관. 남한테 줄 거면 [전달용 폴더로 내보내기].
6. 게임 켜서 월드 선택창에 그 캐릭 이름이 뜨는지 확인.
캐릭터 생성창 뜬 친구 -> 아무 캐릭이나 만들어 1분 플레이 -> 호스트가 [게스트 캐릭터 복원] (예전 캐릭 -> 새 Lv1 캐릭).
지도가 까맘 -> 남의 LocalData.sav 로 [맵 시야 가져오기] (합치기 권장).

========================================================================
 简体中文
========================================================================
1. 完全关闭幻兽帕鲁。
2. 解压后（不要在压缩包内运行）双击 PalworldHostChanger.bat。右上角可切换语言。
3. [选择文件夹] -> 收到的世界文件夹（%LOCALAPPDATA%\Pal\Saved\SaveGames\<数字>\<32 位世界ID>，包含 Level.sav）
4. 点击要成为房主的角色（通常是你自己）。
5. [安装到我的帕鲁] - 已有同一世界时会先移到 %LOCALAPPDATA%\Pal\Saved\HostChangerBackups 备份。要给别人用请选 [导出为转交用文件夹]。
6. 启动游戏，确认世界列表显示该角色名。
朋友出现创建角色界面 -> 让朋友随便创建角色玩 1 分钟 -> 房主使用 [恢复客人角色]（原角色 -> 新 Lv1 角色）。
地图变黑 -> 用别人的 LocalData.sav 执行 [导入地图探索]（推荐 合并）。

========================================================================
 日本語
========================================================================
1. パルワールドを完全に終了します。
2. 展開してから（zip の中から起動しない）PalworldHostChanger.bat をダブルクリック。言語は右上で変更できます。
3. [フォルダを選択] -> 受け取ったワールドフォルダ（%LOCALAPPDATA%\Pal\Saved\SaveGames\<数字>\<32 文字のワールドID>、Level.sav がある場所）
4. ホストにするキャラ（普通は自分）をクリック。
5. [自分のパルワールドに導入] - 同じワールドがある場合は %LOCALAPPDATA%\Pal\Saved\HostChangerBackups へ移して保管。他の人に渡すなら [受け渡し用フォルダに書き出し]。
6. ゲームを起動し、ワールド一覧にそのキャラ名が出ているか確認。
フレンドがキャラ作成画面になる -> 適当なキャラを作って 1 分プレイ -> ホストが [ゲストキャラを復元]（元のキャラ -> 新しい Lv1 キャラ）。
マップが真っ黒 -> 他の人の LocalData.sav で [マップ探索を取り込む]（合成がおすすめ）。

Files: runtime\ = official Python runtime (PSF-signed), app\ = this tool's source code (.py).
Licenses: LICENSE.txt, THIRD_PARTY_NOTICES.txt
