"""Opt-in synchronous pacing; 429 retries never replay repository tools."""
import math
import random
import time
from .provider import ProviderError


class RequestSchedule:
    def __init__(self, interval=0, retries=0, *, clock=time.monotonic, sleep=time.sleep,
                 jitter=lambda: random.uniform(0, 1), on_wait=None):
        if not math.isfinite(interval) or not 0 <= interval <= 60 or type(retries) is not int or not 0 <= retries <= 5:
            raise ValueError("Request interval must be 0..60 seconds; rate retries must be 0..5")
        self.interval, self.retries = interval, retries
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.on_wait = on_wait or (lambda seconds: None)
        self.next_at = 0
        self.requests = self.retry_count = 0
        self.wait_seconds = 0.0

    def wait(self):
        remaining = max(0, self.next_at - self.clock())
        if remaining:
            self.on_wait(remaining)
        while self.clock() < self.next_at:
            delay = min(15, self.next_at - self.clock())
            self.sleep(delay)
            self.wait_seconds += delay


class PacedProvider:
    def __init__(self, provider, schedule: RequestSchedule):
        self.provider, self.schedule = provider, schedule

    def complete(self, messages, tools):
        schedule = self.schedule
        for attempt in range(schedule.retries + 1):
            schedule.wait()
            schedule.requests += 1
            schedule.next_at = schedule.clock() + schedule.interval
            try:
                return self.provider.complete(messages, tools)
            except ProviderError as exc:
                if exc.http_status != 429:
                    raise
                if schedule.retries == 0:
                    raise
                required = exc.details.get("retry_after_seconds")
                delay = max(required or 0, 2 ** (attempt + 1)) + 1 + schedule.jitter()
                # Never shorten long server cooldowns into an early retry.
                # Leave daily quota/long cooldown failures for a later run.
                if delay > 60:
                    raise
                schedule.next_at = max(schedule.next_at, schedule.clock() + delay)
                if attempt == schedule.retries:
                    raise
                schedule.retry_count += 1
