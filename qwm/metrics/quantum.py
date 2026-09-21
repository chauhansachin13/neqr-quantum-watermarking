"""
Quantum noise and decoherence metrics (Sec. 4.2, Eqs. 20-22).

* fidelity           ``F(rho, sigma) = (Tr sqrt(sqrt(rho) sigma sqrt(rho)))**2``
                     (``|<psi|phi>|**2`` for pure states)
* trace distance     ``T(rho, sigma) = 1/2 Tr |rho - sigma|``
* purity             ``P(rho) = Tr rho**2`` and the ratio ``Tr rho**2 / Tr sigma**2``

The metrics are evaluated on NEQR block states of the cover image ``|C>``
and of the watermarked image ``|W>``, optionally after passing them through a
noise channel (depolarising, amplitude damping, phase damping or bit flip)
that models decoherence.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from qiskit.quantum_info import DensityMatrix, Kraus, Statevector, state_fidelity  # noqa: F401

from qwm.neqr import iter_blocks, neqr_statevector

NOISE_MODELS = ("none", "depolarizing", "amplitude_damping", "phase_damping", "bit_flip")


def _eigh(matrix: np.ndarray):
    from scipy import linalg

    return linalg.eigh(matrix, driver="evd")


def _sqrtm_psd(matrix: np.ndarray) -> np.ndarray:
    """Matrix square root of a positive semi-definite Hermitian matrix (via ``eigh``)."""
    w, v = _eigh(matrix)
    w = np.clip(w, 0.0, None)
    return (v * np.sqrt(w)) @ v.conj().T


def fidelity(rho, sigma) -> float:
    """Uhlmann fidelity ``(Tr sqrt(sqrt(rho) sigma sqrt(rho)))**2`` (Eq. 20).

    Pure inputs (``Statevector``) use the closed forms ``|<psi|phi>|**2`` and
    ``<psi|sigma|psi>``; mixed inputs use a Hermitian eigendecomposition.
    """
    if isinstance(rho, Statevector) and isinstance(sigma, Statevector):
        return float(abs(np.vdot(rho.data, sigma.data)) ** 2)
    if isinstance(sigma, Statevector):
        rho, sigma = sigma, rho
    if isinstance(rho, Statevector):
        psi = np.asarray(rho.data)
        return float(np.real(np.vdot(psi, np.asarray(DensityMatrix(sigma).data) @ psi)))
    a = np.asarray(DensityMatrix(rho).data)
    b = np.asarray(DensityMatrix(sigma).data)
    sa = _sqrtm_psd(a)
    inner = sa @ b @ sa
    w = np.clip(np.linalg.eigvalsh((inner + inner.conj().T) / 2.0), 0.0, None)
    return float(np.sqrt(w).sum() ** 2)


def trace_distance(rho, sigma) -> float:
    if isinstance(rho, Statevector) and isinstance(sigma, Statevector):
        return float(np.sqrt(max(0.0, 1.0 - fidelity(rho, sigma))))
    a = np.asarray(DensityMatrix(rho).data)
    b = np.asarray(DensityMatrix(sigma).data)
    eig = np.linalg.eigvalsh(a - b)
    return float(0.5 * np.abs(eig).sum())


def purity(rho) -> float:
    if isinstance(rho, Statevector):
        return 1.0
    return float(np.real(DensityMatrix(rho).purity()))


def purity_ratio(rho, sigma) -> float:
    """Eq. 22: ``Tr rho**2 / Tr sigma**2``."""
    return purity(rho) / purity(sigma)


# --------------------------------------------------------------------------- #
# Noise channels
# --------------------------------------------------------------------------- #
def _single_qubit_kraus(model: str, p: float) -> list[np.ndarray]:
    i2 = np.eye(2)
    x = np.array([[0, 1], [1, 0]])
    y = np.array([[0, -1j], [1j, 0]])
    z = np.array([[1, 0], [0, -1]])
    if model == "depolarizing":
        return [np.sqrt(1 - 3 * p / 4) * i2, np.sqrt(p / 4) * x, np.sqrt(p / 4) * y, np.sqrt(p / 4) * z]
    if model == "amplitude_damping":
        return [np.array([[1, 0], [0, np.sqrt(1 - p)]]), np.array([[0, np.sqrt(p)], [0, 0]])]
    if model == "phase_damping":
        return [np.array([[1, 0], [0, np.sqrt(1 - p)]]), np.array([[0, 0], [0, np.sqrt(p)]])]
    if model == "bit_flip":
        return [np.sqrt(1 - p) * i2, np.sqrt(p) * x]
    raise ValueError(f"unknown noise model {model!r}; expected one of {NOISE_MODELS}")


def apply_noise(state, model: str = "depolarizing", p: float = 0.01) -> DensityMatrix:
    """Apply a single-qubit noise channel independently to every qubit."""
    rho = DensityMatrix(state)
    if model == "none" or p <= 0:
        return rho
    kraus = Kraus(_single_qubit_kraus(model, p))
    for q in range(rho.num_qubits):
        rho = rho.evolve(kraus, [q])
    return rho


# --------------------------------------------------------------------------- #
# Block / image level evaluation
# --------------------------------------------------------------------------- #
def block_states(cover_block, watermarked_block) -> tuple[Statevector, Statevector]:
    return neqr_statevector(cover_block), neqr_statevector(watermarked_block)


def block_metrics(cover_block, watermarked_block, noise: str = "none", p: float = 0.0) -> dict[str, float]:
    """Fidelity, trace distance and purity figures for one ``2x2`` block."""
    psi, phi = block_states(cover_block, watermarked_block)
    rho = psi if (noise == "none" or p <= 0) else apply_noise(psi, noise, p)
    sigma = phi if (noise == "none" or p <= 0) else apply_noise(phi, noise, p)
    return {
        "fidelity": fidelity(rho, sigma),
        "trace_distance": trace_distance(rho, sigma),
        "purity_cover": purity(rho),
        "purity_watermarked": purity(sigma),
        "purity_ratio": purity_ratio(rho, sigma),
        "fidelity_cover_noisy_vs_ideal": fidelity(psi, rho),
    }


def pure_block_fidelity(cover_block, watermarked_block) -> float:
    """Closed form for noiseless NEQR block states: ``(#unchanged pixels / 4)**2``."""
    a = np.asarray(cover_block).reshape(-1)
    b = np.asarray(watermarked_block).reshape(-1)
    return float((np.sum(a == b) / 4.0) ** 2)


def image_metrics(
    cover: np.ndarray,
    watermarked: np.ndarray,
    noise: str = "none",
    p: float = 0.0,
    max_blocks: int | None = 8,
    seed: int = 0,
) -> dict[str, float]:
    """Average block-level quantum metrics over (a random subset of) the image blocks.

    Without noise the fidelity is computed for every block in closed form; with
    noise the density-matrix evolution is restricted to ``max_blocks`` blocks.
    """
    blocks = list(iter_blocks(cover))
    wblocks = list(iter_blocks(watermarked))
    if noise == "none" or p <= 0:
        fids = np.array([pure_block_fidelity(b, w) for (_, b), (_, w) in zip(blocks, wblocks, strict=True)])
        # pure states: T = sqrt(1 - F), purity = 1
        return {
            "fidelity": float(fids.mean()),
            "trace_distance": float(np.sqrt(1.0 - fids).mean()),
            "purity_cover": 1.0,
            "purity_watermarked": 1.0,
            "purity_ratio": 1.0,
            "blocks_evaluated": len(fids),
        }
    rng = np.random.default_rng(seed)
    idx = np.arange(len(blocks))
    if max_blocks is not None and len(idx) > max_blocks:
        idx = rng.choice(idx, size=max_blocks, replace=False)
    rows = [block_metrics(blocks[i][1], wblocks[i][1], noise, p) for i in idx]
    keys = rows[0].keys()
    out = {k: float(np.mean([r[k] for r in rows])) for k in keys}
    out["blocks_evaluated"] = len(rows)
    return out


def sweep(cover, watermarked, noise: str, levels: Iterable[float], max_blocks: int = 8) -> list[dict]:
    """Evaluate :func:`image_metrics` for several noise strengths."""
    return [{"noise": noise, "p": float(p), **image_metrics(cover, watermarked, noise, p, max_blocks)} for p in levels]
