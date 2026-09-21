"""
qwm - NEQR-based quantum image watermarking with reversible quantum logic.

The package implements a simulation-level quantum watermarking framework:

* :mod:`qwm.neqr` - Novel Enhanced Quantum Representation of image blocks.
* :mod:`qwm.gates` - reversible arithmetic/logic modules (RPA, RPS, D4, QE)
  built as Qiskit circuits.
* :mod:`qwm.watermark` - watermark generation (PPB + AA), embedding and
  extraction, both as bit-exact classical reference code and as Qiskit
  circuits.
* :mod:`qwm.metrics` - image quality (MSE/PSNR/SSIM) and quantum-state
  (fidelity, trace distance, purity) metrics.
* :mod:`qwm.attacks` - image processing attacks used for robustness tests.
* :mod:`qwm.classifier` - AI-assisted attack classification (Random Forest).
* :mod:`qwm.resources` - quantum resource (qubit/gate/depth) analysis.
"""

from qwm.version import __version__

__all__ = ["__version__"]
