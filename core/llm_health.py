import threading
import time
from dataclasses import dataclass

from providers.registry import PROVIDERS


@dataclass
class HealthState:
    online: bool | None = None
    latency: float = 0.0
    last_success: float = 0.0
    last_failure: float = 0.0
    failures: int = 0


class HealthManager:
    def __init__(self, interval: int = 60):
        self.interval = interval
        self._states = {name: HealthState() for name in PROVIDERS}
        self._lock = threading.Lock()
        self._started = False

    def start(self):
        if self._started:
            return
        self._started = True
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()

    def is_online(self, provider_name: str) -> bool:
        state = self.get(provider_name)
        return True if state.online is None else state.online

    def get(self, provider_name: str) -> HealthState:
        with self._lock:
            return self._states.setdefault(provider_name, HealthState())

    def snapshot(self) -> dict:
        with self._lock:
            return {name: state for name, state in self._states.items()}

    def record_success(self, provider_name: str, latency: float):
        with self._lock:
            state = self._states.setdefault(provider_name, HealthState())
            state.online = True
            state.latency = latency
            state.last_success = time.time()
            state.failures = 0  # una respuesta buena limpia la racha de fallos

    def record_failure(self, provider_name: str):
        with self._lock:
            state = self._states.setdefault(provider_name, HealthState())
            state.online = False
            state.last_failure = time.time()
            state.failures += 1

    def refresh_provider(self, provider_name: str):
        provider = PROVIDERS[provider_name]
        started = time.monotonic()
        try:
            online = bool(provider.health())
            latency = time.monotonic() - started
            if online:
                self.record_success(provider_name, latency)
            else:
                self.record_failure(provider_name)
        except Exception:
            self.record_failure(provider_name)

    def _loop(self):
        while True:
            for provider_name in PROVIDERS:
                self.refresh_provider(provider_name)
            time.sleep(self.interval)


health_manager = HealthManager()
health_manager.start()
