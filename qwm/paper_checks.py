"""
Consistency checks of figures reported in the reference design.

Two kinds of reported numbers can be checked without re-running anything:

1. **Table 9 (fidelity / trace distance / purity).**  For any two quantum
   states the Fuchs-van de Graaf inequalities hold::

       1 - sqrt(F)  <=  T  <=  sqrt(1 - F)

   with ``F`` the (squared) fidelity of Eq. (20) and ``T`` the trace distance
   of Eq. (21).  In particular ``F = 1`` forces ``T = 0`` and ``T = 0`` forces
   ``F = 1``.  :func:`check_table9` tests every row, allowing for the rounding
   of the printed four-decimal values.
2. **PSNR at 2 bits per pixel (Tables 5 / 12).**  Hiding 8 verifiable bits in
   every 2x2 block means the receiver's check passes for only one in
   ``2**8`` candidate blocks, so the embedder must move each block to the
   nearest passing one.  The classic bounds of quantisation-index modulation
   give the smallest possible mean squared error (:func:`psnr_bounds_2bpp`):
   plain LSB replacement ``2.5`` (44.15 dB), optimal pixel adjustment ``1.5``
   (46.37 dB), the best 4-D lattice (D4) ``1.23`` (47.25 dB) and the
   sphere-packing limit ``2**(2R) / (2 pi e) = 0.94`` (48.4 dB, achievable only
   with infinitely long codes).  The reported 59.97 dB needs an MSE of 0.066,
   about 14 times below that limit.
"""

from __future__ import annotations

import math

# Table 9 of the reference design: (image, fidelity F, trace distance T, purity P)
TABLE9 = (
    ("Lena", 0.9999, 0.0, 1.0233),
    ("Baboon", 1.0, 0.0, 1.0),
    ("Peppers", 0.5231, 0.4880, 0.8842),
    ("Einstein", 1.0, 0.0, 1.0),
    ("Bird", 0.9890, 0.7390, 1.0),
    ("Flower", 0.9888, 0.1020, 0.9892),
    ("Man", 0.5142, 0.0, 0.7830),
    ("Moon", 1.0, 0.0, 1.0),
    ("Baby", 0.3498, 0.4562, 0.9990),
    ("Boat", 0.9990, 0.0991, 0.9992),
    ("Airplane", 1.0, 0.0, 1.0),
    ("House1", 1.0, 0.4378, 1.3202),
    ("Barbara", 1.0, 0.0, 1.0),
    ("House2", 0.9892, 0.0, 1.0),
    ("Aerial", 0.5230, 1.0, 1.0),
    ("Clown", 1.0, 0.0, 1.0),
)

#: half a unit in the last printed decimal place
ROUNDING = 5e-5


def fuchs_van_de_graaf_bounds(fidelity: float) -> tuple[float, float]:
    """``(1 - sqrt(F), sqrt(1 - F))`` - the admissible range of the trace distance."""
    f = min(1.0, max(0.0, fidelity))
    return 1.0 - math.sqrt(f), math.sqrt(1.0 - f)


def consistent(fidelity: float, trace_distance: float, tol: float = ROUNDING) -> bool:
    """True if some ``F'``, ``T'`` within ``tol`` of the printed values satisfy the bounds."""
    f_lo, f_hi = max(0.0, fidelity - tol), min(1.0, fidelity + tol)
    t_lo, t_hi = max(0.0, trace_distance - tol), min(1.0, trace_distance + tol)
    lower_min = 1.0 - math.sqrt(f_hi)  # smallest admissible lower bound
    upper_max = math.sqrt(1.0 - f_lo)  # largest admissible upper bound
    return t_hi >= lower_min and t_lo <= upper_max


def check_table9(rows=TABLE9, tol: float = ROUNDING) -> list[dict]:
    out = []
    for image, f, t, p in rows:
        lo, hi = fuchs_van_de_graaf_bounds(f)
        ok = consistent(f, t, tol)
        reason = ""
        if not ok:
            reason = f"T = {t:g} outside [{lo:.4f}, {hi:.4f}]"
            if f >= 1.0 - tol:
                reason += " (F = 1 implies identical states, hence T = 0)"
            elif t <= tol:
                reason += " (T = 0 implies identical states, hence F = 1)"
            elif t >= 1.0 - tol:
                reason += " (T = 1 implies orthogonal states, hence F = 0)"
        out.append({"image": image, "fidelity": f, "trace_distance": t, "purity": p, "t_min": lo, "t_max": hi, "consistent": ok, "reason": reason})
    return out


# --------------------------------------------------------------------------- #
# PSNR bounds for 2 bits per pixel
# --------------------------------------------------------------------------- #
def mse_to_psnr(mse: float, peak: float = 255.0) -> float:
    return float("inf") if mse <= 0 else 10.0 * math.log10(peak**2 / mse)


def psnr_to_mse(psnr_db: float, peak: float = 255.0) -> float:
    return peak**2 / (10 ** (psnr_db / 10.0))


def psnr_bounds_2bpp(bits_per_pixel: float = 2.0) -> list[dict]:
    """Smallest mean squared error (largest PSNR) for embedding ``R`` checkable bits per pixel."""
    r = bits_per_pixel
    cell = 2.0**r  # residue classes per pixel (coset spacing of the embedding lattice)
    lsb = 2.0 * (cell**2 - 1) / 12.0  # replace the R LSBs: E[(w - l)^2] with w, l uniform
    # optimal pixel adjustment: nearest value with the required residue -> errors uniform on a cell
    half = int(cell // 2)
    errs = range(-half + 1, half + 1)
    opap = sum(e * e for e in errs) / cell
    d4 = 0.076603 * (cell**4) ** (2.0 / 4)  # normalised second moment of D4 times V^(2/n), V = cell^4
    shannon = cell**2 / (2 * math.pi * math.e)
    rows = [
        {"method": f"{int(r)}-LSB replacement (this implementation)", "mse": lsb},
        {"method": "optimal pixel adjustment (nearest pixel with the right LSBs)", "mse": opap},
        {"method": "best 4-D lattice code (D4)", "mse": d4},
        {"method": "sphere-packing limit 2^(2R)/(2*pi*e)", "mse": shannon},
        {"method": "reported in the reference design (Man image)", "mse": psnr_to_mse(59.97)},
    ]
    for row in rows:
        row["psnr_db"] = mse_to_psnr(row["mse"])
    return rows
