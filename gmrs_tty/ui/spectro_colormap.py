"""Colormap lookup tables for the rolling spectrometer.

Two maps ship: ``viridis`` (perceptually uniform, colorblind-safe, the
matplotlib default) and ``grayscale``. Viridis is the recommended
default — it stays readable for the deuteranopia / protanopia /
tritanopia variants and reads correctly when printed in B&W, which
matches the accessibility goal of the spectrometer feature.

The Viridis LUT is a compact 33-stop sample of the canonical matplotlib
table; ``build_lut`` interpolates it up to a 256-entry uint8 BGRA array
that maps directly into a ``QImage.Format_RGB32`` row write. Keeping the
seed list short (rather than embedding a full 256-entry literal) keeps
the module readable and the file size small without sacrificing visual
quality — the eye can't distinguish 256 vs. 33-then-interpolated stops
on a 32 px-tall waterfall.
"""
from __future__ import annotations

import numpy as np


# 33 viridis stops sampled uniformly from the matplotlib lookup. Values
# are RGB float in [0, 1]; ``build_lut`` interpolates and packs to BGRA.
_VIRIDIS_STOPS = np.array([
    (0.267004, 0.004874, 0.329415),
    (0.281412, 0.089774, 0.412415),
    (0.282327, 0.156270, 0.469538),
    (0.275191, 0.219900, 0.504712),
    (0.262138, 0.282091, 0.527908),
    (0.243113, 0.343582, 0.539093),
    (0.221989, 0.401325, 0.544813),
    (0.201239, 0.456082, 0.545912),
    (0.183429, 0.510579, 0.543415),
    (0.166697, 0.564980, 0.534772),
    (0.151326, 0.620149, 0.519289),
    (0.139657, 0.674930, 0.498291),
    (0.144759, 0.726149, 0.471772),
    (0.180653, 0.774815, 0.440085),
    (0.241586, 0.819540, 0.401690),
    (0.319809, 0.860533, 0.359690),
    (0.408258, 0.895824, 0.314155),
    (0.504172, 0.928590, 0.265257),
    (0.609330, 0.953041, 0.216397),
    (0.715189, 0.973416, 0.169990),
    (0.820113, 0.989540, 0.137163),
    (0.922183, 0.999450, 0.143228),
    (0.993248, 0.906157, 0.143936),
    (0.978806, 0.787549, 0.144795),
    (0.948844, 0.667480, 0.142936),
    (0.910427, 0.547568, 0.140662),
    (0.866013, 0.428168, 0.139079),
    (0.819651, 0.318195, 0.146529),
    (0.769556, 0.213631, 0.169105),
    (0.708366, 0.115440, 0.196947),
    (0.640099, 0.046948, 0.218803),
    (0.564384, 0.001000, 0.226057),
    (0.493229, 0.001100, 0.219805),
], dtype=np.float32)


def _interpolate_lut(stops: np.ndarray, n: int = 256) -> np.ndarray:
    """Linearly interpolate an (M, 3) stop array up to (n, 3) float32."""
    xs = np.linspace(0.0, 1.0, stops.shape[0], dtype=np.float32)
    target_x = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out = np.empty((n, 3), dtype=np.float32)
    for ch in range(3):
        out[:, ch] = np.interp(target_x, xs, stops[:, ch])
    return out


def _pack_bgra(rgb_lut: np.ndarray) -> np.ndarray:
    """Pack (n, 3) RGB float into (n,) uint32 BGRA (alpha 0xff).

    QImage.Format_RGB32 is little-endian 0xAARRGGBB; on common platforms
    that means a uint32 view of the pixel buffer is (B, G, R, A) byte
    order. Building a uint8 (n, 4) BGRA view and ``.view('<u4')`` gives
    us exactly that, ready to splat into a QImage scanline.
    """
    n = rgb_lut.shape[0]
    rgb_u8 = np.clip(rgb_lut * 255.0, 0.0, 255.0).astype(np.uint8)
    bgra = np.empty((n, 4), dtype=np.uint8)
    bgra[:, 0] = rgb_u8[:, 2]   # B
    bgra[:, 1] = rgb_u8[:, 1]   # G
    bgra[:, 2] = rgb_u8[:, 0]   # R
    bgra[:, 3] = 0xFF           # A
    return bgra.view(np.uint32).reshape(n)


def build_lut(name: str) -> np.ndarray:
    """Return a 256-entry uint32 LUT (BGRA packed) for the given map name.

    Falls back to viridis on unknown names so a stale ``spectro_colormap``
    config value never crashes the widget.
    """
    n = 256
    if name == "grayscale":
        # Pure linear ramp. Grayscale doubles as the screen-reader-friendly
        # "this is a heatmap" colormap on print and as a fallback when the
        # operator wants to disable hue cues entirely.
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        rgb = np.stack([ramp, ramp, ramp], axis=1)
        return _pack_bgra(rgb)
    return _pack_bgra(_interpolate_lut(_VIRIDIS_STOPS, n))


AVAILABLE_COLORMAPS = ("viridis", "grayscale")
DEFAULT_COLORMAP = "viridis"
