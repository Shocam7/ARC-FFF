"""
arc/core/audio.py
─────────────────
Thread-safe PCM audio playback via sounddevice.
One instance per live agent so each has its own independent audio buffer.

Hold gate
─────────
An agent's audio can be "held" (buffered but not played) while another agent
is finishing its turn.  Call hold() to engage, release() to start draining.
This enables look-ahead preparation: the incoming agent generates its full
audio response while the current speaker's audio finishes naturally, then
plays back with zero perceptible gap.
"""

import threading
import numpy as np
import sounddevice as sd

from .config import SR_OUT


class AudioOutputManager:
    """Feeds raw 16-bit PCM bytes into a sounddevice output stream."""

    def __init__(self):
        self._buf:    np.ndarray        = np.array([], dtype=np.float32)
        self._lock:   threading.Lock    = threading.Lock()
        self._stream: sd.OutputStream | None = None
        self._held:   bool              = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        def _cb(outdata, frames, time, status):
            with self._lock:
                if self._held:
                    # Gate is closed — output silence, keep buffer intact
                    outdata[:, 0] = 0.0
                    return
                n = min(frames, len(self._buf))
                outdata[:n, 0] = self._buf[:n]
                outdata[n:, 0] = 0.0
                self._buf = self._buf[n:]

        self._stream = sd.OutputStream(
            samplerate=SR_OUT, channels=1, dtype="float32",
            blocksize=2048, callback=_cb,
        )
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    # ── Hold gate ─────────────────────────────────────────────────────────────

    def hold(self):
        """Pause playback: audio is buffered but not drained until release()."""
        with self._lock:
            self._held = True

    def release(self):
        """Open the gate: buffered audio begins draining immediately."""
        with self._lock:
            self._held = False

    @property
    def is_held(self) -> bool:
        with self._lock:
            return self._held

    # ── Data ──────────────────────────────────────────────────────────────────

    def feed(self, pcm_bytes: bytes):
        """Accept raw signed 16-bit PCM and append to the playback ring."""
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        with self._lock:
            self._buf = np.concatenate([self._buf, samples])

    def clear(self):
        """Discard buffered audio and clear hold (called on hard interruption)."""
        with self._lock:
            self._buf = np.array([], dtype=np.float32)
            self._held = False

    @property
    def buffered_seconds(self) -> float:
        with self._lock:
            return len(self._buf) / SR_OUT
