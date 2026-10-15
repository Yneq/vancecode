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
| 自動測試 | 新增差異紀錄後重新執行，40 個測試全部通過 | `python3 -m unittest discover -s tests -v` |
| 離線評測 | 更新報告後 6/6 通過，可見與 holdout 均為 6/6 | `reports/offline.json`，mode 為 offline-scripted，包含 candidate_patch |
| 真實模型三案例 | 待設定 API key 與模型後執行 | 尚無 live 報告，不推定成功 |
| 真實模型 patch 人工檢查 | 待 live 報告 | 檢查每案例 candidate_patch，確認符合規格、未硬編碼測試答案 |
| GitHub 最終同步 | 待最後 commit 與 push 驗證 | 比較本機 HEAD 與遠端 main |

離線 reference patch 的程式邏輯已檢查：pricing 只對商品小計折扣後加運費；slug 以 whitespace split/join 正規化並保留標點；mean 檢查空輸入後使用除法保留小數。這是 reference patch 的檢查，不等同檢查真實模型產出的 patch。

## 執行真實模型驗收

在本專案目錄的 `.env` 填入 `OPENAI_API_KEY`、`VANCECODE_MODEL`；若使用其他相容服務，再設定 `VANCECODE_BASE_URL`。不要把金鑰放入 README、報告或 Git。

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
