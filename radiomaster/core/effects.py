"""Audio effects engine: parameter schemas + real-time DSP wiring.

Each effect used to compile to an ffmpeg `libavfilter` audio filter, baked
into the decode subprocess's `-af` chain -- meaning every parameter tweak
required killing and relaunching ffmpeg and reconnecting to the stream, and
a single out-of-range value (e.g. an aecho decay of exactly 0) could crash
ffmpeg and the whole stream with it.

Effects are now applied as a chain of numpy DSP processors (see dsp.py)
directly to already-decoded PCM inside the audio output callback, so
changes are instant and can never crash the stream. `make_processor` builds
a fresh stateful processor instance for an effect; `apply_params` converts
this effect's own UI parameter dict into whatever that processor's update
method expects and applies it. Two of the eight classic DirectX effect
names have no off-the-shelf DSP equivalent, so they're approximated
(documented per-effect below):

- Reverb  -> multi-tap recirculating delay (dsp.MultiTapDelay)
- Gargle  -> sinusoidal amplitude modulation / tremolo (dsp.Tremolo);
             DirectX Gargle used a square wave, this is the closest simple
             substitute.

The other six map onto: Equalizer -> 10-band peaking EQ (dsp.Equalizer),
Compressor -> dsp.Compressor, Distortion -> dsp.Distortion (soft-clip
waveshaping), Echo -> dsp.MultiTapDelay (single tap), Flanger/Chorus ->
dsp.ModulatedDelay (LFO-modulated delay line, different parameter ranges).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from . import dsp
from .dsp import EQ_BANDS_HZ

ParamKind = Literal["float", "int", "choice"]


@dataclass
class Param:
    key: str
    label: str
    kind: ParamKind
    default: object
    min: float = 0
    max: float = 0
    step: float = 0.1
    choices: tuple[str, ...] = ()
    unit: str = ""


@dataclass
class EffectSpec:
    id: str
    display_name: str
    params: list[Param]
    make_processor: Callable[[], object]
    apply_params: Callable[[object, dict], None]
    note: str = ""

    def default_params(self) -> dict:
        return {p.key: p.default for p in self.params}


def _eq_params() -> list[Param]:
    return [
        Param(f"gain_{hz}", f"{hz} Hz gain", "float", 0.0, -12, 12, 0.5, unit="dB")
        for hz in EQ_BANDS_HZ
    ]


def _mk_equalizer() -> dsp.Equalizer:
    return dsp.Equalizer()


def _apply_equalizer(proc: dsp.Equalizer, p: dict) -> None:
    proc.update(p)


def _mk_compressor() -> dsp.Compressor:
    return dsp.Compressor()


def _apply_compressor(proc: dsp.Compressor, p: dict) -> None:
    proc.update(p)


def _mk_distortion() -> dsp.Distortion:
    return dsp.Distortion()


def _apply_distortion(proc: dsp.Distortion, p: dict) -> None:
    proc.update(p)


def _mk_delay() -> dsp.MultiTapDelay:
    return dsp.MultiTapDelay()


def _apply_echo(proc: dsp.MultiTapDelay, p: dict) -> None:
    # A delay/decay of exactly 0 used to make ffmpeg's aecho exit outright;
    # the DSP delay line tolerates 0 fine, but keep the same tiny floor so
    # dragging a slider to its minimum fades the echo out rather than
    # snapping it to a literal zero-length tap.
    delay_ms = max(1.0, float(p["delay_ms"]))
    decay = max(0.001, float(p["decay"]))
    proc.set_taps(
        in_gain=float(p["in_gain"]), out_gain=float(p["out_gain"]),
        taps_ms_decay=[(delay_ms, decay)],
    )


def _mk_reverb() -> dsp.MultiTapDelay:
    return dsp.MultiTapDelay()


def _apply_reverb(proc: dsp.MultiTapDelay, p: dict) -> None:
    room = 0.6 + float(p["room_size"])
    decay = float(p["decay"])
    mix = float(p["mix"])
    taps = [(29 * room, max(0.001, decay * f * mix)) for f in (0.7, 0.55, 0.4, 0.3)]
    proc.set_taps(in_gain=1.0, out_gain=1.0, taps_ms_decay=taps)


def _mk_modulated_delay() -> dsp.ModulatedDelay:
    return dsp.ModulatedDelay()


def _apply_flanger(proc: dsp.ModulatedDelay, p: dict) -> None:
    proc.update({
        "base_delay_ms": float(p["delay_ms"]),
        "depth_ms": float(p["depth_ms"]),
        "speed_hz": float(p["speed_hz"]),
        "feedback": float(p["regen_pct"]) / 100.0,
        "mix": float(p["width_pct"]) / 100.0,
        "phase_deg": float(p["phase_pct"]) / 100.0 * 360.0,
        "in_gain": 1.0, "out_gain": 1.0,
        "shape": "triangular" if p["shape"] == "triangular" else "sine",
    })


def _apply_chorus(proc: dsp.ModulatedDelay, p: dict) -> None:
    proc.update({
        "base_delay_ms": float(p["delay_ms"]),
        "depth_ms": float(p["depth_ms"]),
        "speed_hz": float(p["speed_hz"]),
        "feedback": 0.0,  # ffmpeg's chorus has no feedback, just a mixed delayed voice
        "mix": max(0.0, min(1.0, float(p["decay"]))),
        "phase_deg": 90.0,  # fixed stereo spread between L/R modulation for width
        "in_gain": float(p["in_gain"]), "out_gain": float(p["out_gain"]),
        "shape": "sine",
    })


def _mk_tremolo() -> dsp.Tremolo:
    return dsp.Tremolo()


def _apply_gargle(proc: dsp.Tremolo, p: dict) -> None:
    proc.update(p)


def _mk_loudness() -> dsp.LoudnessNormalizer:
    return dsp.LoudnessNormalizer()


def _apply_loudness(proc: dsp.LoudnessNormalizer, p: dict) -> None:
    proc.update(p)


EFFECT_SPECS: dict[str, EffectSpec] = {
    "equalizer": EffectSpec(
        "equalizer", "Equalizer", _eq_params(), _mk_equalizer, _apply_equalizer,
        note="10-band graphic EQ (ISO centre frequencies), +/-12 dB per band.",
    ),
    "compressor": EffectSpec(
        "compressor", "Compressor",
        [
            Param("threshold", "Threshold", "float", 0.125, 0.001, 1, 0.001),
            Param("ratio", "Ratio", "float", 2.0, 1, 20, 0.1),
            Param("attack", "Attack", "float", 20.0, 0.01, 2000, 1, unit="ms"),
            Param("release", "Release", "float", 250.0, 0.01, 9000, 1, unit="ms"),
            Param("makeup", "Makeup gain", "float", 2.0, 1, 64, 0.1),
            Param("knee", "Knee", "float", 2.82843, 1, 8, 0.1),
            Param("mix", "Mix", "float", 1.0, 0, 1, 0.05),
        ],
        _mk_compressor, _apply_compressor,
    ),
    "distortion": EffectSpec(
        "distortion", "Distortion",
        [
            Param("type", "Clip type", "choice", "tanh", choices=(
                "hard", "tanh", "atan", "cubic", "exp", "alg", "quintic", "sin", "erf",
            )),
            Param("param", "Shape", "float", 1.0, 0.01, 10, 0.1),
            Param("oversample", "Oversample", "int", 1, 1, 64, 1),
        ],
        _mk_distortion, _apply_distortion,
        note="Soft-clip waveshaping distortion.",
    ),
    "echo": EffectSpec(
        "echo", "Echo",
        [
            Param("in_gain", "Input gain", "float", 1.0, 0, 1, 0.05),
            Param("out_gain", "Output gain", "float", 1.0, 0, 1, 0.05),
            Param("delay_ms", "Delay", "int", 1000, 0, 90000, 10, unit="ms"),
            Param("decay", "Decay", "float", 0.5, 0, 1, 0.05),
        ],
        _mk_delay, _apply_echo,
    ),
    "flanger": EffectSpec(
        "flanger", "Flanger",
        [
            Param("delay_ms", "Delay", "float", 0.0, 0, 30, 0.5, unit="ms"),
            Param("depth_ms", "Depth", "float", 2.0, 0, 10, 0.1, unit="ms"),
            Param("regen_pct", "Regeneration", "float", 0.0, -95, 95, 1, unit="%"),
            Param("width_pct", "Width", "float", 71.0, 0, 100, 1, unit="%"),
            Param("speed_hz", "Speed", "float", 0.5, 0.1, 10, 0.1, unit="Hz"),
            Param("shape", "Shape", "choice", "sinusoidal", choices=("triangular", "sinusoidal")),
            Param("phase_pct", "Phase", "float", 25.0, 0, 100, 1, unit="%"),
            Param("interp", "Interpolation", "choice", "linear", choices=("linear", "quadratic")),
        ],
        _mk_modulated_delay, _apply_flanger,
    ),
    "chorus": EffectSpec(
        "chorus", "Chorus",
        [
            Param("in_gain", "Input gain", "float", 1.0, 0, 1, 0.05),
            Param("out_gain", "Output gain", "float", 1.0, 0, 1, 0.05),
            Param("delay_ms", "Delay", "float", 55.0, 20, 100, 1, unit="ms"),
            Param("decay", "Decay", "float", 0.4, 0, 1, 0.05),
            Param("speed_hz", "Speed", "float", 0.25, 0.1, 5, 0.05, unit="Hz"),
            Param("depth_ms", "Depth", "float", 2.0, 0, 10, 0.1, unit="ms"),
        ],
        _mk_modulated_delay, _apply_chorus,
    ),
    "gargle": EffectSpec(
        "gargle", "Gargle",
        [
            Param("frequency_hz", "Frequency", "float", 5.0, 0.1, 30, 0.1, unit="Hz"),
            Param("depth", "Depth", "float", 0.5, 0, 1, 0.05),
        ],
        _mk_tremolo, _apply_gargle,
        note="Amplitude-modulation approximation of DirectX Gargle.",
    ),
    "reverb": EffectSpec(
        "reverb", "Reverb",
        [
            Param("room_size", "Room size", "float", 0.5, 0, 1, 0.05),
            Param("decay", "Decay", "float", 0.4, 0, 1, 0.05),
            Param("mix", "Wet/dry mix", "float", 0.3, 0, 1, 0.05),
        ],
        _mk_reverb, _apply_reverb,
        note="Multi-tap recirculating-delay approximation of reverb.",
    ),
    "loudness": EffectSpec(
        "loudness", "Loudness Normalization",
        [
            Param("target_loudness", "Target loudness (RMS)", "float", 0.2, 0.0, 0.5, 0.01),
            Param("max_gain", "Max gain", "float", 15.0, 1.0, 50.0, 1.0),
            Param("compress", "Extra compression", "float", 0.0, 0.0, 30.0, 0.5),
        ],
        _mk_loudness, _apply_loudness,
        note="Evens out loudness between stations so the same volume % sounds "
             "about the same everywhere -- a causal, real-time automatic gain "
             "control riding a smoothed RMS envelope toward the target level.",
    ),
}

# Order matters for how effects sound when chained: EQ/dynamics first, then
# distortion/colour effects, then modulation, with time-based echo/reverb,
# and loudness normalization LAST so it corrects the final output level
# regardless of what every effect before it did to the signal.
CHAIN_ORDER = ["equalizer", "compressor", "distortion", "chorus", "flanger", "gargle", "echo", "reverb", "loudness"]

DISPLAY_ORDER = ["chorus", "compressor", "distortion", "echo", "flanger", "gargle", "reverb", "equalizer", "loudness"]
