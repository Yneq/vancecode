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
| 自動測試 | 57 個測試全部通過，含錯誤遮蔽、節流、重試次數限制與跨案例排程 | `python3 -m unittest discover -s tests -v` |
| 離線評測 | 更新報告後 6/6 通過，可見與 holdout 均為 6/6 | `reports/offline.json`，mode 為 offline-scripted，包含 candidate_patch |
| Gemini 設定 | 使用者已換入有效 Gemini key，模型為 gemini-3.6-flash；key 僅存於被忽略的 .env | shipping_discount 已成功呼叫 API 並完成修復；未更動舊專案 |
| 真實模型三案例 | shipping_discount 已驗收通過；另兩例遇到免費額度 HTTP 429 中止，待以節流與重試重新驗收 | `reports/live-diagnostic.json`：live，8 回合、7 次工具呼叫、約 31.3 秒，可見與 holdout 均通過；`reports/live-remaining.json` 保留 429 紀錄；舊 `reports/live.json` 為無效 key 時的失敗紀錄 |
| 真實模型 patch 人工檢查 | pricing 已檢查，另兩例待執行 | Gemini 僅修改 pricing.py 的折扣公式：先對商品小計折扣取整，再加運費；沒有改測試或寫死答案 |
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
