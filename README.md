# PDF 壓縮工具（改良版）

改自 [eason9709/AutoPDF-compress](https://github.com/eason9709/AutoPDF-compress)（原專案 README 聲明為 MIT 授權）。

## 功能

- **壓縮**：設定目標大小（MB），程式自動逼近；也可手動指定 DPI 與 JPEG 品質
- **合併**：清單內的 PDF 與圖片依序接成一個 PDF，可用 ↑ ↓ 調整順序
- **拆分**：每個 PDF 依「每 N 頁」切成多個檔案（N=1 即每頁一檔）
- **頁碼範圍**：每個 PDF 可單獨指定頁碼，例如 `1-3,5,8-`
- **圖片轉 PDF**：PNG / JPG / WEBP / BMP / TIFF，安裝 `pillow-heif` 後支援 HEIC / HEIF
- **多語言**：讀取 `lang/` 資料夾內的 JSON，有幾個檔案就有幾種語言可選（見下方）
- **拖曳**檔案或資料夾進視窗即可加入
- **不需要安裝 Poppler**（改用 pypdfium2）
- 記住上次的輸出資料夾與所有設定
- 淺色 / 深色 / 跟隨系統 外觀
- 有進度條、可取消；單一檔案失敗（例如有密碼）不影響其他檔案

## 安裝與執行

```bash
pip install -r requirements.txt
python autopdf.py
```

Linux 需另外安裝 tkinter：`sudo apt install python3-tk`

## 多語言

程式啟動時會掃描程式所在資料夾旁的 `lang/`，**每個 `.json` 檔就是一種語言**，右上角下拉選單的選項數量就是 JSON 檔的數量。切換語言即時生效，不需重開。第一次啟動會依系統語言自動挑選，之後沿用你的選擇。

```
autopdf.py
lang/
  zh_TW.json   ← 檔名 = 語言代碼
  zh_CN.json
  en.json
  ja.json
  _template.json   ← 底線開頭的檔案會被忽略
```

### 新增一種語言

1. 執行 `python autopdf.py --export-lang`，會產生 `lang/_template.json`（含所有可翻譯的文字）。
2. 複製一份，改檔名為語言代碼，例如 `ko.json`。
3. 修改 `_meta.name`（選單顯示的名稱）與 `strings` 裡的文字，存成 UTF-8。
4. 重新開啟程式，選單就會多出該語言。

```json
{
  "_meta": { "name": "한국어", "font": "" },
  "strings": {
    "btn.start": "변환 시작",
    "btn.cancel": "취소"
  }
}
```

- 沒翻譯到的鍵會自動顯示內建的繁體中文，所以可以先翻一部分。
- `{n}`、`{size}` 這類 `{}` 占位符要原樣保留，不可翻譯或刪掉。
- `_meta.font` 選填，可指定該語言專用的字型名稱。
- 標籤太長會被切掉，翻譯請盡量簡短。
- 壞掉的 JSON 會被略過，並在程式的記錄區顯示原因。
- 語言檔也會在程式資料夾以外尋找：依序是 **程式旁 `lang/` → 打包內建 `lang/` → 目前工作目錄 `lang/`**。

## 打包成 exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --collect-all customtkinter --collect-all tkinterdnd2 autopdf.py
```

語言檔有兩種放法，擇一或同時使用：

- **放在 exe 旁邊**：把 `lang` 資料夾複製到 `dist/` 的 exe 旁。之後新增或修改語言不用重新打包。
- **打包進 exe**：加上 `--add-data "lang;lang"`（Windows；macOS / Linux 用 `:` 分隔）。

## 頁碼範圍格式

| 輸入 | 意義 |
|---|---|
| （留空） | 全部頁面 |
| `1-3,5` | 第 1、2、3、5 頁 |
| `8-` | 第 8 頁到最後一頁 |
| `5,1-2` | 依輸入順序：第 5 頁，再第 1、2 頁 |

## 注意

- 輸出是「圖片式 PDF」，原本可選取、搜尋的文字會消失。
- 有密碼保護的 PDF 需先解除密碼。

## 授權

MIT。原專案版權屬原作者，請保留原作者署名。