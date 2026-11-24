# Changelog

## 2.0.0

Extends the reproduction with the reference design's own future-work items.
Details and derivations are in [docs/IMPROVEMENTS.md](docs/IMPROVEMENTS.md).

### Added
- **Keyed blind authentication** (`qwm.secure.SecureWatermark`). The tag is
  the base content code of the MSB plane XOR a one-time Toeplitz MAC (keyed by
  SHAKE-256), embedded in the two LSBs. Verification needs only the key and
  nonce. Untouched blocks never fail; a forged block passes with probability
  2^-8. Grayscale and colour images are supported.
- **Self-recovery** (`qwm.secure.SelfRecoveringWatermark`). 4×4 blocks carry
  20 recovery bits for a keyed partner block (the 5-bit RPA + D4 averages) and
  a 12-bit MAC. Failed blocks are rebuilt by sub-block interpolation, with an
  inpainting fallback.
- **Lean circuits** (`qwm.circuits.lean`). The block circuits now need 44 / 40 /
  41 qubits instead of 354 / 400 / 400. They use Cuccaro adders, pixel position
  bits from half an adder, rounding as a carry-in, D4 as a relabelling of
  wires, Bennett uncomputation and relative-phase Toffolis (unitary
  equivalence is tested).
- **Keyed circuits** (`qwm.circuits.secure`): 44-qubit embedding and 45-qubit
  blind verification, checked against the classical scheme.
- **NISQ study** (`qwm nisq`, `qwm.nisq`): compilation to all-to-all and
  heavy-hex connectivity, depolarising noise, Qiskit Aer matrix-product-state
  simulation, and error thresholds.
- **Tamper study** (`qwm tamper-study`, `qwm.tamper`): seven local
  manipulations, including an LSB-preserving splice and a re-embedding
  forgery; block-level TPR / FPR / F1 / IoU; recovery PSNR; wrong-key pass
  rates.
- **Classifier benchmark** (`qwm classifier-benchmark`): cover-disjoint split,
  six baselines with exact McNemar tests, open-set detection of eight unseen
  attacks, and named descriptor importances.
- **Consistency checks** (`qwm paper-checks`): Fuchs–van de Graaf check of
  Table 9 (6 of 16 rows fail) and PSNR bounds at 2 bpp.
- **Interactive web demo** (`qwm serve`): standard-library HTTP server plus a
  single-page app covering embed, attack (paint / local / global), verify and
  repair, identify the attack, and per-block circuits.
- CLI commands `verify`, `tamper-study`, `nisq`, `classifier-benchmark`,
  `paper-checks` and `serve`; `embed --mode keyed|recovery`.
- Tests for every new module and the web endpoints, and new CI smoke steps.

### Changed
- `build_dataset` now records which cover image each sample came from
  (`AttackDataset.groups`). Its random stream is unchanged, so v1 results
  reproduce bit for bit.
- The basis-state simulator and resource counter understand `rccx`.

## 1.0.0

- Reproduction of the reference design: NEQR, the RPA/RPS/D4/QE modules,
  watermark generation, embedding and extraction (classical and Qiskit),
  image and quantum-state metrics, eight attacks, the Random Forest attack
  classifier, resource analysis, CLI, tests and CI.
