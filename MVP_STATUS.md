# VanceCode MVP 0.1.0 驗收紀錄

狀態：2026-10-17 完成 MVP 功能驗收與三個真實模型修復的人工檢查。GitHub 同步狀態另列。

## 本次收尾範圍

- Python CLI、單一 OpenAI-compatible provider、Agent Loop。
- read_file、search_code、apply_patch、run_tests。
- repo 路徑政策、操作確認、測試唯讀、執行逾時與 bytecode cache 隔離。
- Context Manager 的字元預算、歷史摘要、輸出節錄與行號讀檔。
- 三案例 evaluation、全新 repo、獨立可見測試與 holdout 驗收、JSON 報告與候選 patch。

## 驗收證據

| 項目 | 狀態 | 證據 |
|---|---|---|
| 自動測試 | 59 個測試全部通過，含錯誤遮蔽、節流、重試次數限制與跨案例排程 | `python3 -m unittest discover -s tests -v` |
| 離線評測 | 更新報告後 6/6 通過，可見與 holdout 均為 6/6 | `reports/offline.json`，mode 為 offline-scripted，包含 candidate_patch |
| Gemini 設定 | 使用者已換入有效 Gemini key，模型為 gemini-3.6-flash；key 僅存於被忽略的 .env | shipping_discount 已成功呼叫 API 並完成修復；未更動舊專案 |
| 真實模型三案例 | 三例均已有成功紀錄，分兩次執行，可見與 holdout 均通過 | pricing 見 `reports/live-diagnostic.json`；slug 與 mean 見 `reports/live-new-key.json` |
| 真實模型 patch 人工檢查 | 三例均完成檢查，符合任務規格；只修改實作檔，沒有改測試或寫死答案 | 下表列出實際修復與限制 |
| GitHub 最終同步 | 本機驗收 commit 準備完成，待 push 結果確認 | 比較本機 HEAD 與遠端 main；不能以本機 commit 當成遠端已同步 |

### 真實模型修改檢查

| Case | 回合 / 工具呼叫 | 耗時 | 人工檢查 |
|---|---|---|---|
| shipping_discount | 8 / 7 | 31.3 秒 | 商品小計先折扣取整，再加全額運費，計算順序符合規格 |
| normalize_slug | 9 / 8 | 123.0 秒 | `'-'.join(text.lower().split())` 可處理連續空白、tab 與 Unicode 空白，同時保留標點 |
| mean_precision | 9 / 8 | 136.4 秒 | 先轉 list、檢查空輸入並拋 ValueError，再用 `/` 保留小數；轉 list 會多用 O(n) 記憶體，對此小型任務可接受 |

三個實際 candidate_patch 都已檢查。pricing 與 slug 的修復和 reference patch 相同；mean 的額外 list 轉換使一般 iterable 也可處理，但本次驗收仍只涵蓋既有測試。

成功紀錄來自分開執行與重試後的最終結果，不合併冒充單一 benchmark run 的 3/3 成功率。`reports/live.json` 保留無效 key 時的失敗；`reports/live-remaining.json`、`reports/live-remaining-paced.json`、`reports/live-remaining-final.json` 保留配額失敗。成本與 token 用量尚未量測，不能將報告中的 null 解讀為零。

## 執行真實模型驗收

在本專案目錄的 `.env` 填入 `OPENAI_API_KEY`、`VANCECODE_MODEL`；若使用其他相容服務，再設定 `VANCECODE_BASE_URL`。不要把金鑰放入 README、報告或 Git。

本機 Gemini 設定已完成，不需重新申請 key。Gemini 使用 `https://generativelanguage.googleapis.com/v1beta/openai`；`OPENAI_API_KEY` 在此只是相容介面的設定名稱，內容是 Gemini key。Gemini 3.6 Flash 的模型定價提供免費層，但實際免費額度與計費層級取決於該 key 所屬的 Google 專案；程式不會替你變更計費設定。[官方定價](https://ai.google.dev/gemini-api/docs/pricing)、[相容介面](https://ai.google.dev/gemini-api/docs/openai)。

驗收期間曾遇 DNS 連線失敗、無效 key 與免費額度 429；成功的真實模型驗收由使用者在可連網的本機終端機執行，報告與 patch 由本聊天讀取檢查。以下為日後重新執行的命令，MVP 收尾不需要再消耗一次模型額度。

```sh
python3 -m vancecode.evaluation --live --repeats 1 --max-steps 20 --request-interval 15 --rate-limit-retries 2 --output reports/live-rerun.json
```

這會實際呼叫 API。驗收時保留全部案例的成功與失敗；不得改用離線結果填補失敗，也不得把未執行當成通過。若有失敗，先判讀 reason 與 patch，再決定修正 harness 或將失敗記為已知限制。

## 已知限制

- 目前的檔案與執行政策不是 OS sandbox，僅適用可信任 repo。
- Context 使用 JSON 字元預算，尚無精確 token 計量、輸出 token 預留與成本統計。
- Evaluation 只涵蓋三個小型 Python 修復任務，不能推論大型專案能力。
- Holdout 只從 Agent repo 與對話中分離；原始碼仍在 runner 專案，不是安全保密機制。
- 測試必須使用 unittest 與 `tests/` 目錄；每個檔案上限 100 KB；不提供任意 shell、新增檔案或通用 diff 編輯。
- 尚無 session 持久化、自動回復、串流回應或跨 provider 重試；完整歷史僅保存在記憶體。

本次 MVP 功能驗收已完成，不再擴大功能；後續新增任務、模型、token 計量或正式 sandbox 時，需另行評估與驗證。
