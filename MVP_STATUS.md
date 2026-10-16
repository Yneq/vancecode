# VanceCode MVP 0.1.0 驗收紀錄

狀態：驗收中，尚未宣告真實模型驗收完成。

## 本次收尾範圍

- Python CLI、單一 OpenAI-compatible provider、Agent Loop。
- read_file、search_code、apply_patch、run_tests。
- repo 路徑政策、操作確認、測試唯讀、執行逾時與 bytecode cache 隔離。
- Context Manager 的字元預算、歷史摘要、輸出節錄與行號讀檔。
- 三案例 evaluation、全新 repo、獨立可見測試與 holdout 驗收、JSON 報告與候選 patch。

## 證據與待完成項目

| 項目 | 狀態 | 證據 |
|---|---|---|
| 自動測試 | 48 個測試全部通過，含 Google 錯誤碼擷取、錯誤說明遮蔽與輸出長度限制 | `python3 -m unittest discover -s tests -v` |
| 離線評測 | 更新報告後 6/6 通過，可見與 holdout 均為 6/6 | `reports/offline.json`，mode 為 offline-scripted，包含 candidate_patch |
| Gemini 設定 | 已沿用既有股票研究專案的本機 key 與 gemini-3.6-flash；key 僅存於被忽略的 .env | 使用 Google OpenAI-compatible endpoint，未更動舊專案 |
| 真實模型三案例 | 外部終端機執行 0/3；單案例診斷確認 HTTP 400 / INVALID_ARGUMENT，尚無工具呼叫或修改 | `reports/live.json` 與 `reports/live-diagnostic.json`；需新版 provider_reason/request_issue 判讀，不推定為模型能力失敗 |
| 真實模型 patch 人工檢查 | 待 live 報告 | 檢查每案例 candidate_patch，確認符合規格、未硬編碼測試答案 |
| GitHub 最終同步 | 依使用者安排，留待明天一併 push | 比較本機 HEAD 與遠端 main |

離線 reference patch 的程式邏輯已檢查：pricing 只對商品小計折扣後加運費；slug 以 whitespace split/join 正規化並保留標點；mean 檢查空輸入後使用除法保留小數。這是 reference patch 的檢查，不等同檢查真實模型產出的 patch。

## 執行真實模型驗收

在本專案目錄的 `.env` 填入 `OPENAI_API_KEY`、`VANCECODE_MODEL`；若使用其他相容服務，再設定 `VANCECODE_BASE_URL`。不要把金鑰放入 README、報告或 Git。

本機 Gemini 設定已完成，不需重新申請 key。Gemini 使用 `https://generativelanguage.googleapis.com/v1beta/openai`；`OPENAI_API_KEY` 在此只是相容介面的設定名稱，內容是 Gemini key。Gemini 3.6 Flash 的模型定價提供免費層，但實際免費額度與計費層級取決於該 key 所屬的 Google 專案；程式不會替你變更計費設定。[官方定價](https://ai.google.dev/gemini-api/docs/pricing)、[相容介面](https://ai.google.dev/gemini-api/docs/openai)。

第一次預檢只執行 `shipping_discount`。Baseline 有重現故障，但 provider 無法連線；另以 DNS 查詢確認目前工作階段無法解析 `generativelanguage.googleapis.com`。因此保留預檢紀錄，不繼續消耗其他案例，也不將 0/1 當成 Gemini 修復失敗率。需在可連網的本機終端機執行下列完整驗收，再回看 candidate_patch。

```sh
python3 -m vancecode.evaluation --live --repeats 1 --max-steps 20 --output reports/live.json
```

這會實際呼叫 API。驗收時保留全部案例的成功與失敗；不得改用離線結果填補失敗，也不得把未執行當成通過。若有失敗，先判讀 reason 與 patch，再決定修正 harness 或將失敗記為已知限制。

## 已知限制

- 目前的檔案與執行政策不是 OS sandbox，僅適用可信任 repo。
- Context 使用 JSON 字元預算，尚無精確 token 計量、輸出 token 預留與成本統計。
- Evaluation 只涵蓋三個小型 Python 修復任務，不能推論大型專案能力。
- Holdout 只從 Agent repo 與對話中分離；原始碼仍在 runner 專案，不是安全保密機制。
- 測試必須使用 unittest 與 `tests/` 目錄；每個檔案上限 100 KB；不提供任意 shell、新增檔案或通用 diff 編輯。
- 尚無 session 持久化、自動回復、串流回應或跨 provider 重試；完整歷史僅保存在記憶體。

本次 MVP 收尾不再擴大功能。完成 live 驗收、人工檢查與 GitHub 同步後，再更新本文件的實際結果。
