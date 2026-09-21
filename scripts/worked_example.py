"""Trace the 2x2 worked example through every stage of the framework."""

from __future__ import annotations

import numpy as np

from qwm.circuits import (
    WatermarkEmbeddingCircuit,
    WatermarkExtractionCircuit,
    WatermarkGenerationCircuit,
)
from qwm.metrics.quantum import block_metrics
from qwm.neqr import encode_decode_roundtrip, neqr_block_circuit
from qwm.watermark import block_trace


def main() -> None:
    block = np.array([[50, 60], [48, 32]])
    print("NEQR circuit of the block:", neqr_block_circuit(block).count_ops())
    print("NEQR round trip:", encode_decode_roundtrip(block).tolist())
    print("generation trace:", block_trace(block))
    gen = WatermarkGenerationCircuit(block)
    wb = gen.run()["watermark"]
    emb = WatermarkEmbeddingCircuit(block, wb)
    wblock = emb.run()["watermarked_block"]
    ext = WatermarkExtractionCircuit(wblock, wb)
    print("watermark:", wb, "| watermarked block:", wblock.tolist(), "| extracted:", ext.run()["extracted_bits"])
    print("quantum metrics (no noise):", block_metrics(block, wblock))
    print("quantum metrics (depolarizing p=0.05):", block_metrics(block, wblock, "depolarizing", 0.05))


if __name__ == "__main__":
    main()
