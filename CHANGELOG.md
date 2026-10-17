# Changelog

## 0.1.0 — 2026-10-17

首個完成驗收的 MVP：Python CLI、provider abstraction、Agent Loop 與四個 repository tools，另含操作確認、路徑保護、測試執行隔離、Context Manager、錯誤診斷、請求節流與限次 429 重試。

Evaluation Harness 提供三個故障案例、獨立驗收與 holdout 測試、候選修改差異及 JSON 報告。59 個自動測試通過；Gemini 3.6 Flash 已分兩次完成三個案例的真實修復驗收與人工差異檢查，早期失敗紀錄保留。

此版本供學習與作品展示：不是 OS sandbox，沒有精確 token/成本統計，也未驗證大型 repository 的修復能力。完整證據與限制見 [MVP_STATUS.md](MVP_STATUS.md)。
