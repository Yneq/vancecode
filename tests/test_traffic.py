import unittest
from unittest.mock import patch
from vancecode.provider import ProviderError
from vancecode.traffic import PacedProvider, RequestSchedule
from vancecode.evaluation import evaluate, ScriptedBenchmarkProvider
from vancecode.benchmarks import BENCHMARKS


class Clock:
    def __init__(self):
        self.now = 0
        self.delays = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.now += seconds


class Stub:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


class TrafficTests(unittest.TestCase):
    def schedule(self, interval=0, retries=0):
        self.clock = Clock()
        return RequestSchedule(interval, retries, clock=self.clock.time, sleep=self.clock.sleep, jitter=lambda: 0)

    def test_interval_is_shared_across_cases(self):
        schedule = self.schedule(13)
        PacedProvider(Stub([{}]), schedule).complete([], [])
        PacedProvider(Stub([{}]), schedule).complete([], [])
        self.assertEqual(self.clock.now, 13)
        self.assertEqual(schedule.requests, 2)

    def test_429_waits_for_server_delay_then_retries_same_turn(self):
        schedule = self.schedule(13, 2)
        provider = Stub([ProviderError("quota", http_status=429, retry_after_seconds=45), {"role": "assistant"}])
        self.assertEqual(PacedProvider(provider, schedule).complete([], []), {"role": "assistant"})
        self.assertEqual(self.clock.now, 46)
        self.assertEqual(schedule.retry_count, 1)
        self.assertTrue(all(s <= 15 for s in self.clock.delays))

    def test_other_errors_are_not_retried(self):
        for status in (400, 401, 403, 404, 503):
            schedule = self.schedule(13, 2)
            provider = Stub([ProviderError("failure", http_status=status)])
            with self.assertRaises(ProviderError):
                PacedProvider(provider, schedule).complete([], [])
            self.assertEqual(provider.calls, 1)
            self.assertEqual(schedule.retry_count, 0)

    def test_retry_budget_is_bounded(self):
        schedule = self.schedule(0, 2)
        provider = Stub([ProviderError("quota", http_status=429)] * 3)
        with self.assertRaises(ProviderError):
            PacedProvider(provider, schedule).complete([], [])
        self.assertEqual(provider.calls, 3)
        self.assertEqual(schedule.retry_count, 2)
        self.assertEqual(self.clock.now, 8)  # 2+1, then 4+1, excluding jitter

    def test_long_server_cooldown_is_not_shortened(self):
        schedule = self.schedule(13, 2)
        provider = Stub([ProviderError("daily quota", http_status=429, retry_after_seconds=3600)])
        with self.assertRaises(ProviderError):
            PacedProvider(provider, schedule).complete([], [])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.clock.now, 0)
        next_provider = Stub([{}])
        with self.assertRaises(ProviderError):
            PacedProvider(next_provider, schedule).complete([], [])
        self.assertEqual(next_provider.calls, 0)

    def test_long_quota_blocks_remaining_evaluation_cases(self):
        schedule = self.schedule(15, 2)
        provider = Stub([ProviderError("daily quota", http_status=429, retry_after_seconds=39774)])
        with patch("vancecode.evaluation.RequestSchedule", return_value=schedule):
            report = evaluate(lambda _: provider, mode="live", cases=BENCHMARKS[:2])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(report["runs"][0]["reason"], "quota_cooldown")
        self.assertTrue(report["runs"][1]["skipped_due_to_quota"])
        self.assertEqual(report["runs"][1]["transport_requests"], 0)

    def test_defaults_do_not_add_retry_or_cross_case_cooldown(self):
        schedule = self.schedule()
        with self.assertRaises(ProviderError):
            PacedProvider(Stub([ProviderError("quota", http_status=429, retry_after_seconds=45)]), schedule).complete([], [])
        PacedProvider(Stub([{}]), schedule).complete([], [])
        self.assertEqual(self.clock.now, 0)

    def test_invalid_limits(self):
        for interval, retries in ((-1, 0), (61, 0), (float("nan"), 0), (float("inf"), 0), (0, -1), (0, 6)):
            with self.assertRaises(ValueError):
                RequestSchedule(interval, retries)

    def test_evaluation_reports_transport_requests_and_waiting(self):
        schedule = self.schedule(13, 2)
        with patch("vancecode.evaluation.RequestSchedule", return_value=schedule):
            report = evaluate(ScriptedBenchmarkProvider, mode="offline-scripted", cases=BENCHMARKS[:2],
                              request_interval=13, rate_limit_retries=2)
        self.assertEqual(report["summary"]["passed"], 2)
        self.assertEqual([r["transport_requests"] for r in report["runs"]], [7, 7])
        self.assertEqual(sum(r["request_wait_seconds"] for r in report["runs"]), 169)
        class Flaky(ScriptedBenchmarkProvider):
            def __init__(self, case):
                super().__init__(case)
                self.failed = False

            def complete(self, messages, tools):
                if not self.failed:
                    self.failed = True
                    raise ProviderError("quota", http_status=429, retry_after_seconds=3)
                return super().complete(messages, tools)
        schedule = self.schedule(13, 2)
        with patch("vancecode.evaluation.RequestSchedule", return_value=schedule):
            report = evaluate(Flaky, mode="offline-scripted", cases=BENCHMARKS[:1],
                              request_interval=13, rate_limit_retries=2)
        row = report["runs"][0]
        self.assertTrue(row["success"])
        self.assertEqual(row["provider_calls"], 7)
        self.assertEqual(row["transport_requests"], 8)
        self.assertEqual(row["rate_limit_retries"], 1)
        self.assertEqual(row["tool_calls"], 6)
