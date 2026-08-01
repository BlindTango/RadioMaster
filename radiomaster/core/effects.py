"""Audio effects engine: parameter schemas + ffmpeg audio-filter ("-af") builders.

Each effect maps to a real ffmpeg `libavfilter` audio filter. Two of the eight
classic DirectX effect names have no direct ffmpeg equivalent, so they are
approximated with the closest available filter (documented per-effect below):

- Reverb  -> multi-tap `aecho` (ffmpeg ships no dedicated reverb filter)
- Gargle  -> `tremolo` (amplitude modulation; DirectX Gargle used a square
             wave, this uses ffmpeg's sinusoidal tremolo as the nearest stock
             filter)

The other six map directly: Chorus->chorus, Compressor->acompressor,
Distortion->asoftclip, Echo->aecho, Flanger->flanger,
Equalizer->10-band chained `equalizer` (ISO graphic-EQ centre frequencies).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

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
    build_filter: Callable[[dict], str]
    note: str = ""

    def default_params(self) -> dict:
        return {p.key: p.default for p in self.params}


_EQ_BANDS_HZ = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def _eq_params() -> list[Param]:
    return [
        Param(f"gain_{hz}", f"{hz} Hz gain", "float", 0.0, -12, 12, 0.5, unit="dB")
        for hz in _EQ_BANDS_HZ
    ]


def _build_equalizer(p: dict) -> str:
    stages = [
        f"equalizer=f={hz}:width_type=o:width=1:g={p.get(f'gain_{hz}', 0.0)}"
        for hz in _EQ_BANDS_HZ
    ]
    return ",".join(stages)


def _build_compressor(p: dict) -> str:
    return (
        f"acompressor=threshold={p['threshold']}:ratio={p['ratio']}:"
        f"attack={p['attack']}:release={p['release']}:makeup={p['makeup']}:"
        f"knee={p['knee']}:mix={p['mix']}"
    )


def _build_distortion(p: dict) -> str:
    return f"asoftclip=type={p['type']}:param={p['param']}:oversample={p['oversample']}"


def _build_echo(p: dict) -> str:
    # aecho rejects a delay or decay of exactly 0 outright and ffmpeg exits
    # immediately -- clamp both away from 0 so dragging either slider all the
    # way down fades the echo out instead of killing the decode process.
    delay_ms = max(1, int(p['delay_ms']))
    decay = max(0.001, float(p['decay']))
    return f"aecho={p['in_gain']}:{p['out_gain']}:{delay_ms}:{decay}"


def _build_flanger(p: dict) -> str:
    return (
        f"flanger=delay={p['delay_ms']}:depth={p['depth_ms']}:regen={p['regen_pct']}:"
        f"width={p['width_pct']}:speed={p['speed_hz']}:shape={p['shape']}:"
        f"phase={p['phase_pct']}:interp={p['interp']}"
    )


def _build_chorus(p: dict) -> str:
    return (
        f"chorus={p['in_gain']}:{p['out_gain']}:{p['delay_ms']}:"
        f"{p['decay']}:{p['speed_hz']}:{p['depth_ms']}"
    )


def _build_gargle(p: dict) -> str:
    return f"tremolo=f={p['frequency_hz']}:d={p['depth']}"


def _build_loudness(p: dict) -> str:
    # dynaudnorm, not the two-pass loudnorm filter: loudnorm's first pass
    # needs to measure the WHOLE file before applying gain, which doesn't
    # exist for a live, unbounded stream. dynaudnorm adapts continuously
    # (sliding Gaussian-smoothed window) so it works single-pass on live
    # audio. targetrms is what actually evens out perceived loudness between
    # stations (peak-only normalization alone still lets a quiet station
    # stay quiet if it never reaches peak); maxgain caps how hard a very
    # quiet stream gets boosted so near-silence doesn't get amplified into
    # audible noise.
    return (
        f"dynaudnorm=framelen=500:gausssize=31:peak=0.95:"
        f"maxgain={p['max_gain']}:targetrms={p['target_loudness']}:compress={p['compress']}"
    )


def _build_reverb(p: dict) -> str:
    room = 0.6 + float(p["room_size"])
    decay = float(p["decay"])
    # aecho's in_gain/out_gain scale the WHOLE output, not the wet/dry
    # balance — feeding "mix" into out_gain (as this used to) cut the
    # overall stream volume as mix rose above 0. Fixed at unity here, with
    # mix instead scaling the echo-tap decay levels directly, so it actually
    # controls reverb wetness without touching the dry level.
    mix = float(p["mix"])
    # aecho rejects a decay of exactly 0 outright and ffmpeg exits immediately,
    # so dragging "Decay" or "Wet/dry mix" down to 0 must fade the reverb out
    # rather than produce a literal 0.000 tap -- clamp every tap to a tiny but
    # non-zero floor.
    delays = "|".join(str(max(1, int(d * room))) for d in (29, 37, 44, 51))
    decays = "|".join(f"{max(0.001, decay * f * mix):.3f}" for f in (0.7, 0.55, 0.4, 0.3))
    return f"aecho=1.0:1.0:{delays}:{decays}"


EFFECT_SPECS: dict[str, EffectSpec] = {
    "equalizer": EffectSpec(
        "equalizer", "Equalizer", _eq_params(), _build_equalizer,
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
        _build_compressor,
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
        _build_distortion,
        note="Soft-clip distortion (ffmpeg has no filter literally named 'distortion').",
    ),
    "echo": EffectSpec(
        "echo", "Echo",
        [
            # ffmpeg's aecho in_gain/out_gain scale the WHOLE output (dry
            # signal included), not just the echo tap — its own doc defaults
            # of 0.6/0.3 were measured (via volumedetect) to cut overall
            # loudness by ~12dB the instant Echo is enabled. Defaulting both
            # to 1.0 keeps the dry level intact; "decay" alone controls how
            # audible the echo itself is.
            Param("in_gain", "Input gain", "float", 1.0, 0, 1, 0.05),
            Param("out_gain", "Output gain", "float", 1.0, 0, 1, 0.05),
            Param("delay_ms", "Delay", "int", 1000, 0, 90000, 10, unit="ms"),
            Param("decay", "Decay", "float", 0.5, 0, 1, 0.05),
        ],
        _build_echo,
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
        _build_flanger,
    ),
    "chorus": EffectSpec(
        "chorus", "Chorus",
        [
            # Same master-output-gain trap as aecho above (verified: ffmpeg's
            # own defaults of 0.4/0.4 cut overall loudness by ~13dB).
            Param("in_gain", "Input gain", "float", 1.0, 0, 1, 0.05),
            Param("out_gain", "Output gain", "float", 1.0, 0, 1, 0.05),
            Param("delay_ms", "Delay", "float", 55.0, 20, 100, 1, unit="ms"),
            Param("decay", "Decay", "float", 0.4, 0, 1, 0.05),
            Param("speed_hz", "Speed", "float", 0.25, 0.1, 5, 0.05, unit="Hz"),
            Param("depth_ms", "Depth", "float", 2.0, 0, 10, 0.1, unit="ms"),
        ],
        _build_chorus,
    ),
    "gargle": EffectSpec(
        "gargle", "Gargle",
        [
            Param("frequency_hz", "Frequency", "float", 5.0, 0.1, 30, 0.1, unit="Hz"),
            Param("depth", "Depth", "float", 0.5, 0, 1, 0.05),
        ],
        _build_gargle,
        note="Amplitude-modulation approximation of DirectX Gargle (ffmpeg tremolo filter).",
    ),
    "reverb": EffectSpec(
        "reverb", "Reverb",
        [
            Param("room_size", "Room size", "float", 0.5, 0, 1, 0.05),
            Param("decay", "Decay", "float", 0.4, 0, 1, 0.05),
            Param("mix", "Wet/dry mix", "float", 0.3, 0, 1, 0.05),
        ],
        _build_reverb,
        note="Multi-tap echo approximation of reverb (ffmpeg ships no dedicated reverb filter).",
    ),
    "loudness": EffectSpec(
        "loudness", "Loudness Normalization",
        [
            Param("target_loudness", "Target loudness (RMS)", "float", 0.2, 0.0, 0.5, 0.01),
            Param("max_gain", "Max gain", "float", 15.0, 1.0, 50.0, 1.0),
            Param("compress", "Extra compression", "float", 0.0, 0.0, 30.0, 0.5),
        ],
        _build_loudness,
        note="Evens out loudness between stations so the same volume % sounds "
             "about the same everywhere (ffmpeg dynaudnorm — single-pass, safe "
             "for live streams; the alternative loudnorm filter needs a full "
             "first pass over the whole file, which a live stream doesn't have).",
    ),
}

# Order matters for how effects sound when chained: EQ/dynamics first, then
# distortion/colour effects, then modulation, with time-based echo/reverb,
# and loudness normalization LAST so it corrects the final output level
# regardless of what every effect before it did to the signal.
CHAIN_ORDER = ["equalizer", "compressor", "distortion", "chorus", "flanger", "gargle", "echo", "reverb", "loudness"]

DISPLAY_ORDER = ["chorus", "compressor", "distortion", "echo", "flanger", "gargle", "reverb", "equalizer", "loudness"]
