# Third-party notices

Palworld Host Changer is licensed under GPL-3.0-or-later (see `LICENSE`).
The source code and the release `.exe` include or bundle the following components.

## ooz — Oodle Kraken decompressor

- Upstream: https://github.com/powzix/ooz (commit `05038060aa68f9187ae9923b2388ca8db40e58d1`)
- Copyright (C) 2016, Powzix
- License: GNU General Public License v3.0 or later (per the source file headers; full text in `LICENSE`)
- Used as: `src/ooz.dll` (x64), built from the **unmodified** sources in `third_party/ooz/`
  with `third_party/ooz/build_ooz_dll.bat`. Only `Kraken_Decompress` is exported.
- Note from upstream: the decoder is "not fuzz safe" — only open save files you trust.

## palworld-save-tools

- Upstream: https://github.com/cheahjs/palworld-save-tools (version 0.24.0, from PyPI)
- Used for: reading/writing the GVAS structure of `LevelMeta.sav`
- License: MIT

```
MIT License

Copyright (c) 2024 Jun Siang Cheah

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Bundled in the release .exe only

- **Python** runtime — Python Software Foundation License, https://docs.python.org/3/license.html
- **Tcl/Tk** (tkinter GUI) — Tcl/Tk license (BSD-style), https://www.tcl.tk/software/tcltk/license.html
- **PyInstaller** bootloader — GPL-2.0 with the PyInstaller bootloader exception, https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt

## Prior work

- xNul/palworld-host-save-fix (https://github.com/xNul/palworld-host-save-fix) — the original
  approach to host save fixing. No code from it is included.

Palworld is a trademark of Pocketpair, Inc. This is an unofficial fan tool.
