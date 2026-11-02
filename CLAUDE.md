# CLAUDE.md

## 專案
PDF 壓縮工具 (改自 eason9709/AutoPDF-compress, MIT)。單一檔案 autopdf.py,
介面用 CustomTkinter, 渲染用 pypdfium2, 圖片處理用 Pillow。

## 結構
- autopdf.py: 主程式 (核心壓縮、GUI、環境檢查、多語言都在裡面)
- build_exe.py: 用 PyInstaller 打包 exe
- lang/*.json: 語言檔 (檔名=語言代碼, zh_CN 要用底線)
- requirements.txt, README.md, LICENSE

## 慣例
- 使用者介面與回覆一律用繁體中文
- 所有介面文字都走 t("key"), 新增字串要同時加進 DEFAULT_STRINGS 和 lang/*.json
- 不要把變數取名叫 t (會蓋掉翻譯函式)
- 核心壓縮: 逐頁串流, 不把整份文件放進記憶體; 多程序用 spawn

## 注意
- 在 Windows 上實測, 拖曳/打包相關問題以使用者回報為準
- 不要 commit build/、dist/、*.spec、exe
