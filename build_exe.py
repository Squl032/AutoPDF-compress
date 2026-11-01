"""
一鍵打包成 exe (使用 PyInstaller)

用法:
    python build_exe.py                 # 單一 exe, 無主控台視窗
    python build_exe.py --console       # 保留主控台視窗 (除錯用, 才看得到 print)
    python build_exe.py --onedir        # 資料夾版 (啟動較快, 但要整個資料夾一起發佈)
    python build_exe.py --yes           # 缺什麼套件就直接安裝, 不詢問

流程: 檢查環境(缺套件可自動安裝) -> 把 lang/ 內的語言檔全部打包進 exe -> PyInstaller 打包
語言規則: exe 內建打包當下 lang/ 的所有語言; 執行時 exe 旁邊若有 lang/ 資料夾,
          其中「內建沒有的語言」會被額外加入; 沒有就只用內建語言。
"""

import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "autopdf.py")
LANG_DIR = os.path.join(HERE, "lang")
YES = "--yes" in sys.argv


def ask(question):
    if YES:
        return True
    try:
        return input(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes", "是")
    except EOFError:
        return False


def main():
    # 1) 程式本身需要的套件 (沿用 autopdf.py 的環境檢查, 缺少會詢問並安裝)
    cmd = [sys.executable, SCRIPT, "--check-env"] + (["--yes"] if YES else [])
    if subprocess.call(cmd) != 0:
        print("環境檢查未通過, 已中止。")
        return 1

    # 2) PyInstaller
    if importlib.util.find_spec("PyInstaller") is None:
        if not ask("找不到 PyInstaller, 要現在安裝嗎?"):
            print("需要 PyInstaller 才能打包: pip install pyinstaller")
            return 1
        if (
            subprocess.call([sys.executable, "-m", "pip", "install", "pyinstaller"])
            != 0
        ):
            print("PyInstaller 安裝失敗。")
            return 1

    # 3) 語言檔
    langs = []
    if os.path.isdir(LANG_DIR):
        langs = [
            f
            for f in sorted(os.listdir(LANG_DIR))
            if f.lower().endswith(".json") and not f.startswith("_")
        ]
    if langs:
        print(
            f"將內建 {len(langs)} 種語言: "
            + ", ".join(os.path.splitext(f)[0] for f in langs)
        )
    else:
        print("警告: 找不到 lang/ 或裡面沒有語言檔, exe 只會內建繁體中文。")

    # 4) 打包
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir" if "--onedir" in sys.argv else "--onefile",
        "--console" if "--console" in sys.argv else "--windowed",
        "--name",
        "autopdf",
    ]
    if langs:
        args += ["--add-data", f"{LANG_DIR}{os.pathsep}lang"]  # 語言檔打包進 exe
    for mod in (
        "customtkinter",
        "tkinterdnd2",
        "pypdfium2",
        "pypdfium2_raw",
        "pillow_heif",
    ):
        if importlib.util.find_spec(mod) is not None:  # 只收集有安裝的 (含資料檔/DLL)
            args += ["--collect-all", mod]
    icon = os.path.join(HERE, "icon.ico")
    if os.path.isfile(icon):
        args += ["--icon", icon]
    args.append(SCRIPT)

    print("\n執行:", " ".join(args), "\n")
    rc = subprocess.call(args, cwd=HERE)
    if rc != 0:
        print("\n打包失敗, 請看上方 PyInstaller 的錯誤訊息。")
        return rc
    exe = os.path.join(
        HERE, "dist", "autopdf" + (".exe" if sys.platform.startswith("win") else "")
    )
    print(f"\n完成: {exe}")
    print(
        "想新增語言: 在 exe 旁邊放 lang 資料夾與新的 .json (同代碼的檔案預設會被內建版取代)。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
