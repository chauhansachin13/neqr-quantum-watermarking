"""Reversible quantum logic modules used by the watermarking framework."""

from qwm.gates.adder import (
    ReverseParallelAdder,
    RPALayout,
    reversible_full_adder,
    reversible_half_adder,
    rpa_gate,
)
from qwm.gates.divider import DividingFour, d4_gate
from qwm.gates.equal import QuantumEqual, qe_gate
from qwm.gates.subtractor import (
    ReverseParallelSubtractor,
    reversible_full_subtractor,
    reversible_half_subtractor,
    rps_gate,
)

__all__ = [
    "ReverseParallelAdder",
    "ReverseParallelSubtractor",
    "DividingFour",
    "QuantumEqual",
    "RPALayout",
    "reversible_half_adder",
    "reversible_full_adder",
    "reversible_half_subtractor",
    "reversible_full_subtractor",
    "rpa_gate",
    "rps_gate",
    "d4_gate",
    "qe_gate",
]
