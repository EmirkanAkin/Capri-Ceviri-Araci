"""
Capri — Süre tahmini
====================
İki parça: `estimate` çeviri başlamadan metin miktarından tahmin verir (önceki çevirilerde ölçülen hız varsa
onu kullanır), `LiveEta` çeviri sürerken son 90 sn'nin gerçek hızından kalan süreyi hesaplar.
"""
from __future__ import annotations

import collections
import json
import time
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Optional, Tuple

# Başlangıç hızları: karakter/sn, tek iş parçacığı (Gemini: anahtar başına). Gerçek çevirilerden öğrenilip güncellenir.
PRIOR_CPS = {"gemini": 900, "openai": 200, "anthropic": 200, "deepl": 1500, "ollama": 50, "opus": 2500, "nllb": 1500}
DEFAULT_CPS = 150
CPU_PENALTY = 10            # yerel modeller GPU'suz yaklaşık bu kadar yavaş
RATE_WINDOW = 90.0


def format_duration(seconds: Optional[float]) -> str:
    """Kalan süre metni: '50 sn', '4 dk 10 sn', '1 sa 5 dk'."""
    if seconds is None:
        return ""
    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total} sn"
    if total < 3600:
        minutes, secs = divmod(total, 60)
        return f"{minutes} dk {secs} sn" if secs else f"{minutes} dk"
    hours, rest = divmod(total, 3600)
    minutes = rest // 60
    return f"{hours} sa {minutes} dk" if minutes else f"{hours} sa"


def format_estimate(seconds: float) -> str:
    """Tahmin metni kasıtlı olarak yuvarlak: yanlış bir kesinlik izlenimi vermez."""
    if seconds < 10:
        return "birkaç saniye"
    if seconds < 60:
        return f"yaklaşık {int(round(seconds / 5.0)) * 5} sn"
    if seconds < 3600:
        return f"yaklaşık {max(1, int(round(seconds / 60.0)))} dk"
    hours, rest = divmod(int(round(seconds / 300.0)) * 300, 3600)
    return f"yaklaşık {hours} sa {rest // 60} dk" if rest else f"yaklaşık {hours} sa"


def format_rate(items_per_sec: Optional[float], unit: str = "satır") -> str:
    if not items_per_sec or items_per_sec <= 0:
        return ""
    if items_per_sec >= 1:
        return f"{items_per_sec:.1f}".replace(".", ",") + f" {unit}/sn"
    return f"{max(1, int(round(items_per_sec * 60)))} {unit}/dk"


class SpeedStore:
    """Motor başına ölçülen çeviri hızı (karakter/sn, iş parçacığı başına); diskte saklanır."""

    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._data: Dict[str, float] = {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            self._data = {}

    def get(self, model: str) -> Optional[float]:
        return self._data.get(model)

    def record(self, model: str, chars: float, seconds: float, workers: int = 1) -> Optional[float]:
        if chars <= 0 or seconds <= 0:
            return None
        measured = chars / seconds / max(1, workers)
        previous = self._data.get(model)
        value = measured if previous is None else previous * 0.5 + measured * 0.5
        self._data[model] = round(value, 2)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass
        return value


def estimate(model: str, chars: int, workers: int = 1, gpu: bool = True,
             store: Optional[SpeedStore] = None) -> Dict[str, Any]:
    """Metin miktarı ve motordan süre tahmini. basis: 'learned' (bu bilgisayarda ölçüldü) ya da 'prior'."""
    learned = store.get(model) if store else None
    cps = learned if learned else PRIOR_CPS.get(model, DEFAULT_CPS)
    if not learned and model in ("opus", "nllb") and not gpu:
        cps /= CPU_PENALTY
    seconds = chars / (cps * max(1, workers))
    return {"seconds": round(seconds, 1), "text": format_estimate(seconds), "basis": "learned" if learned else "prior"}


# Yaklaşık fiyatlar (USD / 1M token; DeepL: / 1M karakter). Fiyatlar değişir; arayüzde "yaklaşık" yazar.
PRICES = [
    ("gpt-4o-mini", 0.15, 0.60), ("gpt-4.1-nano", 0.10, 0.40), ("gpt-4.1-mini", 0.40, 1.60), ("gpt-4.1", 2.00, 8.00),
    ("gpt-4o", 2.50, 10.00), ("gpt-5-nano", 0.05, 0.40), ("gpt-5-mini", 0.25, 2.00), ("gpt-5", 1.25, 10.00),
    ("claude-3-5-haiku", 0.80, 4.00), ("claude-haiku", 1.00, 5.00), ("claude-3-haiku", 0.25, 1.25),
    ("claude-sonnet", 3.00, 15.00), ("claude-3-5-sonnet", 3.00, 15.00), ("claude-opus", 15.00, 75.00),
]
DEEPL_PER_MILLION_CHARS = 25.0
CHARS_PER_TOKEN = 3.5
OVERHEAD = 1.25    # sistem talimatı, JSON biçimi ve yeniden denemeler


def estimate_cost(provider: str, model: str, chars: int) -> Optional[Dict[str, Any]]:
    """Ücretli API'ler için yaklaşık maliyet; ücretsiz/yerel motorlar ve bilinmeyen modeller için None."""
    if chars <= 0:
        return None
    if provider == "deepl":
        usd = chars / 1_000_000 * DEEPL_PER_MILLION_CHARS
    elif provider in ("openai", "anthropic"):
        name = (model or "").lower()
        match = next((p for p in sorted(PRICES, key=lambda p: -len(p[0])) if name.startswith(p[0])), None)
        if not match:
            return None
        tokens_in = chars / CHARS_PER_TOKEN * OVERHEAD
        tokens_out = chars * 1.2 / CHARS_PER_TOKEN
        usd = (tokens_in * match[1] + tokens_out * match[2]) / 1_000_000
    else:
        return None
    text = "1 sentten az" if usd < 0.01 else f"yaklaşık {usd:.2f} $".replace(".", ",")
    return {"usd": round(usd, 4), "text": text}


class LiveEta:
    """İlerleme örneklerinden kalan süre. Toplu çalışan motorlar için son 90 sn'nin ortalamasını kullanır."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self.total = 0
        self.done = 0
        self.started = clock()
        self.base = 0
        self._last_sample = self.started
        self._samples: Deque[Tuple[float, int]] = collections.deque()

    def start(self, total: int, done: int = 0) -> None:
        self.total = max(total, 1)
        self.done = self.base = done
        self.started = self._last_sample = self._clock()
        self._samples.clear()
        self._samples.append((self.started, done))

    def update(self, done: int) -> None:
        now = self._clock()
        # Başlangıçtaki ani sıçrama önbellekten gelir; hız hesabına katılmaz
        if now - self.started < 0.5 and len(self._samples) == 1:
            self.base = done
            self._samples[0] = (self.started, done)
        elif done != self.done:
            self._samples.append((now, done))
            self._last_sample = now
            while len(self._samples) > 2 and now - self._samples[0][0] > RATE_WINDOW:
                self._samples.popleft()
        self.done = done

    def rate(self) -> Optional[float]:
        if len(self._samples) < 2:
            return None
        (t0, d0), (t1, d1) = self._samples[0], self._samples[-1]
        return (d1 - d0) / (t1 - t0) if t1 > t0 and d1 > d0 else None

    def eta_seconds(self, fallback_per_item: Optional[float] = None) -> Optional[float]:
        remaining = max(0, self.total - self.done)
        rate = self.rate()
        if rate:
            return remaining / rate
        return remaining * fallback_per_item if fallback_per_item else None

    def elapsed(self) -> float:
        return self._clock() - self.started

    def worked(self) -> Tuple[int, float]:
        """(çevrilen satır, geçen süre): hız öğrenmek için."""
        return self.done - self.base, self._last_sample - self.started
