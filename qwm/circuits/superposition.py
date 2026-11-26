"""True NEQR quantum superposition circuits for pixel- and block-parallel operations.

Unlike block-classical execution where pixel intensities are loaded as fixed
computational basis states ``|p0>|p1>|p2>|p3>``, these circuits prepare and
process genuine NEQR coordinate superpositions:

.. math::
    |\\psi\\rangle = \\frac{1}{\\sqrt{HW}} \\sum_{y, x} |f(y, x)\\rangle |y, x\\rangle

* :func:`neqr_ppb_superposition_circuit` & :func:`run_neqr_ppb_superposition`:
  evaluates reversible PPB watermark generation coherently across all pixels of a
  ``2^h x 2^w`` grayscale image in a single quantum circuit, verified with exact
  :class:`qiskit.quantum_info.Statevector` simulation (13–17 qubits).
* :func:`neqr_tamper_oracle_circuit` & :func:`run_grover_tamper_search`:
  flags coordinates whose embedded two LSBs disagree with the pixel-level PPB
  check (blind) or a reference watermark, uncomputes scratch cleanly, and runs
  Grover amplitude amplification to concentrate probability onto tampered
  coordinates.
* :func:`block_neqr_superposition_circuit` & :func:`run_block_neqr_superposition`:
  prepares a uniform superposition over all ``B = 2^k`` ``2x2`` blocks of a patch
  (``44 + k`` qubits), evaluates full 8-bit 2x2 block watermark generation
  simultaneously across every block branch, and verifies every block outcome
  via Matrix Product State (``AerSimulator(method="matrix_product_state")``).
* :func:`block_neqr_blind_verify`: prepares a block-superposition NEQR state for a
  keyed watermarked patch, evaluates the MSB content code + block-indexed Toeplitz
  MAC in superposition, and verifies every tampered/authentic block simultaneously.
"""

from __future__ import annotations

import math

import numpy as np
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister, transpile
from qiskit.circuit.library import MCXGate
from qiskit.quantum_info import Statevector
from qiskit_aer import AerSimulator

from qwm.circuits.lean import LeanBlockRegisters, append_lean_generation, append_lean_ppb
from qwm.circuits.secure import msb_message_qubits
from qwm.neqr import neqr_circuit
from qwm.secure.authentication import SecureWatermark
from qwm.watermark.generation import block_pixels, block_watermark_bits, pixel_position_bits

__all__ = [
    "neqr_ppb_superposition_circuit",
    "run_neqr_ppb_superposition",
    "neqr_tamper_oracle_circuit",
    "run_grover_tamper_search",
    "block_neqr_superposition_circuit",
    "run_block_neqr_superposition",
    "block_neqr_blind_verify",
]


def _check_pow2_2d(image: np.ndarray) -> tuple[np.ndarray, int, int]:
    arr = np.asarray(image, dtype=np.uint8)
    if arr.ndim != 2:
        raise ValueError("expected a 2D grayscale image")
    h, w = arr.shape
    if h < 2 or w < 2 or (h & (h - 1)) != 0 or (w & (w - 1)) != 0:
        raise ValueError(f"dimensions must be powers of 2 >= 2, got {arr.shape}")
    return arr, h, w


def _apply_ref_lsb(
    qc: QuantumCircuit,
    coord: list,
    ref_reg: QuantumRegister,
    ref_lsb: np.ndarray,
) -> None:
    """Load 2-bit expected LSB per coordinate conditionally into ``ref_reg``."""
    h, w = ref_lsb.shape[:2]
    n_coord = len(coord)
    for y in range(h):
        for x in range(w):
            b0, b1 = int(ref_lsb[y, x, 0]), int(ref_lsb[y, x, 1])
            if not (b0 or b1):
                continue
            ctrl_bits = f"{y * w + x:0{n_coord}b}"
            if b0:
                qc.mcx(coord, ref_reg[0], ctrl_state=ctrl_bits)
            if b1:
                qc.mcx(coord, ref_reg[1], ctrl_state=ctrl_bits)


def neqr_ppb_superposition_circuit(image: np.ndarray, masked: bool = False) -> QuantumCircuit:
    """Coherent NEQR superposition evaluating ``PPB(f(y, x))`` over all coordinates."""
    arr, _, _ = _check_pow2_2d(image)
    base = neqr_circuit(arr)
    ppb = QuantumRegister(2, "ppb")
    cin = QuantumRegister(1, "cin")
    qc = QuantumCircuit(*base.qregs, ppb, cin, name="NEQRSuperpositionPPB")
    pix_q = list(base.qregs[0])
    coord_q = list(base.qregs[1])
    qc.compose(base, pix_q + coord_q, inplace=True)
    append_lean_ppb(qc, pix_q, ppb[0], ppb[1], cin[0], masked=masked, relative_phase=True)
    return qc


def run_neqr_ppb_superposition(image: np.ndarray, masked: bool = False) -> dict:
    """Exact statevector simulation of :func:`neqr_ppb_superposition_circuit`."""
    arr, h, w = _check_pow2_2d(image)
    qc = neqr_ppb_superposition_circuit(arr, masked=masked)
    sv = Statevector.from_instruction(qc)

    n_coord = int(math.log2(h * w))
    # Layout: 0..7 intensity, 8..8+n_coord-1 idx, 8+n_coord..+1 ppb, last cin
    anc_idx = [8 + n_coord + 2]
    anc_probs = sv.probabilities_dict(qargs=anc_idx)
    ancilla_clean_prob = float(anc_probs.get("0", 0.0))

    coord_ppb_qargs = list(range(8, 8 + n_coord + 2))
    probs = sv.probabilities_dict(qargs=coord_ppb_qargs)

    decoded_ppb = np.zeros((h, w, 2), dtype=np.uint8)
    expected_ppb = np.zeros((h, w, 2), dtype=np.uint8)
    coord_prob_map = np.zeros((h, w), dtype=np.float64)

    for idx in range(h * w):
        y, x = divmod(idx, w)
        val = int(arr[y, x] & 0xFC) if masked else int(arr[y, x])
        expected_ppb[y, x] = pixel_position_bits(val)

    for bs, p in probs.items():
        if p < 1e-12:
            continue
        # Qiskit bitstring ordering is MSB->LSB, so [:2] is ppb[1], ppb[0]; [2:] is coord
        ppb1, ppb0 = int(bs[0]), int(bs[1])
        idx = int(bs[2:], 2)
        y, x = divmod(idx, w)
        coord_prob_map[y, x] += float(p)
        if p >= 0.5 / (h * w):
            decoded_ppb[y, x, 0] = ppb0
            decoded_ppb[y, x, 1] = ppb1

    exact_match = bool(np.array_equal(decoded_ppb, expected_ppb))
    uniform_prob = 1.0 / (h * w)
    uniform = bool(np.allclose(coord_prob_map, uniform_prob, atol=1e-9))
    return {
        "shape": (h, w),
        "qubits": qc.num_qubits,
        "depth": qc.depth(),
        "ancilla_clean_prob": ancilla_clean_prob,
        "uniform": uniform,
        "exact_match": exact_match,
        "decoded_ppb": decoded_ppb,
        "expected_ppb": expected_ppb,
        "coord_probabilities": coord_prob_map,
    }


def neqr_tamper_oracle_circuit(
    image: np.ndarray,
    reference_lsb: np.ndarray | None = None,
    grover_iterations: int = 1,
) -> QuantumCircuit:
    """NEQR coordinate superposition + Grover tamper-search amplification circuit."""
    arr, h, w = _check_pow2_2d(image)
    if reference_lsb is not None:
        ref = np.asarray(reference_lsb, dtype=np.uint8)
        if ref.shape != (h, w, 2):
            raise ValueError(f"reference_lsb must have shape {(h, w, 2)}")
    else:
        ref = None

    base = neqr_circuit(arr)
    ppb = QuantumRegister(2, "ppb")
    cin = QuantumRegister(1, "cin")
    qc = QuantumCircuit(*base.qregs, ppb, cin, name="NEQRGroverTamper")
    pix_q = list(base.qregs[0])
    coord_q = list(base.qregs[1])
    qc.compose(base, pix_q + coord_q, inplace=True)

    # Oracle O marks coordinate basis states whose LSB != expected/PPB via phase kickback (-1)
    oracle = QuantumCircuit(*qc.qregs)
    if ref is None:
        append_lean_ppb(oracle, pix_q, ppb[0], ppb[1], cin[0], masked=True, relative_phase=True)
    else:
        _apply_ref_lsb(oracle, coord_q, ppb, ref)
    oracle.cx(pix_q[0], ppb[0])
    oracle.cx(pix_q[1], ppb[1])
    oracle.x(ppb[0])
    oracle.x(ppb[1])
    oracle.cz(ppb[0], ppb[1])
    oracle.x(ppb[0])
    oracle.x(ppb[1])
    oracle.cx(pix_q[1], ppb[1])
    oracle.cx(pix_q[0], ppb[0])
    if ref is None:
        ppb_inv = QuantumCircuit(*qc.qregs)
        append_lean_ppb(ppb_inv, pix_q, ppb[0], ppb[1], cin[0], masked=True, relative_phase=True)
        oracle.compose(ppb_inv.inverse(), inplace=True)
    else:
        _apply_ref_lsb(oracle, coord_q, ppb, ref)

    # Diffuser: A * S_0(coord) * A^dagger uncomputes NEQR before reflecting around |0..0>
    diffuser = QuantumCircuit(*qc.qregs)
    diffuser.compose(base.inverse(), pix_q + coord_q, inplace=True)
    diffuser.x(coord_q)
    if len(coord_q) == 1:
        diffuser.z(coord_q[0])
    else:
        diffuser.h(coord_q[-1])
        diffuser.mcx(coord_q[:-1], coord_q[-1])
        diffuser.h(coord_q[-1])
    diffuser.x(coord_q)
    diffuser.compose(base, pix_q + coord_q, inplace=True)

    for _ in range(int(grover_iterations)):
        qc.compose(oracle, inplace=True)
        qc.compose(diffuser, inplace=True)

    return qc


def _classical_tamper_mask(arr: np.ndarray, ref: np.ndarray | None) -> np.ndarray:
    h, w = arr.shape
    mask = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            lsb0 = int(arr[y, x]) & 1
            lsb1 = (int(arr[y, x]) >> 1) & 1
            if ref is None:
                e0, e1 = pixel_position_bits(int(arr[y, x]) & 0xFC)
            else:
                e0, e1 = int(ref[y, x, 0]), int(ref[y, x, 1])
            mask[y, x] = (lsb0 != e0) or (lsb1 != e1)
    return mask


def run_grover_tamper_search(
    image: np.ndarray,
    reference_lsb: np.ndarray | None = None,
    iterations: int | None = None,
    threshold_multiplier: float = 2.0,
) -> dict:
    """Run exact statevector Grover tamper localization on a ``2^h x 2^w`` patch."""
    arr, h, w = _check_pow2_2d(image)
    n_pixels = h * w
    n_coord = int(math.log2(n_pixels))
    expected_mask = _classical_tamper_mask(arr, reference_lsb)
    n_marked = int(expected_mask.sum())

    if iterations is None:
        if 0 < n_marked < n_pixels:
            iterations = max(1, int(math.floor(math.pi / 4.0 * math.sqrt(n_pixels / n_marked))))
        else:
            iterations = max(1, int(math.floor(math.pi / 4.0 * math.sqrt(n_pixels))))

    qc = neqr_tamper_oracle_circuit(arr, reference_lsb=reference_lsb, grover_iterations=iterations)
    sv = Statevector.from_instruction(qc)
    coord_probs_dict = sv.probabilities_dict(qargs=list(range(8, 8 + n_coord)))
    anc_probs = sv.probabilities_dict(qargs=list(range(8 + n_coord, 8 + n_coord + 3)))

    prob_map = np.zeros((h, w), dtype=np.float64)
    for bs, p in coord_probs_dict.items():
        idx = int(bs, 2)
        y, x = divmod(idx, w)
        prob_map[y, x] = float(p)

    uniform = 1.0 / n_pixels
    flagged = prob_map > threshold_multiplier * uniform
    flagged_coords = [(int(r), int(c)) for r, c in np.argwhere(flagged)]
    tampered_mass = float(prob_map[expected_mask].sum()) if n_marked else 0.0
    max_prob = float(prob_map.max())
    return {
        "shape": (h, w),
        "qubits": qc.num_qubits,
        "iterations": int(iterations),
        "n_marked_true": n_marked,
        "expected_tamper_mask": expected_mask,
        "coord_probabilities": prob_map,
        "flagged_mask": flagged,
        "flagged_coords": flagged_coords,
        "tampered_probability_mass": tampered_mass,
        "amplification_gain": float(max_prob / uniform),
        "ancilla_clean_prob": float(anc_probs.get("000", 0.0)),
        "exact_match": bool(np.array_equal(flagged, expected_mask)),
    }


def _extract_blocks_pow2(image: np.ndarray) -> tuple[np.ndarray, list[np.ndarray], int, int]:
    arr, h, w = _check_pow2_2d(image)
    hb, wb = h // 2, w // 2
    n_blocks = hb * wb
    if n_blocks < 2 or (n_blocks & (n_blocks - 1)) != 0:
        raise ValueError(f"number of 2x2 blocks must be power of 2 >= 2, got {n_blocks}")
    k = int(math.log2(n_blocks))
    blocks = [arr[2 * br : 2 * br + 2, 2 * bc : 2 * bc + 2] for br in range(hb) for bc in range(wb)]
    return arr, blocks, k, hb


def block_neqr_superposition_circuit(
    image: np.ndarray,
    masked: bool = False,
) -> tuple[QuantumCircuit, QuantumRegister, LeanBlockRegisters]:
    """Prepare ``1/sqrt(B) sum_b |b>|P0..P3>_b`` and run one shared ``append_lean_generation``."""
    _, blocks, k, _ = _extract_blocks_pow2(image)
    lay = LeanBlockRegisters()
    addr = QuantumRegister(k, "addr")
    regs = [addr, *lay.pixels, lay.out, lay.anc]
    qc = QuantumCircuit(*regs, name="BlockNEQRSuperposition")
    qc.h(addr)

    for b_idx, blk in enumerate(blocks):
        ctrl_bits = f"{b_idx:0{k}b}"
        for reg, val in zip(lay.pixels, block_pixels(blk), strict=True):
            for bit in range(8):
                if (int(val) >> bit) & 1:
                    qc.mcx(list(addr), reg[bit], ctrl_state=ctrl_bits)

    append_lean_generation(qc, lay, masked=masked, relative_phase=True)
    return qc, addr, lay


def run_block_neqr_superposition(
    image: np.ndarray,
    masked: bool = False,
    shots: int = 1024,
    seed: int = 7,
) -> dict:
    """Simulate full 8-bit multi-block NEQR superposition via Aer MPS simulator."""
    arr, blocks, k, _ = _extract_blocks_pow2(image)
    qc, addr, lay = block_neqr_superposition_circuit(arr, masked=masked)

    meas_qubits = list(addr) + [q for r in lay.pixels for q in r] + list(lay.out) + list(lay.anc)
    cr = ClassicalRegister(len(meas_qubits), "m")
    qc_m = qc.copy()
    qc_m.add_register(cr)
    qc_m.measure(meas_qubits, list(cr))

    sim = AerSimulator(method="matrix_product_state")
    tqc = transpile(qc_m, sim, optimization_level=1, seed_transpiler=seed)
    counts = sim.run(tqc, shots=shots, seed_simulator=seed).result().get_counts()

    seen_blocks: set[int] = set()
    correct_shots = 0
    for bs, cnt in counts.items():
        bits = [int(ch) for ch in bs[::-1]]
        b_idx = sum(bits[i] << i for i in range(k))
        seen_blocks.add(b_idx)
        pix_offset = k
        pix = [sum(bits[pix_offset + 8 * p + j] << j for j in range(8)) for p in range(4)]
        wm_offset = pix_offset + 32
        wm = bits[wm_offset : wm_offset + 8]
        anc = bits[wm_offset + 8 :]
        exp_pix = block_pixels(blocks[b_idx])
        exp_img = blocks[b_idx] & 0xFC if masked else blocks[b_idx]
        exp_wm = block_watermark_bits(exp_img)
        if pix == exp_pix and wm == exp_wm and all(a == 0 for a in anc):
            correct_shots += cnt

    return {
        "shape": tuple(arr.shape),
        "n_blocks": len(blocks),
        "qubits": qc.num_qubits,
        "shots": int(shots),
        "blocks_sampled": len(seen_blocks),
        "all_blocks_seen": len(seen_blocks) == len(blocks),
        "correct_shots": int(correct_shots),
        "accuracy": float(correct_shots / shots),
    }


def block_neqr_blind_verify(
    image: np.ndarray,
    key,
    nonce: bytes | str = b"",
    shots: int = 1024,
    seed: int = 7,
) -> dict:
    """Superposition blind verification of a keyed-watermarked patch via Aer MPS."""
    arr, blocks, k, hb = _extract_blocks_pow2(image)
    wb = arr.shape[1] // 2
    sw = SecureWatermark(key, nonce)
    mac = sw.mac(arr.shape)
    classical = sw.verify(arr)

    lay = LeanBlockRegisters()
    addr = QuantumRegister(k, "addr")
    flag = QuantumRegister(1, "flag")
    qc = QuantumCircuit(addr, *lay.pixels, lay.out, lay.anc, flag, name="BlockNEQRBlindVerify")
    qc.h(addr)

    for b_idx, blk in enumerate(blocks):
        ctrl_bits = f"{b_idx:0{k}b}"
        for reg, val in zip(lay.pixels, block_pixels(blk), strict=True):
            for bit in range(8):
                if (int(val) >> bit) & 1:
                    qc.mcx(list(addr), reg[bit], ctrl_state=ctrl_bits)

    append_lean_generation(qc, lay, masked=True, relative_phase=True)
    msg_q = msb_message_qubits(lay.pixels)
    for b_idx in range(len(blocks)):
        ctrl_bits = f"{b_idx:0{k}b}"
        mat = mac.matrix(b_idx)
        mask = mac.mask(b_idx)
        for i, o in enumerate(lay.out):
            for j, m in enumerate(msg_q):
                if mat[i, j]:
                    qc.mcx([*list(addr), m], o, ctrl_state="1" + ctrl_bits)
            if mask[i]:
                qc.mcx(list(addr), o, ctrl_state=ctrl_bits)

    for i in range(4):
        qc.cx(lay.pixels[i][0], lay.out[2 * i])
        qc.cx(lay.pixels[i][1], lay.out[2 * i + 1])
    qc.append(MCXGate(8, ctrl_state=0), list(lay.out) + [flag[0]])

    meas_qubits = list(addr) + [flag[0]] + list(lay.anc)
    cr = ClassicalRegister(len(meas_qubits), "m")
    qc.add_register(cr)
    qc.measure(meas_qubits, list(cr))

    sim = AerSimulator(method="matrix_product_state")
    tqc = transpile(qc, sim, optimization_level=1, seed_transpiler=seed)
    counts = sim.run(tqc, shots=shots, seed_simulator=seed).result().get_counts()

    block_authentic = np.zeros((hb, wb), dtype=bool)
    block_counts = np.zeros((hb, wb), dtype=int)
    clean_shots = 0
    correct_shots = 0
    tamper_grid = classical.tamper_map
    for bs, cnt in counts.items():
        bits = [int(ch) for ch in bs[::-1]]
        b_idx = sum(bits[i] << i for i in range(k))
        fl = bool(bits[k])
        anc_ok = all(a == 0 for a in bits[k + 1 :])
        br, bc = divmod(b_idx, wb)
        exp_auth = bool(not tamper_grid[br, bc])
        block_counts[br, bc] += cnt
        if fl:
            block_authentic[br, bc] = True
        if anc_ok:
            clean_shots += cnt
        if anc_ok and fl == exp_auth:
            correct_shots += cnt

    tamper_map_q = ~block_authentic
    return {
        "shape": tuple(arr.shape),
        "n_blocks": len(blocks),
        "qubits": qc.num_qubits,
        "shots": int(shots),
        "accuracy": float(correct_shots / shots),
        "ancilla_clean_rate": float(clean_shots / shots),
        "tamper_blocks_quantum": tamper_map_q,
        "tamper_blocks_classical": tamper_grid,
        "matches_classical": bool(np.array_equal(tamper_map_q, tamper_grid)),
        "block_shot_counts": block_counts,
    }
