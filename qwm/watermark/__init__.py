"""Watermark generation, embedding and extraction (classical reference code)."""

from qwm.watermark.embedding import (
    MODES,
    embed_block,
    embed_image,
    embed_pixel,
    embed_pixel_trace,
    payload_capacity,
)
from qwm.watermark.extraction import (
    bit_error_rate,
    extract_block,
    extract_image,
    extract_pixel_trace,
    normalized_correlation,
    tamper_map,
)
from qwm.watermark.generation import (
    arithmetic_average,
    block_trace,
    block_watermark_bits,
    generate_watermark,
    pixel_position_bits,
    watermark_to_image,
)

__all__ = [
    "MODES",
    "arithmetic_average",
    "bit_error_rate",
    "block_trace",
    "block_watermark_bits",
    "embed_block",
    "embed_image",
    "embed_pixel",
    "embed_pixel_trace",
    "extract_block",
    "extract_image",
    "extract_pixel_trace",
    "generate_watermark",
    "normalized_correlation",
    "payload_capacity",
    "pixel_position_bits",
    "tamper_map",
    "watermark_to_image",
]
