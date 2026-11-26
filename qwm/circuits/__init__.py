"""Block-level and superposition Qiskit circuits for NEQR watermarking."""

from qwm.circuits.embedding import WatermarkEmbeddingCircuit
from qwm.circuits.extraction import WatermarkExtractionCircuit
from qwm.circuits.generation import WatermarkGenerationCircuit
from qwm.circuits.shallow import (
    ShallowBlindVerificationCircuit,
    ShallowGenerationCircuit,
    ShallowKeyedEmbeddingCircuit,
    cla_adder,
)
from qwm.circuits.superposition import (
    block_neqr_blind_verify,
    block_neqr_superposition_circuit,
    neqr_ppb_superposition_circuit,
    neqr_tamper_oracle_circuit,
    run_block_neqr_superposition,
    run_grover_tamper_search,
    run_neqr_ppb_superposition,
)

__all__ = [
    "WatermarkGenerationCircuit",
    "WatermarkEmbeddingCircuit",
    "WatermarkExtractionCircuit",
    "ShallowGenerationCircuit",
    "ShallowKeyedEmbeddingCircuit",
    "ShallowBlindVerificationCircuit",
    "cla_adder",
    "neqr_ppb_superposition_circuit",
    "run_neqr_ppb_superposition",
    "neqr_tamper_oracle_circuit",
    "run_grover_tamper_search",
    "block_neqr_superposition_circuit",
    "run_block_neqr_superposition",
    "block_neqr_blind_verify",
]
