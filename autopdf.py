"""
AutoPDF-compress (改良版)
原專案: https://github.com/eason9709/AutoPDF-compress (README 聲明為 MIT 授權)

功能
- 壓縮 PDF, 並可把 PNG / JPG / WEBP / BMP / TIFF (以及 HEIC / HEIF, 需 pillow-heif) 轉成 PDF
- 合併: 清單中的 PDF 與圖片可依序接成一個 PDF; 拆分: 每個 PDF 依頁數切成多個檔案
- 每個 PDF 可單獨指定頁碼範圍, 例如 1-3,5,8-
- 拖曳檔案/資料夾進視窗
- 多語言: 讀取 lang/ 資料夾內的 .json, 有幾個檔就有幾種語言 (exe 內建最新語言, 旁邊的 lang/ 可再新增)
- 啟動前自動檢查套件, 缺少時可一鍵 pip 安裝 (python autopdf.py --check-env 可手動檢查)
- 自動模式: 設定目標大小, 程式用二分搜尋 JPEG 品質逼近目標, 不夠才降解析度
- 不需要 Poppler: 使用 pypdfium2 渲染, pip 即可安裝
- 記住上次的所有設定 (輸出資料夾、DPI、模式、主題…)
- 淺色 / 深色 / 跟隨系統 三種外觀

注意: 輸出是「圖片式 PDF」, 原本可選取/搜尋的文字會消失。
"""

import collections
import importlib.util
import io
import json
import math
import multiprocessing
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor


class Cancelled(Exception):
    pass


# ----------------------------- 多語言 -----------------------------
# 語言檔放在 lang/ 資料夾, 每個 .json 一種語言:
#   檔名(不含 .json) = 語言代碼, 例如 en.json -> "en"
#   {"_meta": {"name": "English", "font": "(選填)字型名稱"}, "strings": {"鍵": "文字", ...}}
# 缺少的鍵自動退回下面的內建繁體中文; 檔名以 _ 開頭的檔案會被忽略 (例如 _template.json)。
DEFAULT_LANG = "zh_TW"
DEFAULT_STRINGS = {
    "app.title": "PDF 壓縮工具",
    "app.subtitle": "壓縮 · 合併 · 拆分 · 圖片轉 PDF · 自動逼近目標大小",
    "theme.light": "淺色",
    "theme.dark": "深色",
    "theme.system": "系統",
    "files.title": "檔案",
    "files.summary": "檔案  ·  {n} 個  ·  {size}",
    "files.add": "＋ 添加檔案",
    "files.clear": "清除",
    "files.empty_dnd": "尚未加入檔案\n把 PDF 或圖片拖進視窗，或點右上角「＋ 添加檔案」",
    "files.empty": "尚未加入檔案\n點右上角「＋ 添加檔案」選擇 PDF 或圖片",
    "files.badge_pdf": "PDF",
    "files.badge_image": "圖片",
    "files.pages": "{n} 頁",
    "files.pages_unknown": "? 頁",
    "files.range_placeholder": "全部頁面",
    "progress.title": "處理進度",
    "settings.title": "設定",
    "out.folder": "輸出資料夾 (留空 = 與原檔同資料夾)",
    "out.browse": "瀏覽",
    "omode.label": "輸出方式",
    "omode.each": "各自輸出",
    "omode.merge": "合併成一個",
    "omode.split": "拆分頁面",
    "omode.hint.each": "每個檔案各自輸出一個 PDF。PDF 可在清單中填頁碼範圍, 只保留需要的頁面。",
    "omode.hint.merge": "清單中所有檔案 (PDF 與圖片) 依序接成一個 PDF, 可用 ↑ ↓ 調整順序。",
    "omode.hint.split": "每個 PDF 依頁數拆成多個檔案 (圖片不受影響, 仍各自輸出)。",
    "merge.name": "合併後檔名",
    "split.every": "每",
    "split.pages": "頁拆成一個檔案",
    "cmode.label": "壓縮模式",
    "cmode.auto": "自動壓到目標大小",
    "cmode.manual": "手動設定",
    "target.label": "目標大小 (MB, 每個輸出檔)",
    "dpi.label": "DPI (自動模式為起始值)",
    "quality.label": "JPEG 品質 (僅手動模式)",
    "gray.switch": "轉灰階 (文件可再縮小很多)",
    "btn.start": "開始轉換",
    "btn.cancel": "取消",
    "btn.open_out": "開啟輸出資料夾",
    "dlg.pick": "選擇 PDF 或圖片",
    "dlg.ft_supported": "PDF 與圖片",
    "dlg.ft_pdf": "PDF",
    "dlg.ft_all": "所有檔案",
    "msg.error": "錯誤",
    "msg.done": "完成",
    "msg.bad_range": "頁碼有問題",
    "msg.no_files": "請先添加要轉換的 PDF 或圖片！",
    "msg.bad_target": "目標大小請輸入大於 0 的數字",
    "msg.lang_busy": "處理中無法切換語言",
    "log.skipped": "略過 {n} 個不支援的檔案",
    "log.skipped_heif": " (想支援 HEIC 請 pip install pillow-heif)",
    "log.sampling": "頁數較多 ({n} 頁), 先抽樣 {k} 頁估算壓縮設定",
    "log.retry": "實際大小 {size} 超過目標, 調整後重試 ({i}/{max})",
    "log.gray_note": ", 灰階",
    "log.low_quality": "⚠ 為達成目標大小已大幅降低畫質, 內容可能難以閱讀",
    "perf.label": "效能模式",
    "perf.eco": "省資源",
    "perf.balanced": "平衡",
    "perf.fast": "高速",
    "perf.hint": "偵測到 {cores} 核心、記憶體 {total} (可用 {avail})。此模式最多同時 {w} 個處理程序平行處理, 額外約用 {mem} 記憶體, 頁數多時較快。",
    "perf.hint_single": "偵測到 {cores} 核心、記憶體 {total} (可用 {avail})。此模式只用單一處理程序, 最省資源。",
    "log.parallel": "使用 {w} 個處理程序平行處理",
    "tfirst.switch": "優先達成目標大小",
    "tfirst.hint": "必要時大幅降低畫質並自動轉灰階 (關閉則保留最低畫質)",
    "log.dpi_q": "DPI {dpi}, 品質 {q}",
    "log.limit_note": " (仍超過目標, 已是極限)",
    "lang.load_failed": "語言檔 {file} 無法讀取: {err}",
    "job.merge": "合併 {n} 個檔案",
    "job.split_part": "{name} 第 {j}/{total} 份",
    "run.item": "[{i}/{total}] {label}",
    "run.done_compare": "  完成: {before} KB → {after} KB  ({pct}%)",
    "run.already_small": "  原檔 ({size}) 已小於目標大小, 直接複製, 不重新壓縮",
    "run.warn_bigger": "  ⚠ 壓縮後沒有變小 (原檔可能已經很小), 建議保留原檔",
    "run.done_out": "  完成: {size} → {file}",
    "run.cancelled": "  已取消",
    "run.failed": "  失敗: {err}",
    "run.summary": "處理結束: 成功 {ok}/{total} 項",
    "run.summary_cancelled": "  (已取消)",
    "err.with_file": "{name}: {msg}",
    "err.pdf_open": "無法開啟 {name} (可能有密碼保護或檔案損毀)",
    "err.pdf_no_pages": "{name} 沒有任何頁面",
    "err.pdf_page_out": "{name} 的頁碼超出範圍 (共 {n} 頁)",
    "err.img_read": "無法讀取圖片 {name}",
    "err.range_parse": "看不懂頁碼「{part}」, 格式範例: 1-3,5,8-",
    "err.range_reversed": "頁碼「{part}」的起始頁大於結束頁",
    "err.range_out": "頁碼「{part}」超出範圍 (此檔共 {n} 頁)",
    "err.range_empty": "沒有選到任何頁面",
    "err.no_pagecount_range": "讀不到頁數, 無法套用頁碼範圍",
    "err.no_pagecount_split": "讀不到頁數 (可能有密碼), 無法拆分",
    "dnd.unavailable": "拖曳功能無法使用 ({err}), 請確認已安裝 tkinterdnd2 (pip install tkinterdnd2)",
    "dnd.admin": "目前以系統管理員身分執行, Windows 會阻擋從檔案總管拖曳檔案進來。請改用一般權限開啟程式 (或使用「＋ 添加檔案」)。",
    "env.title": "環境檢查",
    "env.required": "必要套件 (缺少就無法執行):",
    "env.optional": "選用套件 (拖曳檔案、HEIC 圖片支援):",
    "env.ask": "要現在自動安裝嗎? (需要網路連線)",
    "env.installing_title": "安裝套件中",
    "env.installing": "正在安裝: {pkgs}\n請稍候, 完成後會自動啟動程式...",
    "env.install_failed": "套件安裝失敗:\n\n{err}\n\n請手動執行:\n{cmd}",
    "env.optional_failed": "選用套件安裝失敗, 已略過 (不影響主要功能):\n{pkgs}\n\n之後不會再詢問。",
    "env.declined": "未安裝必要套件, 程式無法執行。\n手動安裝指令:\n{cmd}",
    "env.no_tk": "找不到 tkinter, 無法顯示視窗。\n{hint}",
    "env.hint_linux": "請執行: sudo apt install python3-tk",
    "env.hint_other": "請重新安裝 Python, 並確認勾選 tcl/tk 元件。",
    "lang.skipped_bundled": '語言檔 {files} 與 exe 內建語言同代碼, 已使用內建的最新版 (要覆蓋請在檔案的 _meta 加上 "override": true)',
    "cli.no_ctk": "缺少 customtkinter, 請先執行: pip install -r requirements.txt",
}


def app_dir():
    """程式所在資料夾 (打包成 exe 時為 exe 所在資料夾)。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def lang_sources():
    """回傳 [(資料夾, 是否為內建)], 依優先順序。
    內建 = 打包進 exe 的 lang (最新版, 優先); 外部 = exe/腳本旁邊與目前工作目錄的 lang。"""
    cands = []
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        cands.append((os.path.join(sys._MEIPASS, "lang"), True))
    cands.append((os.path.join(app_dir(), "lang"), False))
    cands.append((os.path.join(os.getcwd(), "lang"), False))
    seen, out = set(), []
    for d, bundled in cands:
        key = os.path.normcase(os.path.realpath(d))
        if key not in seen and os.path.isdir(d):
            seen.add(key)
            out.append((d, bundled))
    return out


def system_locale():
    if sys.platform.startswith("win"):
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                return buf.value  # 例如 zh-TW
        except Exception:
            pass
    for v in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(v)
        if val:
            return val.split(".")[0]
    try:
        import locale

        return locale.getlocale()[0] or ""
    except Exception:
        return ""


class I18N:
    def __init__(self):
        self.langs = {}  # 代碼 -> {"name", "strings", "font", "path"}
        self.errors = []  # [(檔名, 錯誤訊息)]
        self.skipped = []  # 與內建語言同代碼而被忽略的外部檔
        self.code = DEFAULT_LANG
        self.scan()

    @staticmethod
    def _parse(path, stem):
        with open(path, encoding="utf-8-sig") as f:  # utf-8-sig: 相容記事本存的 BOM
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("top level must be a JSON object")
        meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
        raw = data.get("strings")
        if not isinstance(raw, dict):  # 容錯: 允許不包 "strings", 直接平鋪
            raw = {k: v for k, v in data.items() if not k.startswith("_")}
        strings = {k: v for k, v in raw.items() if isinstance(v, str)}
        if not strings:
            raise ValueError("no usable translation strings")
        return {
            "name": str(meta.get("name") or stem),
            "named": bool(meta.get("name")),
            "strings": strings,
            "font": str(meta.get("font") or ""),
            "path": path,
            "override": bool(meta.get("override")),
            "bundled": False,
        }

    def scan(self):
        """exe: 先載入內建語言, 外部 lang/ 只『新增』內建沒有的語言 (同代碼預設忽略,
        除非外部檔 _meta 寫 "override": true, 則以內建為底、疊上外部的文字)。
        腳本模式: 直接讀 lang/ 資料夾, 有幾個 json 就有幾種語言。"""
        self.langs, self.errors, self.skipped = {}, [], []
        bundled_codes = set()
        for d, bundled in lang_sources():
            for fn in sorted(os.listdir(d)):
                stem, ext = os.path.splitext(fn)
                if ext.lower() != ".json" or stem.startswith("_"):
                    continue
                try:
                    entry = self._parse(os.path.join(d, fn), stem)
                except (
                    OSError,
                    ValueError,
                ) as e:  # JSONDecodeError 是 ValueError 的子類
                    self.errors.append((fn, str(e)))
                    continue
                if stem in self.langs:
                    if stem in bundled_codes and not bundled:
                        if entry["override"]:
                            old = self.langs[stem]
                            old["strings"] = {**old["strings"], **entry["strings"]}
                            if entry["named"]:
                                old["name"] = entry["name"]
                            if entry["font"]:
                                old["font"] = entry["font"]
                        else:
                            self.skipped.append(fn)
                    continue  # 其餘情況: 同代碼先到先得
                entry["bundled"] = bundled
                self.langs[stem] = entry
                if bundled:
                    bundled_codes.add(stem)
        if DEFAULT_LANG not in self.langs:  # 內建語言永遠可用
            self.langs[DEFAULT_LANG] = {
                "name": "繁體中文",
                "strings": {},
                "font": "",
                "path": "",
                "override": False,
                "named": True,
                "bundled": True,
            }
        self.langs = dict(sorted(self.langs.items()))
        if self.code not in self.langs:
            self.code = DEFAULT_LANG

    def guess(self):
        loc = system_locale().replace("-", "_").lower()
        if not loc:
            return DEFAULT_LANG
        low = {c.lower(): c for c in self.langs}
        if loc in low:
            return low[loc]
        lang = loc.split("_")[0]
        if lang == "zh":
            trad = any(k in loc for k in ("tw", "hk", "mo", "hant"))
            for c in (("zh_tw", "zh_hant") if trad else ("zh_cn", "zh_hans")):
                if c in low:
                    return low[c]
        for lc, c in low.items():
            if lc.split("_")[0] == lang:
                return c
        return DEFAULT_LANG

    def set(self, code):
        """code 為空或不存在 -> 依系統語言自動挑選。回傳實際採用的代碼。"""
        self.code = code if code in self.langs else self.guess()
        return self.code

    def font(self):
        return self.langs.get(self.code, {}).get("font", "")

    def t(self, key, **kw):
        s = self.langs.get(self.code, {}).get("strings", {}).get(key)
        if s is None:
            s = DEFAULT_STRINGS.get(key, key)
        try:
            return s.format(**kw) if kw else s
        except (KeyError, IndexError, ValueError):  # 翻譯檔的占位符寫錯時不要讓程式壞掉
            try:
                return DEFAULT_STRINGS.get(key, key).format(**kw)
            except Exception:
                return s


I18N_ = I18N()


def t(key, **kw):
    return I18N_.t(key, **kw)


def export_lang_template(path=None):
    """輸出翻譯範本 (lang/_template.json), 翻譯者複製後改檔名與內容即可。"""
    path = path or os.path.join(app_dir(), "lang", "_template.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "_meta": {"name": "Your Language Name", "font": ""},
        "strings": DEFAULT_STRINGS,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


# ----------------------------- 設定檔 -----------------------------
DEFAULTS = {
    "output_dir": "",
    "dpi": 150,
    "quality": 75,
    "auto": True,
    "target_mb": 4.0,
    "gray": False,
    "theme": "system",
    "language": "",
    "skip_optional_packages": False,
    "target_first": True,
    "perf_mode": "balanced",  # language 空字串 = 依系統語言
    "output_mode": "each",  # each=各自輸出 / merge=合併成一個 / split=拆分頁面
    "split_n": 1,
    "merge_name": "merged",
}


def config_path():
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "AutoPDF", "settings.json")


def load_settings():
    cfg = dict(DEFAULTS)
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            if k in cfg and type(v) is type(cfg[k]):
                cfg[k] = v
    except (OSError, ValueError):
        pass
    return cfg


def save_settings(cfg):
    try:
        p = config_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # 存不了設定不該讓程式壞掉


# ----------------------------- 環境檢查 -----------------------------
# 直接執行 .py 時, 在匯入第三方套件之前先檢查; 缺少就詢問是否自動 pip 安裝。
# 打包成 exe 後套件都已內建, 不會執行這段。
REQUIRED_PKGS = [
    ("customtkinter", "customtkinter>=5.2.0"),
    ("pypdfium2", "pypdfium2"),
    ("PIL", "pillow"),
]
OPTIONAL_PKGS = [("pillow_heif", "pillow-heif"), ("tkinterdnd2", "tkinterdnd2")]


def _pkg_missing(pkgs):
    return [spec for mod, spec in pkgs if importlib.util.find_spec(mod) is None]


def _pip_name(spec):
    return re.split(r"[<>=!~\s]", spec, 1)[0]


def _pkg_version(spec):
    try:
        from importlib import metadata

        return metadata.version(_pip_name(spec))
    except Exception:
        return None


def _manual_cmd(specs):
    return f'"{sys.executable}" -m pip install ' + " ".join(f'"{s}"' for s in specs)


def _run_pip(specs):
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        *specs,
    ]
    kw = (
        {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}
    )  # 不跳黑視窗
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kw,
        )
        return p.returncode == 0, ((p.stderr or "") + (p.stdout or "")).strip()[-700:]
    except Exception as e:
        return False, str(e)


def _tk_root():
    try:
        import tkinter as tk_

        r = tk_.Tk()
        r.withdraw()
        return tk_, r
    except Exception:
        return None, None


def _dialog(kind, title, msg):
    """kind: info / error / yesno。沒有視窗環境時退回主控台。"""
    tk_, r = _tk_root()
    if r is not None:
        try:
            from tkinter import messagebox as mb

            r.attributes("-topmost", True)
            fn = {"info": mb.showinfo, "error": mb.showerror, "yesno": mb.askyesno}[
                kind
            ]
            return fn(title, msg, parent=r)
        except Exception:
            pass
        finally:
            try:
                r.destroy()
            except Exception:
                pass
    print(f"\n[{title}]\n{msg}")
    if kind == "yesno":
        try:
            return input("[Y/n] ").strip().lower() in ("", "y", "yes", "是")
        except EOFError:
            return False
    return None


def _install_steps(steps):
    """steps: [(名稱, [套件規格])], 依序 pip 安裝並顯示進度視窗。必要套件失敗就不再繼續。"""
    results = {}

    def work():
        for name, specs in steps:
            ok, out = _run_pip(specs)
            results[name] = (ok, out)
            if not ok and name == "req":
                break

    th = threading.Thread(target=work, daemon=True)
    th.start()
    tk_, r = _tk_root()
    if r is not None:
        try:
            from tkinter import ttk as ttk_

            r.deiconify()
            r.title(t("env.installing_title"))
            r.resizable(False, False)
            pkgs = ", ".join(sp for _, specs in steps for sp in specs)
            tk_.Label(
                r, text=t("env.installing", pkgs=pkgs), justify="left", padx=22, pady=14
            ).pack()
            pb = ttk_.Progressbar(r, mode="indeterminate", length=340)
            pb.pack(padx=22, pady=(0, 18))
            pb.start(12)

            def poll():
                if th.is_alive():
                    r.after(150, poll)
                else:
                    r.destroy()

            r.after(150, poll)
            r.mainloop()
        except Exception:
            pass
    else:
        print(
            t(
                "env.installing",
                pkgs=", ".join(sp for _, specs in steps for sp in specs),
            )
        )
    th.join()
    return results


def ensure_environment(auto=False, report=False):
    """檢查執行環境。缺少套件時詢問 (auto=True 則直接安裝)。回傳 True = 可以繼續執行。"""
    cfg = load_settings()
    I18N_.set(cfg["language"])
    if importlib.util.find_spec("tkinter") is None:
        hint = (
            t("env.hint_linux")
            if sys.platform.startswith("linux")
            else t("env.hint_other")
        )
        print(t("env.no_tk", hint=hint))
        return False

    req = _pkg_missing(REQUIRED_PKGS)
    # --yes 會無視「不再詢問」, 方便之後想補裝選用套件時使用
    opt = (
        []
        if (cfg.get("skip_optional_packages") and not auto)
        else _pkg_missing(OPTIONAL_PKGS)
    )
    if req or opt:
        parts = []
        if req:
            parts.append(t("env.required") + "\n" + "\n".join("  • " + x for x in req))
        if opt:
            parts.append(t("env.optional") + "\n" + "\n".join("  • " + x for x in opt))
        msg = "\n\n".join(parts) + "\n\n" + t("env.ask")
        if auto or _dialog("yesno", t("env.title"), msg):
            res = _install_steps([x for x in (("req", req), ("opt", opt)) if x[1]])
            importlib.invalidate_caches()
            if req and not res.get("req", (False, ""))[0]:
                _dialog(
                    "error",
                    t("env.title"),
                    t(
                        "env.install_failed",
                        err=res.get("req", (False, ""))[1],
                        cmd=_manual_cmd(req),
                    ),
                )
                return False
            if opt and not res.get("opt", (False, ""))[0]:
                _dialog(
                    "info",
                    t("env.title"),
                    t("env.optional_failed", pkgs=", ".join(opt)),
                )
                cfg["skip_optional_packages"] = True
                save_settings(cfg)
        elif req:
            _dialog("error", t("env.title"), t("env.declined", cmd=_manual_cmd(req)))
            return False
        else:  # 只缺選用套件而使用者選「否」: 記住, 之後不再詢問
            cfg["skip_optional_packages"] = True
            save_settings(cfg)

    still = _pkg_missing(REQUIRED_PKGS)
    if still:
        _dialog(
            "error",
            t("env.title"),
            t("env.install_failed", err="import failed", cmd=_manual_cmd(still)),
        )
        return False
    if report:
        print(f"Python {sys.version.split()[0]} ({sys.executable})")
        for mod, spec in REQUIRED_PKGS + OPTIONAL_PKGS:
            ver = _pkg_version(spec) if importlib.util.find_spec(mod) else None
            kind = "required" if (mod, spec) in REQUIRED_PKGS else "optional"
            print(
                f"  [{'OK' if ver or importlib.util.find_spec(mod) else '--'}] "
                f"{_pip_name(spec)} {ver or ''} ({kind})".rstrip()
            )
    return True


if __name__ == "__main__" and not getattr(sys, "frozen", False):
    if "--export-lang" in sys.argv:
        print(export_lang_template())
        sys.exit(0)
    if "--no-env-check" not in sys.argv:
        if not ensure_environment(
            auto="--yes" in sys.argv, report="--check-env" in sys.argv
        ):
            sys.exit(1)
    if "--check-env" in sys.argv:
        sys.exit(0)


import pypdfium2 as pdfium
from PIL import Image, ImageOps

try:  # 選用: 支援 iPhone 的 HEIC / HEIF
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:
    HEIF_OK = False

try:  # 選用: 拖曳檔案進視窗
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_OK, DND_ERR = True, ""
except Exception as _e:
    DND_OK, DND_ERR = False, str(_e) or type(_e).__name__

try:  # GUI 套件缺少時仍可 import 核心函式
    import customtkinter as ctk
    from tkinter import filedialog, messagebox
except ImportError:
    ctk = None

# ----------------------------- 可調參數 -----------------------------
MAX_AUTO_QUALITY = 90  # (保留) 自動模式品質上限
MIN_DPI = 72  # 一般階梯的解析度下限
HARD_MIN_DPI = 30  # 「優先達成目標」時的解析度下限
FALLBACK_QUALITY = 35  # 所有階梯都超標時, 最後一階再壓一次用的品質
SAMPLE_BYTES = 128 * 1024**2  # 抽樣階段最多同時放在記憶體的點陣圖大小
SAMPLE_MAX_PAGES = 40
MP_MIN_PAGES = 12  # 頁數少於此值不值得啟動多處理程序 (啟動要約 1 秒)
WORKER_MEM = (
    450 * 1024**2
)  # 估計每個工作程序需要的記憶體 (pdfium + 一頁點陣圖 + 編碼緩衝)
PERF_MODES = ("eco", "balanced", "fast")
MAX_ATTEMPTS = 4  # 抽樣估算不準時, 最多修正重試幾次
# 階梯 = (解析度比例, 品質下限, 品質上限, 是否轉灰階); 先保品質, 保不住才降解析度, 最後才轉灰階
TIERS_NORMAL = [
    (1.0, 50, 90, False),
    (0.85, 50, 90, False),
    (0.7, 50, 90, False),
    (0.6, 50, 90, False),
    (0.5, 50, 90, False),
]
TIERS_EXTRA = [
    (0.5, 50, 90, True),
    (0.4, 40, 90, True),
    (0.33, 30, 90, True),
    (0.25, 20, 90, True),
    (0.2, 15, 60, True),
]
WORKERS = max(1, os.cpu_count() or 1)
A4_PT = (595.28, 841.89)

NO_DND = "--no-dnd" in sys.argv  # 診斷用: 停用拖曳, 用來判斷介面異常是否與拖曳套件有關
# Windows 上 CustomTkinter 啟動時會自己隱藏/重顯示視窗, 第一次建好的介面偶爾有元件沒畫出來,
# 所以啟動後重建一次 (和切換語言走同一條路徑)。其他系統不需要。
FIRST_RUN_REFRESH = sys.platform.startswith("win")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
if HEIF_OK:
    IMAGE_EXTS |= {".heic", ".heif"}
SUPPORTED_EXTS = IMAGE_EXTS | {".pdf"}


# ----------------------------- 核心 -----------------------------
def _encode_jpeg(im, quality):
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def encode_all(pool, images, quality):
    return list(pool.map(lambda im: _encode_jpeg(im, quality), images))


def scale_all(pool, images, s):
    if s == 1.0:
        return images
    return list(
        pool.map(
            lambda im: im.resize(
                (max(1, round(im.width * s)), max(1, round(im.height * s))),
                Image.LANCZOS,
            ),
            images,
        )
    )


def estimated_pdf_size(jpegs):
    return sum(len(j) for j in jpegs) + 420 * len(jpegs) + 600


def _payload(jpegs):
    return sum(len(j) for j in jpegs)


def is_pdf(path):
    return path.lower().endswith(".pdf")


def parse_page_ranges(text, n):
    """'1-3,5,8-' -> 0 起算的頁索引清單 (保留順序)。空字串 = 全部頁面。"""
    txt = (text or "").strip()
    if txt in ("", "全部", "all", "ALL"):
        return list(range(n))
    for ch, rep in (
        ("，", ","),
        ("、", ","),
        ("－", "-"),
        ("–", "-"),
        ("～", "-"),
        ("~", "-"),
        (" ", ""),
    ):
        txt = txt.replace(ch, rep)
    out = []
    for part in txt.split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                lo, hi = (int(a) if a else 1), (int(b) if b else n)
            else:
                lo = hi = int(part)
        except ValueError:
            raise ValueError(t("err.range_parse", part=part)) from None
        if lo > hi:
            raise ValueError(t("err.range_reversed", part=part))
        if lo < 1 or hi > n:
            raise ValueError(t("err.range_out", part=part, n=n))
        out.extend(range(lo - 1, hi))
    if not out:
        raise ValueError(t("err.range_empty"))
    return out


def pdf_page_count(path):
    try:
        with open(path, "rb") as fh:
            pdf = pdfium.PdfDocument(fh)
            try:
                return len(pdf)
            finally:
                pdf.close()
    except Exception:
        return None


def _open_pdf(path):
    fh = open(path, "rb")  # 用檔案物件開, 避免 Windows 中文路徑問題
    try:
        return pdfium.PdfDocument(fh), fh
    except Exception as e:
        fh.close()
        raise ValueError(t("err.pdf_open", name=os.path.basename(path))) from e


def _prepare_image(path, gray):
    with Image.open(path) as im0:
        im0.load()
        im = ImageOps.exif_transpose(im0)  # 手機照片的旋轉資訊
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    return im.convert("L" if gray else "RGB")


def _fit_a4(w, h):
    W, H = (A4_PT[1], A4_PT[0]) if w > h else A4_PT
    s = min(W / w, H / h)
    return w * s, h * s


class _DocCache:
    """只保留最近使用的一份 PDF: 頁面通常依序處理所以命中率高, 也不會同時開太多檔案。"""

    def __init__(self):
        self._cur = None

    def get(self, path):
        if self._cur and self._cur[0] == path:
            return self._cur[1]
        self.close()
        pdf, fh = _open_pdf(path)
        self._cur = (path, pdf, fh)
        return pdf

    def close(self):
        if self._cur:
            _, pdf, fh = self._cur
            for c in (pdf, fh):
                try:
                    c.close()
                except Exception:
                    pass
            self._cur = None


def _render_page(docs, kind, path, idx, size, dpi, gray):
    """渲染一頁 -> (PIL 圖片, 頁面尺寸 pt)。主程式與多處理程序的工作程序共用。"""
    if kind == "pdf":
        page = docs.get(path)[idx]
        try:
            bmp = page.render(scale=dpi / 72, grayscale=gray)
            im = bmp.to_pil().convert("L" if gray else "RGB")
        finally:
            page.close()
        return im, size
    im = _prepare_image(path, gray)
    wpt, hpt = _fit_a4(*im.size)
    tw = max(1, round(wpt / 72 * dpi))
    if im.width > tw:  # 只縮小, 不放大
        im = im.resize((tw, max(1, round(im.height * tw / im.width))), Image.LANCZOS)
    return im, (wpt, hpt)


class PageSource:
    """依序提供所有輸出頁面。一次只渲染一頁, 不會把整份文件的點陣圖放進記憶體,
    所以記憶體用量與頁數無關。"""

    def __init__(self, items, cancel):
        self.cancel = cancel
        self.pages = []  # (種類, 路徑, 頁索引, 頁面尺寸 pt)
        self._docs = _DocCache()
        try:
            for path, pages in items:
                name = os.path.basename(path)
                if is_pdf(path):
                    pdf = self._docs.get(path)
                    n = len(pdf)
                    if n == 0:
                        raise ValueError(t("err.pdf_no_pages", name=name))
                    idx = list(pages) if pages is not None else list(range(n))
                    if any(i < 0 or i >= n for i in idx):
                        raise ValueError(t("err.pdf_page_out", name=name, n=n))
                    for i in idx:
                        pg = pdf[i]
                        size = pg.get_size()
                        pg.close()
                        self.pages.append(("pdf", path, i, size))
                else:
                    try:
                        with Image.open(path) as im:
                            w, h = im.size
                    except Exception as e:
                        raise ValueError(t("err.img_read", name=name)) from e
                    self.pages.append(("img", path, None, _fit_a4(w, h)))
        except Exception:
            self.close()
            raise

    def close(self):
        self._docs.close()

    def render(self, i, dpi, gray):
        """渲染第 i 頁, 回傳 (PIL 圖片, 頁面尺寸 pt)。"""
        return _render_page(self._docs, *self.pages[i], dpi, gray)

    def avg_page_bytes(self, dpi, gray):
        bpp = 1 if gray else 3
        return sum(
            w / 72 * dpi * h / 72 * dpi * bpp for *_, (w, h) in self.pages
        ) / len(self.pages)


_WORKER_DOCS = None


def _mp_task(args):
    """在工作程序中渲染 + JPEG 編碼一頁, 只把壓縮後的位元組傳回主程式 (傳輸量小)。"""
    global _WORKER_DOCS
    kind, path, idx, size, dpi, gray, quality = args
    if _WORKER_DOCS is None:
        _WORKER_DOCS = _DocCache()
    im, size_pt = _render_page(_WORKER_DOCS, kind, path, idx, size, dpi, gray)
    return _encode_jpeg(im, quality), im.size, size_pt


class _MPPool:
    """多處理程序渲染 (pdfium 不是執行緒安全, 要平行就得用多個程序)。延遲建立, 失敗時退回單程序。"""

    def __init__(self, workers):
        self.workers = workers
        self.broken = workers <= 1
        self._ex = None

    def executor(self):
        if self._ex is None:  # 一律用 spawn: 各系統行為一致, 也是 Windows 唯一的選擇
            self._ex = ProcessPoolExecutor(
                max_workers=self.workers,
                mp_context=multiprocessing.get_context("spawn"),
            )
        return self._ex

    def close(self, wait=True):
        if self._ex is not None:
            try:
                self._ex.shutdown(wait=wait, cancel_futures=True)
            except Exception:
                pass
            self._ex = None


def _stream_encode_mp(src, mp, dpi, quality, gray, cancel, prog):
    n = len(src.pages)
    jpegs, px, sizes = [None] * n, [None] * n, [None] * n
    ex = mp.executor()
    pending = collections.deque()
    nxt = 0
    for done in range(n):
        if cancel.is_set():
            raise Cancelled
        while (
            nxt < n and len(pending) < mp.workers * 3
        ):  # 限制排隊數量, 也讓頁面大致依序處理
            kind, path, idx, size = src.pages[nxt]
            pending.append(
                (nxt, ex.submit(_mp_task, (kind, path, idx, size, dpi, gray, quality)))
            )
            nxt += 1
        i, fut = pending.popleft()
        jpegs[i], px[i], sizes[i] = fut.result()
        prog((done + 1) / n)
    return jpegs, px, sizes


def stream_encode(src, pool, dpi, quality, gray, cancel, prog, mp=None):
    """逐頁渲染 -> JPEG 編碼。記憶體只會同時存在少數幾頁的點陣圖。
    有 mp 時用多個程序平行渲染 (失敗會自動退回單程序)。"""
    if mp is not None and not mp.broken:
        try:
            return _stream_encode_mp(src, mp, dpi, quality, gray, cancel, prog)
        except Cancelled:
            mp.close(wait=False)
            raise
        except Exception:
            mp.broken = True  # 多程序出問題 (例如被防毒擋下), 改回單程序重做
            mp.close(wait=False)
    n = len(src.pages)
    jpegs, px, sizes = [None] * n, [None] * n, [None] * n
    pending = collections.deque()

    def finish(entry):
        i, fut = entry
        jpegs[i] = fut.result()

    for i in range(n):
        if cancel.is_set():
            raise Cancelled
        im, size = src.render(i, dpi, gray)
        px[i], sizes[i] = im.size, size
        pending.append((i, pool.submit(_encode_jpeg, im, quality)))
        del im
        while len(pending) > WORKERS * 2:  # 限制排隊中的點陣圖數量
            finish(pending.popleft())
        prog((i + 1) / n)
    while pending:
        finish(pending.popleft())
    return jpegs, px, sizes


def write_pdf(path, jpegs, px_sizes, sizes_pt, gray):
    """手寫最小 PDF: 直接嵌入 JPEG 位元組, 不重新編碼。"""
    cs = b"/DeviceGray" if gray else b"/DeviceRGB"
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []

    def add(body):
        offsets.append(len(out))
        out.extend(f"{len(offsets)} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")

    n = len(jpegs)
    kids = " ".join(f"{3 + 3 * i} 0 R" for i in range(n))
    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    for i, (jpg, (pw, ph), (w, h)) in enumerate(zip(jpegs, px_sizes, sizes_pt)):
        cont_no, img_no = 4 + 3 * i, 5 + 3 * i
        add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w:.2f} {h:.2f}] "
            f"/Contents {cont_no} 0 R "
            f"/Resources << /XObject << /Im0 {img_no} 0 R >> >> >>".encode()
        )
        content = f"q {w:.2f} 0 0 {h:.2f} 0 0 cm /Im0 Do Q".encode()
        add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        add(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s "
            b"/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n"
            % (pw, ph, cs, len(jpg))
            + jpg
            + b"\nendstream"
        )
    xref = len(out)
    out.extend(b"xref\n0 %d\n0000000000 65535 f \n" % (len(offsets) + 1))
    for off in offsets:
        out.extend(b"%010d 00000 n \n" % off)
    out.extend(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(offsets) + 1, xref)
    )
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(out)
    os.replace(tmp, path)


def _tiers(base_dpi, gray, target_first):
    """壓縮『階梯』: (解析度比例, 品質下限, 品質上限, 轉灰階)。依序嘗試, 越後面畫質越差。"""
    out = [x for x in TIERS_NORMAL if x[0] == 1.0 or base_dpi * x[0] >= MIN_DPI]
    if target_first:
        out += [x for x in TIERS_EXTRA if base_dpi * x[0] >= HARD_MIN_DPI]
    if gray:  # 已經是灰階, 『轉灰階』階梯與彩色階梯相同, 去除重複
        out = [(s, lo, hi, False) for s, lo, hi, _ in out]
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _search(pool, images, payload_budget, gray, tiers, bump):
    """在 images (可能只是抽樣) 上找出『符合預算的最高畫質』設定。
    回傳 dict(s, q, gray, data, imgs, fits)。"""
    last = None
    for s, qlo, qhi, g in tiers:
        imgs = scale_all(pool, images, s)
        g_eff = gray or g
        if g and not gray:
            imgs = list(pool.map(lambda im: im.convert("L"), imgs))
        data = encode_all(pool, imgs, qhi)
        bump()
        if _payload(data) <= payload_budget:
            return dict(s=s, q=qhi, gray=g_eff, data=data, imgs=imgs, fits=True)
        data = encode_all(pool, imgs, qlo)
        bump()
        last = (s, qlo, g_eff, data, imgs)
        if _payload(data) > payload_budget:
            continue
        best_q, best = qlo, data
        lo, hi = qlo + 1, qhi - 1
        while lo <= hi:  # 二分搜尋「仍符合預算的最高品質」
            mid = (lo + hi) // 2
            d = encode_all(pool, imgs, mid)
            bump()
            if _payload(d) <= payload_budget:
                best_q, best, lo = mid, d, mid + 1
            else:
                hi = mid - 1
        return dict(s=s, q=best_q, gray=g_eff, data=best, imgs=imgs, fits=True)
    s, q, g_eff, data, imgs = last  # 全部階梯都超標: 取最後一階, 再壓一次
    fq = min(q, FALLBACK_QUALITY)
    if fq < q:
        data = encode_all(pool, imgs, fq)
        bump()
    return dict(
        s=s,
        q=fq,
        gray=g_eff,
        data=data,
        imgs=imgs,
        fits=_payload(data) <= payload_budget,
    )


def _sample_indices(n, k):
    if k >= n:
        return list(range(n))
    return sorted({round(j * (n - 1) / (k - 1)) for j in range(k)})


def convert(
    items,
    dst,
    *,
    dpi=150,
    quality=75,
    target_kb=None,
    gray=False,
    target_first=True,
    workers=1,
    cancel=None,
    log=print,
    progress=lambda f: None,
):
    """
    items: [(路徑, 頁索引清單或 None), ...] -> 單一輸出 PDF (PDF/圖片可混合 = 合併)。
    target_kb=None -> 手動 (固定 dpi+quality)
    target_kb=數字 -> 自動逼近目標; target_first=True 時, 品質壓不下去會繼續降解析度/品質並轉灰階。
    頁數少: 全部頁面放進記憶體精確搜尋; 頁數多: 抽樣估算 + 逐頁串流, 記憶體用量固定。
    回傳輸出 KB。
    """
    cancel = cancel or threading.Event()
    last = [0.0]

    def prog(f):  # 進度只增不減
        last[0] = max(last[0], min(1.0, f))
        progress(last[0])

    def mk_bump(base, span, steps=10):
        cnt = [0]

        def bump():
            cnt[0] += 1
            prog(base + span * min(1.0, cnt[0] / steps))
            if cancel.is_set():
                raise Cancelled

        return bump

    src = PageSource(items, cancel)
    mp = _MPPool(1)
    try:
        n = len(src.pages)
        mp = _MPPool(workers if n >= MP_MIN_PAGES else 1)  # 頁數太少不值得啟動多程序
        prog(0.02)
        with ThreadPoolExecutor(WORKERS) as pool:
            if target_kb is None:  # ---- 手動: 固定參數, 逐頁串流 ----
                if not mp.broken:
                    log("  " + t("log.parallel", w=mp.workers))
                jpegs, px, sizes = stream_encode(
                    src,
                    pool,
                    dpi,
                    quality,
                    gray,
                    cancel,
                    lambda f: prog(0.02 + 0.96 * f),
                    mp,
                )
                final_gray = gray
                log("  " + t("log.dpi_q", dpi=f"{dpi:.0f}", q=quality))
            else:  # ---- 自動: 逼近目標大小 ----
                budget = target_kb * 1024
                overhead = 420 * n + 600
                tiers = _tiers(dpi, gray, target_first)
                k_max = int(
                    max(
                        6,
                        min(
                            SAMPLE_MAX_PAGES,
                            SAMPLE_BYTES // max(1, src.avg_page_bytes(dpi, gray)),
                        ),
                    )
                )
                if n <= k_max:  # 頁數少: 全部渲染一次, 精確搜尋
                    imgs, sizes = [], []
                    for i in range(n):
                        if cancel.is_set():
                            raise Cancelled
                        im, size = src.render(i, dpi, gray)
                        imgs.append(im)
                        sizes.append(size)
                        prog(0.02 + 0.40 * (i + 1) / n)
                    res = _search(
                        pool, imgs, budget - overhead, gray, tiers, mk_bump(0.42, 0.54)
                    )
                    jpegs, px = res["data"], [im.size for im in res["imgs"]]
                    ok = res["fits"]
                    del imgs
                else:  # 頁數多: 抽樣估算 -> 逐頁串流 -> 驗證, 必要時修正重試
                    idx = _sample_indices(n, k_max)
                    log("  " + t("log.sampling", n=n, k=len(idx)))
                    if not mp.broken:
                        log("  " + t("log.parallel", w=mp.workers))
                    sample = []
                    for j, i in enumerate(idx):
                        if cancel.is_set():
                            raise Cancelled
                        sample.append(src.render(i, dpi, gray)[0])
                        prog(0.02 + 0.10 * (j + 1) / len(idx))
                    margin = 0.93
                    for attempt in range(1, MAX_ATTEMPTS + 1):
                        sample_budget = (budget * margin - overhead) * len(idx) / n
                        res = _search(
                            pool,
                            sample,
                            sample_budget,
                            gray,
                            tiers,
                            mk_bump(0.12, 0.10),
                        )
                        jpegs, px, sizes = stream_encode(
                            src,
                            pool,
                            dpi * res["s"],
                            res["q"],
                            res["gray"],
                            cancel,
                            lambda f: prog(0.22 + 0.76 * f),
                            mp,
                        )
                        actual = estimated_pdf_size(jpegs)
                        ok = actual <= budget
                        if ok or not res["fits"] or attempt == MAX_ATTEMPTS:
                            break
                        margin *= budget / actual * 0.97  # 實際比預測大多少, 就多壓多少
                        log(
                            "  "
                            + t(
                                "log.retry",
                                size=fmt_size(actual),
                                i=attempt + 1,
                                max=MAX_ATTEMPTS,
                            )
                        )
                    del sample
                final_gray = res["gray"]
                eff_dpi = dpi * res["s"]
                note = (t("log.gray_note") if final_gray and not gray else "") + (
                    "" if ok else t("log.limit_note")
                )
                log("  " + t("log.dpi_q", dpi=f"{eff_dpi:.0f}", q=res["q"]) + note)
                if target_first and (
                    eff_dpi < MIN_DPI or res["q"] < 35 or (final_gray and not gray)
                ):
                    log("  " + t("log.low_quality"))
            if cancel.is_set():
                raise Cancelled
            write_pdf(dst, jpegs, px, sizes, final_gray)
    finally:
        mp.close()
        src.close()
    progress(1.0)
    return os.path.getsize(dst) / 1024


def compress_pdf(src, dst, pages=None, **kw):
    return convert([(src, pages)], dst, **kw)


def images_to_pdf(paths, dst, **kw):
    return convert([(p, None) for p in paths], dst, **kw)


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def open_folder(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def is_admin():
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def fmt_size(n_bytes):
    return (
        f"{n_bytes / 1048576:.2f} MB"
        if n_bytes >= 1048576
        else f"{n_bytes / 1024:.0f} KB"
    )


# ----------------------------- 系統資源 -----------------------------
def system_memory():
    """回傳 (實體記憶體總量, 目前可用量), 單位 bytes; 偵測不到回傳 (None, None)。"""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            ms = MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(ms)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return int(ms.ullTotalPhys), int(ms.ullAvailPhys)
        if sys.platform == "darwin":
            total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
            vm = subprocess.check_output(["vm_stat"], text=True)
            page = int(re.search(r"page size of (\d+)", vm).group(1))
            pages = sum(
                int(n)
                for _, n in re.findall(
                    r"Pages (free|inactive|speculative):\s+(\d+)", vm
                )
            )
            return total, pages * page
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
        return info["MemTotal"], info.get("MemAvailable", info.get("MemFree"))
    except Exception:
        return None, None


def plan_workers(mode, cores=None, avail=None):
    """依效能模式、CPU 核心數與『目前可用記憶體』決定平行處理程序數 (1 = 不使用多程序)。
    eco: 單程序。balanced: 最多一半核心 (上限 4), 只用可用記憶體的 25%。
    fast: 保留 1 核心給介面 (上限 16), 最多用可用記憶體的 60%。"""
    cores = cores or os.cpu_count() or 1
    if mode not in ("balanced", "fast") or cores < 2:
        return 1
    if avail is None:
        avail = system_memory()[1]
    frac, cap, by_cores = (
        (0.25, 4, max(1, cores // 2))
        if mode == "balanced"
        else (0.6, 16, max(1, cores - 1))
    )
    by_mem = int((avail * frac) // WORKER_MEM) if avail else 2
    return max(1, min(by_cores, by_mem, cap))


def fmt_gb(n_bytes):
    return "?" if n_bytes is None else f"{n_bytes / 2 ** 30:.1f} GB"


# ----------------------------- GUI -----------------------------
if sys.platform.startswith("win"):
    UI_FONT = "Microsoft JhengHei UI"
elif sys.platform == "darwin":
    UI_FONT = "PingFang TC"
else:
    UI_FONT = None


def F(size=13, weight="normal"):
    fam = I18N_.font() or UI_FONT  # 語言檔可用 _meta.font 指定專屬字型
    kw = {"family": fam} if fam else {}
    return ctk.CTkFont(size=size, weight=weight, **kw)


def theme_labels():
    return {k: t(f"theme.{k}") for k in ("light", "dark", "system")}


class App(ctk.CTk if ctk else object):
    def __init__(self):
        self.cfg = load_settings()
        I18N_.set(self.cfg["language"])
        ctk.set_appearance_mode(self.cfg["theme"])
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.geometry("1120x780")
        self.minsize(980, 680)

        self.files = []
        self.ranges = {}  # 路徑 -> 使用者輸入的頁碼範圍文字
        self.page_counts = {}  # 路徑 -> 頁數 (None = 讀不到)
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.running = False
        self.last_out = ""
        self.dnd_active = False
        self.dnd_error = ""
        self._dnd_ready = self._load_dnd()  # 先載入 tkdnd, 再建元件
        self.header = self.left = self.right = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.main = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.main.grid(row=0, column=0, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_columnconfigure(1, weight=0)
        self.main.grid_rowconfigure(1, weight=1)
        self._build_ui()
        for fn, err in I18N_.errors:
            self.log(t("lang.load_failed", file=fn, err=err))
        if getattr(sys, "frozen", False) and I18N_.skipped:
            self.log(t("lang.skipped_bundled", files=", ".join(I18N_.skipped)))
        if not self.dnd_active:  # 拖曳不能用時, 直接在記錄區說明原因
            self.log(t("dnd.unavailable", err=self.dnd_error or DND_ERR or "?"))
        elif is_admin():
            self.log(t("dnd.admin"))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._poll)
        if FIRST_RUN_REFRESH:
            self.after(350, self._post_start_refresh)

    def _build_ui(self):
        """建立 (或在切換語言時重建) 整個介面。狀態都存在 self.cfg / self.files / self.ranges。"""
        for w in (self.header, self.left, self.right):
            if w is not None:
                w.destroy()
        self.title(t("app.title"))
        self._build_header()
        self._build_left()
        self._build_right()
        self.dnd_active = self._setup_dnd()
        self._refresh_list()
        self._apply_mode()
        self._apply_output_mode()
        self._apply_perf()

    # ---------- 拖曳 ----------
    def _load_dnd(self):
        """載入 tkdnd (只做一次, 且必須在建立元件之前)。"""
        if NO_DND:
            self.dnd_error = "disabled by --no-dnd"
            return False
        if not DND_OK:
            self.dnd_error = DND_ERR
            return False
        try:
            require = getattr(TkinterDnD, "require", None) or TkinterDnD._require
            require(self)  # 根視窗本身不能註冊拖放, 之後改註冊在容器與其所有子元件上
            return True
        except Exception as e:
            self.dnd_error = str(e) or type(e).__name__
            return False

    def _setup_dnd(self):
        if not self._dnd_ready:
            return False
        try:
            self._register_dnd_tree(self.main)
            return True
        except Exception as e:
            self.dnd_error = str(e) or type(e).__name__
            return False  # 拖曳失敗不影響其他功能

    def _register_dnd_tree(self, widget):
        """把 widget 與它底下每一個子元件都註冊成拖放目標。
        CustomTkinter 的按鈕/標籤/清單列內部都還有子元件 (canvas), 滑鼠實際停在那上面;
        在 Windows 上若只註冊外層框架, 游標會一直顯示禁止符號。"""
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass  # 少數元件不支援就略過
        for child in widget.winfo_children():
            self._register_dnd_tree(child)

    def _on_drop(self, event):
        if not self.running:
            paths = []
            for p in self.tk.splitlist(event.data):
                if os.path.isdir(p):  # 拖資料夾 = 加入裡面所有支援的檔案
                    for root, _, names in os.walk(p):
                        paths += [os.path.join(root, n) for n in sorted(names)]
                else:
                    paths.append(p)
            self.add_paths(paths)
        return getattr(event, "action", None) or "copy"  # <<Drop>> 事件要回傳動作

    # ---------- 版面 ----------
    def _lang_labels(self):
        """代碼 -> 選單顯示文字; 名稱重複時附上代碼以便分辨。"""
        names = {c: i["name"] for c, i in I18N_.langs.items()}
        vals = list(names.values())
        return {c: (f"{n} ({c})" if vals.count(n) > 1 else n) for c, n in names.items()}

    def _build_header(self):
        h = self.header = ctk.CTkFrame(self.main, fg_color="transparent")
        h.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(18, 4))
        h.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(h, text=t("app.title"), font=F(24, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkLabel(
            h, text=t("app.subtitle"), font=F(12), text_color=("gray40", "gray65")
        ).grid(row=1, column=0, sticky="w")
        labels = self._lang_labels()
        self._lang_by_label = {v: k for k, v in labels.items()}
        self.lang_menu = ctk.CTkOptionMenu(
            h,
            values=list(labels.values()),
            command=self._on_language,
            font=F(12),
            dropdown_font=F(12),
            width=150,
            state="normal" if len(labels) > 1 else "disabled",
        )
        self.lang_menu.set(labels[I18N_.code])
        self.lang_menu.grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 10))
        self.theme_seg = ctk.CTkSegmentedButton(
            h, values=list(theme_labels().values()), command=self._on_theme, font=F(12)
        )
        self.theme_seg.set(theme_labels()[self.cfg["theme"]])
        self.theme_seg.grid(row=0, column=2, rowspan=2, sticky="e")

    def _build_left(self):
        left = self.left = ctk.CTkFrame(self.main, fg_color="transparent")
        left.grid(row=1, column=0, sticky="nsew", padx=(24, 10), pady=(8, 20))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=3)
        left.grid_rowconfigure(1, weight=2)

        fc = ctk.CTkFrame(left, corner_radius=14)
        fc.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        fc.grid_columnconfigure(0, weight=1)
        fc.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(fc, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        top.grid_columnconfigure(0, weight=1)
        self.count_label = ctk.CTkLabel(top, text=t("files.title"), font=F(15, "bold"))
        self.count_label.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            top, text=t("files.add"), width=120, font=F(13), command=self.add_files
        ).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(
            top,
            text=t("files.clear"),
            width=64,
            font=F(13),
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray85"),
            command=self.clear_files,
        ).grid(row=0, column=2)
        self.list_frame = ctk.CTkScrollableFrame(fc, fg_color="transparent")
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.list_frame.grid_columnconfigure(0, weight=1)

        pc = ctk.CTkFrame(left, corner_radius=14)
        pc.grid(row=1, column=0, sticky="nsew")
        pc.grid_columnconfigure(0, weight=1)
        pc.grid_rowconfigure(2, weight=1)
        ph = ctk.CTkFrame(pc, fg_color="transparent")
        ph.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        ph.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(ph, text=t("progress.title"), font=F(15, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.pct_label = ctk.CTkLabel(ph, text="0%", font=F(13))
        self.pct_label.grid(row=0, column=1, sticky="e")
        self.progress = ctk.CTkProgressBar(pc, height=10)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.log_box = ctk.CTkTextbox(pc, font=F(12), wrap="word", state="disabled")
        self.log_box.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _build_right(self):
        rc = self.right = ctk.CTkFrame(self.main, corner_radius=14, width=370)
        rc.grid(row=1, column=1, sticky="ns", padx=(10, 24), pady=(8, 20))
        rc.grid_propagate(False)
        rc.grid_columnconfigure(0, weight=1)
        rc.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(rc, text=t("settings.title"), font=F(15, "bold")).grid(
            row=0, column=0, sticky="w", padx=18, pady=(14, 2)
        )

        sf = ctk.CTkScrollableFrame(rc, fg_color="transparent")
        sf.grid(row=1, column=0, sticky="nsew", padx=6)
        sf.grid_columnconfigure(0, weight=1)
        P = dict(padx=12)

        self._label(sf, 0, t("out.folder"))
        of = ctk.CTkFrame(sf, fg_color="transparent")
        of.grid(row=1, column=0, sticky="ew", pady=(0, 10), **P)
        of.grid_columnconfigure(0, weight=1)
        self.out_var = ctk.StringVar(value=self.cfg["output_dir"])
        ctk.CTkEntry(of, textvariable=self.out_var, font=F(12)).grid(
            row=0, column=0, sticky="ew"
        )
        ctk.CTkButton(
            of, text=t("out.browse"), width=56, font=F(12), command=self.browse_output
        ).grid(row=0, column=1, padx=(6, 0))

        self._label(sf, 2, t("omode.label"))
        self._omode_rev = {t(f"omode.{k}"): k for k in ("each", "merge", "split")}
        self.omode_seg = ctk.CTkSegmentedButton(
            sf,
            values=list(self._omode_rev),
            font=F(12),
            command=lambda _=None: self._apply_output_mode(),
        )
        self.omode_seg.set(t(f"omode.{self.cfg['output_mode']}"))
        self.omode_seg.grid(row=3, column=0, sticky="ew", pady=(0, 4), **P)
        self.hint = ctk.CTkLabel(
            sf,
            text="",
            font=F(11),
            justify="left",
            wraplength=300,
            text_color=("gray40", "gray65"),
            anchor="w",
        )
        self.hint.grid(row=4, column=0, sticky="w", pady=(0, 4), **P)

        self.merge_frame = ctk.CTkFrame(sf, fg_color="transparent")
        self.merge_frame.grid(row=5, column=0, sticky="ew", pady=(0, 8), **P)
        ctk.CTkLabel(self.merge_frame, text=t("merge.name"), font=F(12)).grid(
            row=0, column=0
        )
        self.merge_name_var = ctk.StringVar(value=self.cfg["merge_name"])
        ctk.CTkEntry(
            self.merge_frame, textvariable=self.merge_name_var, width=150, font=F(12)
        ).grid(row=0, column=1, padx=6)
        ctk.CTkLabel(self.merge_frame, text=".pdf", font=F(12)).grid(row=0, column=2)
        self.split_frame = ctk.CTkFrame(sf, fg_color="transparent")
        self.split_frame.grid(row=5, column=0, sticky="ew", pady=(0, 8), **P)
        ctk.CTkLabel(self.split_frame, text=t("split.every"), font=F(12)).grid(
            row=0, column=0
        )
        self.split_var = ctk.StringVar(value=str(self.cfg["split_n"]))
        ctk.CTkEntry(
            self.split_frame, textvariable=self.split_var, width=60, font=F(12)
        ).grid(row=0, column=1, padx=6)
        ctk.CTkLabel(self.split_frame, text=t("split.pages"), font=F(12)).grid(
            row=0, column=2
        )

        self._label(sf, 6, t("cmode.label"))
        self.mode_seg = ctk.CTkSegmentedButton(
            sf,
            values=[t("cmode.auto"), t("cmode.manual")],
            font=F(12),
            command=lambda _=None: self._apply_mode(),
        )
        self.mode_seg.set(t("cmode.auto") if self.cfg["auto"] else t("cmode.manual"))
        self.mode_seg.grid(row=7, column=0, sticky="ew", pady=(0, 10), **P)

        self._label(sf, 8, t("target.label"))
        tf = ctk.CTkFrame(sf, fg_color="transparent")
        tf.grid(row=9, column=0, sticky="ew", pady=(0, 10), **P)
        self.target_var = ctk.StringVar(value=f"{self.cfg['target_mb']:g}")
        self.target_entry = ctk.CTkEntry(
            tf, textvariable=self.target_var, width=70, font=F(13)
        )
        self.target_entry.grid(row=0, column=0)
        self.preset_btns = []
        for i, mb in enumerate(("1", "2", "4", "10")):
            b = ctk.CTkButton(
                tf,
                text=mb,
                width=38,
                height=28,
                font=F(12),
                fg_color=("gray80", "gray28"),
                text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray35"),
                command=lambda v=mb: self.target_var.set(v),
            )
            b.grid(row=0, column=i + 1, padx=(6, 0))
            self.preset_btns.append(b)

        self.dpi_var = ctk.IntVar(value=self.cfg["dpi"])
        self._slider(sf, 13, t("dpi.label"), self.dpi_var, 72, 300)
        self.q_var = ctk.IntVar(value=self.cfg["quality"])
        self.q_slider = self._slider(sf, 15, t("quality.label"), self.q_var, 30, 95)

        self.gray_var = ctk.BooleanVar(value=self.cfg["gray"])
        ctk.CTkSwitch(
            sf, text=t("gray.switch"), variable=self.gray_var, font=F(13)
        ).grid(row=17, column=0, sticky="w", pady=(6, 6), **P)
        self.tfirst_var = ctk.BooleanVar(value=self.cfg["target_first"])
        self.tfirst_switch = ctk.CTkSwitch(
            sf, text=t("tfirst.switch"), variable=self.tfirst_var, font=F(13)
        )
        self.tfirst_switch.grid(row=18, column=0, sticky="w", pady=(4, 0), **P)
        ctk.CTkLabel(
            sf,
            text=t("tfirst.hint"),
            font=F(11),
            justify="left",
            wraplength=300,
            text_color=("gray40", "gray65"),
            anchor="w",
        ).grid(row=19, column=0, sticky="w", pady=(0, 10), **P)

        self._label(sf, 10, t("perf.label"))
        self._perf_rev = {t(f"perf.{k}"): k for k in PERF_MODES}
        self.perf_seg = ctk.CTkSegmentedButton(
            sf,
            values=list(self._perf_rev),
            font=F(12),
            command=lambda _=None: self._apply_perf(),
        )
        self.perf_seg.set(t(f"perf.{self.cfg['perf_mode']}"))
        self.perf_seg.grid(row=11, column=0, sticky="ew", pady=(0, 4), **P)
        self.perf_hint = ctk.CTkLabel(
            sf,
            text="",
            font=F(11),
            justify="left",
            wraplength=300,
            text_color=("gray40", "gray65"),
            anchor="w",
        )
        self.perf_hint.grid(row=12, column=0, sticky="w", pady=(0, 12), **P)

        bf = ctk.CTkFrame(rc, fg_color="transparent")
        bf.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 16))
        bf.grid_columnconfigure((0, 1), weight=1)
        self.start_btn = ctk.CTkButton(
            bf,
            text=t("btn.start"),
            height=42,
            font=F(15, "bold"),
            command=self.start,
            state="disabled" if self.running else "normal",
        )
        self.start_btn.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.cancel_btn = ctk.CTkButton(
            bf,
            text=t("btn.cancel"),
            height=34,
            font=F(13),
            state="normal" if self.running else "disabled",
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray85"),
            command=self.cancel.set,
        )
        self.cancel_btn.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            bf,
            text=t("btn.open_out"),
            height=34,
            font=F(13),
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray85"),
            command=self.open_output,
        ).grid(row=1, column=1, sticky="ew", padx=(4, 0))

    def _label(self, parent, row, text):
        ctk.CTkLabel(
            parent, text=text, font=F(12), text_color=("gray35", "gray70")
        ).grid(row=row, column=0, sticky="w", padx=12, pady=(2, 3))

    def _slider(self, parent, row, text, var, lo, hi):
        self._label(parent, row, text)
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=row + 1, column=0, sticky="ew", padx=12, pady=(0, 8))
        f.grid_columnconfigure(0, weight=1)
        lab = ctk.CTkLabel(f, text=str(var.get()), width=36, font=F(13))

        def on(v):
            var.set(int(round(float(v))))
            lab.configure(text=str(var.get()))

        s = ctk.CTkSlider(f, from_=lo, to=hi, number_of_steps=hi - lo, command=on)
        s.set(var.get())
        s.grid(row=0, column=0, sticky="ew")
        lab.grid(row=0, column=1, padx=(8, 0))
        return s

    # ---------- 狀態 ----------
    def _output_mode(self):
        return self._omode_rev.get(self.omode_seg.get(), "each")

    def _is_auto(self):
        return self.mode_seg.get() == t("cmode.auto")

    def _perf_mode(self):
        return self._perf_rev.get(self.perf_seg.get(), "balanced")

    def _apply_perf(self):
        mode = self._perf_mode()
        w = plan_workers(mode)
        total, avail = system_memory()
        info = dict(cores=os.cpu_count() or 1, total=fmt_gb(total), avail=fmt_gb(avail))
        if w > 1:
            self.perf_hint.configure(
                text=t("perf.hint", w=w, mem=fmt_gb(w * WORKER_MEM), **info)
            )
        else:
            self.perf_hint.configure(text=t("perf.hint_single", **info))

    def _apply_output_mode(self):
        m = self._output_mode()
        self.hint.configure(text=t(f"omode.hint.{m}"))
        self.merge_frame.grid() if m == "merge" else self.merge_frame.grid_remove()
        self.split_frame.grid() if m == "split" else self.split_frame.grid_remove()

    def _apply_mode(self):
        auto = self._is_auto()
        self.target_entry.configure(state="normal" if auto else "disabled")
        for b in self.preset_btns:
            b.configure(state="normal" if auto else "disabled")
        self.q_slider.configure(state="disabled" if auto else "normal")
        self.tfirst_switch.configure(state="normal" if auto else "disabled")

    def _on_theme(self, label):
        key = next((k for k, v in theme_labels().items() if v == label), "system")
        self.cfg["theme"] = key
        ctk.set_appearance_mode(key)

    def _on_language(self, label):
        code = self._lang_by_label.get(label)
        if not code or code == I18N_.code:
            return
        if self.running:  # 處理中重建介面會弄丟進度元件, 先擋下
            self.lang_menu.set(self._lang_labels()[I18N_.code])
            messagebox.showinfo(t("msg.error"), t("msg.lang_busy"))
            return
        self._collect_cfg()
        self.cfg["language"] = I18N_.set(code)
        save_settings(self.cfg)
        self._rebuild_preserving()

    def _rebuild_preserving(self):
        """重建整個介面並保留: 設定值、檔案清單、頁碼範圍、記錄區文字與進度。"""
        self._collect_cfg()
        log_text = self.log_box.get("1.0", "end-1c")
        prog, pct = self.progress.get(), self.pct_label.cget("text")
        self._build_ui()
        self.log_box.configure(state="normal")
        self.log_box.insert("end", log_text)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.progress.set(prog)
        self.pct_label.configure(text=pct)

    def _post_start_refresh(self):
        if not self.running:
            try:
                self._rebuild_preserving()
            except Exception:
                pass  # 重繪失敗不影響使用

    def _collect_cfg(self):
        try:
            mb = float(self.target_var.get())
            if mb <= 0:
                raise ValueError
        except ValueError:
            mb = None
        try:
            split_n = max(1, int(self.split_var.get()))
        except ValueError:
            split_n = self.cfg["split_n"]
        name = self.merge_name_var.get().strip() or "merged"
        self.cfg.update(
            output_dir=self.out_var.get().strip(),
            dpi=self.dpi_var.get(),
            quality=self.q_var.get(),
            auto=self._is_auto(),
            gray=self.gray_var.get(),
            target_first=self.tfirst_var.get(),
            perf_mode=self._perf_mode(),
            output_mode=self._output_mode(),
            split_n=split_n,
            merge_name=name,
        )
        if mb:
            self.cfg["target_mb"] = mb
        return mb

    def _on_close(self):
        self._collect_cfg()
        save_settings(self.cfg)
        self.cancel.set()
        self.destroy()

    # ---------- 檔案 ----------
    def add_files(self):
        pats = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTS))
        paths = filedialog.askopenfilenames(
            title=t("dlg.pick"),
            filetypes=[
                (t("dlg.ft_supported"), pats),
                (t("dlg.ft_pdf"), "*.pdf"),
                (t("dlg.ft_all"), "*.*"),
            ],
        )
        self.add_paths(paths)

    def add_paths(self, paths):
        skipped = 0
        for p in paths:
            if os.path.splitext(p)[1].lower() not in SUPPORTED_EXTS:
                skipped += 1
            elif p not in self.files:
                self.files.append(p)
                if is_pdf(p):
                    self.page_counts[p] = pdf_page_count(p)
        if skipped:
            self.log(
                t("log.skipped", n=skipped) + ("" if HEIF_OK else t("log.skipped_heif"))
            )
        self._refresh_list()

    def clear_files(self):
        if not self.running:
            self.files.clear()
            self.ranges.clear()
            self.page_counts.clear()
            self._refresh_list()

    def remove_file(self, path):
        if not self.running and path in self.files:
            self.files.remove(path)
            self.ranges.pop(path, None)
            self.page_counts.pop(path, None)
            self._refresh_list()

    def move_file(self, path, delta):
        if self.running or path not in self.files:
            return
        i = self.files.index(path)
        j = i + delta
        if 0 <= j < len(self.files):
            self.files[i], self.files[j] = self.files[j], self.files[i]
            self._refresh_list()

    def _refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        total = 0
        if not self.files:
            ctk.CTkLabel(
                self.list_frame,
                text=t("files.empty_dnd" if self.dnd_active else "files.empty"),
                font=F(13),
                text_color=("gray45", "gray60"),
            ).grid(pady=60)
        flat = dict(
            fg_color="transparent",
            text_color=("gray30", "gray70"),
            hover_color=("gray78", "gray30"),
            font=F(12),
            width=26,
            height=26,
        )
        for i, p in enumerate(self.files):
            try:
                size = os.path.getsize(p)
            except OSError:
                size = 0
            total += size
            row = ctk.CTkFrame(
                self.list_frame, corner_radius=10, fg_color=("gray90", "gray20")
            )
            row.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            row.grid_columnconfigure(1, weight=1)
            pdf_flag = is_pdf(p)
            ctk.CTkLabel(
                row,
                text=t("files.badge_pdf" if pdf_flag else "files.badge_image"),
                width=46,
                font=F(11, "bold"),
                corner_radius=6,
                text_color="white",
                fg_color=("#3b82f6", "#2563eb") if pdf_flag else ("#10b981", "#059669"),
            ).grid(row=0, column=0, padx=(10, 8), pady=8)
            ctk.CTkLabel(row, text=os.path.basename(p), anchor="w", font=F(13)).grid(
                row=0, column=1, sticky="ew"
            )
            if pdf_flag:
                n = self.page_counts.get(p)
                ctk.CTkLabel(
                    row,
                    text=t("files.pages", n=n) if n else t("files.pages_unknown"),
                    font=F(12),
                    width=44,
                    text_color=("gray40", "gray65"),
                ).grid(row=0, column=2, padx=(6, 2))
                ent = ctk.CTkEntry(
                    row,
                    width=92,
                    height=26,
                    font=F(12),
                    placeholder_text=t("files.range_placeholder"),
                )
                if self.ranges.get(p):
                    ent.insert(0, self.ranges[p])
                ent.bind(
                    "<KeyRelease>",
                    lambda e, p=p, w=ent: self.ranges.__setitem__(p, w.get()),
                )
                ent.grid(row=0, column=3, padx=4)
            ctk.CTkLabel(
                row,
                text=fmt_size(size),
                font=F(12),
                width=64,
                text_color=("gray40", "gray65"),
            ).grid(row=0, column=4, padx=4)
            ctk.CTkButton(
                row, text="↑", command=lambda p=p: self.move_file(p, -1), **flat
            ).grid(row=0, column=5)
            ctk.CTkButton(
                row, text="↓", command=lambda p=p: self.move_file(p, 1), **flat
            ).grid(row=0, column=6)
            ctk.CTkButton(
                row, text="✕", command=lambda p=p: self.remove_file(p), **flat
            ).grid(row=0, column=7, padx=(0, 6))
        n = len(self.files)
        self.count_label.configure(
            text=(
                t("files.title")
                if not n
                else t("files.summary", n=n, size=fmt_size(total))
            )
        )
        if self.dnd_active:
            self._register_dnd_tree(self.list_frame)

    def browse_output(self):
        d = filedialog.askdirectory()
        if d:
            self.out_var.set(d)

    def open_output(self):
        folder = (
            self.out_var.get().strip()
            or self.last_out
            or (os.path.dirname(self.files[0]) if self.files else "")
        )
        if folder and os.path.isdir(folder):
            open_folder(folder)

    # ---------- log / 進度 ----------
    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log(val)
                elif kind == "progress":
                    self.progress.set(val)
                    self.pct_label.configure(text=f"{val * 100:.0f}%")
                elif kind == "done":
                    self._finish(val)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _finish(self, summary):
        self.running = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.log("\n" + summary)
        messagebox.showinfo(t("msg.done"), summary)

    # ---------- 規劃工作 ----------
    def _selected_pages(self, p):
        txt = self.ranges.get(p, "").strip()
        if not txt:
            return None
        name = os.path.basename(p)
        n = self.page_counts.get(p)
        if not n:
            raise ValueError(
                t("err.with_file", name=name, msg=t("err.no_pagecount_range"))
            )
        try:
            return parse_page_ranges(txt, n)
        except ValueError as e:
            raise ValueError(t("err.with_file", name=name, msg=str(e))) from None

    def plan_jobs(self):
        """回傳 job 清單; 每個 job = 一個輸出 PDF。頁碼有誤會丟出 ValueError。"""
        mode = self.cfg["output_mode"]
        files = list(self.files)
        sel = {p: self._selected_pages(p) for p in files if is_pdf(p)}

        def each(p):
            name = os.path.splitext(os.path.basename(p))[0]
            out = f"{name}_compressed.pdf" if is_pdf(p) else f"{name}.pdf"
            return dict(
                items=[(p, sel.get(p))],
                name=out,
                src=p,
                label=os.path.basename(p),
                compare=is_pdf(p) and sel.get(p) is None,
            )

        if mode == "merge":
            items = [(p, sel.get(p)) for p in files]
            return [
                dict(
                    items=items,
                    name=f"{self.cfg['merge_name']}.pdf",
                    src=files[0],
                    label=t("job.merge", n=len(files)),
                    compare=False,
                )
            ]

        jobs = []
        for p in files:
            if mode == "split" and is_pdf(p):
                base = os.path.basename(p)
                n = self.page_counts.get(p)
                if not n:
                    raise ValueError(
                        t("err.with_file", name=base, msg=t("err.no_pagecount_split"))
                    )
                idx = sel[p] if sel[p] is not None else list(range(n))
                size = self.cfg["split_n"]
                stem = os.path.splitext(base)[0]
                chunks = [idx[k : k + size] for k in range(0, len(idx), size)]
                for j, ch in enumerate(chunks, 1):
                    contiguous = ch == list(range(ch[0], ch[0] + len(ch)))
                    if contiguous:
                        tag = (
                            f"p{ch[0] + 1}"
                            if len(ch) == 1
                            else f"p{ch[0] + 1}-{ch[-1] + 1}"
                        )
                    else:
                        tag = f"part{j:02d}"
                    jobs.append(
                        dict(
                            items=[(p, ch)],
                            name=f"{stem}_{tag}.pdf",
                            src=p,
                            label=t(
                                "job.split_part", name=base, j=j, total=len(chunks)
                            ),
                            compare=False,
                        )
                    )
            else:
                jobs.append(each(p))
        return jobs

    def start(self):
        if self.running:
            return
        if not self.files:
            messagebox.showerror(t("msg.error"), t("msg.no_files"))
            return
        mb = self._collect_cfg()
        if self.cfg["auto"] and mb is None:
            messagebox.showerror(t("msg.error"), t("msg.bad_target"))
            return
        try:
            jobs = self.plan_jobs()
        except ValueError as e:
            messagebox.showerror(t("msg.bad_range"), str(e))
            return
        save_settings(self.cfg)
        opts = dict(
            dpi=self.cfg["dpi"],
            quality=self.cfg["quality"],
            target_kb=mb * 1024 if self.cfg["auto"] else None,
            gray=self.cfg["gray"],
            target_first=self.cfg["target_first"],
            workers=plan_workers(self.cfg["perf_mode"]),
        )
        self.running = True
        self.cancel.clear()
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress.set(0)
        self.pct_label.configure(text="0%")
        threading.Thread(
            target=self._run, args=(jobs, self.cfg["output_dir"], opts), daemon=True
        ).start()

    def _run(self, jobs, out_dir, opts):
        say = lambda m: self.q.put(("log", m))
        total, ok = len(jobs), 0
        used = set()
        for idx, job in enumerate(jobs):
            if self.cancel.is_set():
                break
            folder = out_dir or os.path.dirname(job["src"])
            say(t("run.item", i=idx + 1, total=total, label=job["label"]))
            dst = ""
            try:
                os.makedirs(folder, exist_ok=True)
                dst = unique_path(os.path.join(folder, job["name"]))
                while dst in used:  # 同一次工作內也不互相覆蓋
                    dst = unique_path(dst[:-4] + " (1).pdf")
                used.add(dst)
                prog = lambda f, i=idx: self.q.put(("progress", (i + f) / total))
                if (
                    job["compare"]
                    and opts["target_kb"] is not None
                    and os.path.getsize(job["src"]) <= opts["target_kb"] * 1024
                ):
                    # 原檔本來就已經達標: 不要為了「壓縮」反而把畫質弄差 (轉成圖片後檔案甚至可能變大)
                    shutil.copy2(job["src"], dst)
                    say(
                        t(
                            "run.already_small",
                            size=fmt_size(os.path.getsize(job["src"])),
                        )
                    )
                    self.q.put(("progress", (idx + 1) / total))
                    self.last_out = folder
                    ok += 1
                    continue
                size_kb = convert(
                    job["items"],
                    dst,
                    cancel=self.cancel,
                    log=say,
                    progress=prog,
                    **opts,
                )
                if job["compare"]:
                    before = os.path.getsize(job["src"]) / 1024
                    say(
                        t(
                            "run.done_compare",
                            before=f"{before:.0f}",
                            after=f"{size_kb:.0f}",
                            pct=f"{size_kb / before * 100:.0f}",
                        )
                    )
                    if size_kb >= before:
                        say(t("run.warn_bigger"))
                else:
                    say(
                        t(
                            "run.done_out",
                            size=fmt_size(size_kb * 1024),
                            file=os.path.basename(dst),
                        )
                    )
                self.last_out = folder
                ok += 1
            except Cancelled:
                say(t("run.cancelled"))
                if dst and os.path.exists(dst + ".part"):
                    os.remove(dst + ".part")
                break
            except Exception as e:  # 單一工作失敗 (加密、損毀…) 不影響其他
                say(t("run.failed", err=e))
        self.q.put(("progress", 1.0 if not self.cancel.is_set() else 0))
        self.q.put(
            (
                "done",
                t("run.summary", ok=ok, total=total)
                + (t("run.summary_cancelled") if self.cancel.is_set() else ""),
            )
        )


def _cli_compress():
    """python autopdf.py --compress 輸入.pdf 輸出.pdf [--target-mb N] [--workers N]"""
    a = sys.argv
    i = a.index("--compress")
    src, dst = a[i + 1], a[i + 2]

    def opt(name, default):
        return a[a.index(name) + 1] if name in a else default

    mb = float(opt("--target-mb", 0))
    kb = compress_pdf(
        src, dst, target_kb=mb * 1024 if mb else None, workers=int(opt("--workers", 1))
    )
    print(f"{dst}: {kb / 1024:.2f} MB")


def main():
    if "--compress" in sys.argv:
        _cli_compress()
        return
    if "--list-lang" in sys.argv:  # 診斷: 目前實際載入了哪些語言
        for code, info in I18N_.langs.items():
            src = "bundled" if info.get("bundled") else (info["path"] or "built-in")
            print(f"{code}\t{info['name']}\t{len(info['strings'])} strings\t{src}")
        for fn in I18N_.skipped:
            print(f"skipped (same code as bundled): {fn}")
        for fn, err in I18N_.errors:
            print(f"error: {fn}: {err}")
        return
    if "--export-lang" in sys.argv:  # 給翻譯者: python autopdf.py --export-lang
        print(export_lang_template())
        return
    if ctk is None:
        sys.exit(t("cli.no_ctk"))
    App().mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # 打包成 exe 後, 工作程序啟動時需要這行
    main()
