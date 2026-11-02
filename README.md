# Flight Tracker 2.0 ✈️

使用 GitHub Pages、Supabase 和 GitHub Actions 的航線票價追蹤網站。

- 網站：<https://lydiaz-wu.github.io/flight-tracker/>
- 程式碼：<https://github.com/lydiaz-wu/flight-tracker>

## 目前架構

```text
web/                    # 手機優先的 PWA 前端：頁面、航線表單、登入與推播訂閱
cloud_worker.py         # GitHub Actions 排程入口：讀取監控、寫入報價、通知
worker_v2.py            # 航線組合、票價查詢與驗證
scrapers/               # 航空公司及 Google Flights 資料來源
supabase/               # 雲端資料庫 SQL（如專案已有）
tests/                  # 自動化測試
.github/workflows/      # Pages 部署與定期查價
```

舊的 LINE / Webhook 版本可能仍保留在 `app.py`、`notifiers/` 等模組供參考；**目前網頁流程以 GitHub Pages + Supabase 為主**。未確認依賴前，不要直接刪除舊模組。

## 本機開發

建議 Python 3.11：

```bash
conda create -n flight-tracker python=3.11 -y
conda activate flight-tracker
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m pytest -q
```

若 macOS 安裝 `cryptography` 因 OpenSSL / Rust 編譯失敗，可先在 conda 環境安裝適當的預編譯套件。依賴版本應與實際部署環境核對。

## 雲端設定

前端公開設定在 `web/cloud-config.js`：Supabase 專案 URL、publishable key、VAPID **public** key。公開設定檔**不可**放私鑰。

GitHub Actions Secrets（依當前程式）包含 `SUPABASE_URL`、`SUPABASE_SECRET_KEY`、`VAPID_PRIVATE_KEY`、`VAPID_SUBJECT`。不要提交真實私鑰、`.env` 或 PEM 檔案。

GitHub Actions：

- **Deploy Flight Tracker to GitHub Pages**：網站部署
- **Check flight fares**：定時查票價並寫回 Supabase；成功綠燈表示程序完成，不保證每個來源都成功取得真實可購買報價

詳見 `CLOUD_SETUP.md`（如存在）。

## 資料品質提醒

不同出發日期或不同航空公司的票價不能直接當成同一張機票的歷史漲跌。請確認去回程、幣別、實際營運航空及最終可購買價格，再決定是否購票。

## 歷史文件

早期 LINE Bot 與過渡版本的說明保存在 `docs/archive/`，僅供追溯，不代表目前部署方式。
