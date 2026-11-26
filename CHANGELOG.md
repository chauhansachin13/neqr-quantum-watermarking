# Changelog

## 3.0.1

Paper-fidelity, workflow simplicity, and Bento UI polish:
- **Unitary inverse & paper completeness**: `WatermarkEmbeddingCircuit.verify_unitary_inverse()` verifies `U† |W> = |C> ⊗ |Wb>` (Eqs. 12–16), `measure_all_families()` compares Table 21 `v1` against `v2 Lean`/`Keyed` and `v3 Shallow CLA` circuits (`qwm resources`), `qwm.data` supports paper image aliases (`House1`, `Flower`, etc.) plus native-size RGB preservation, and `notebooks/walkthrough.ipynb` adds v2/v3 sections.
- **Simple CLI & offline pipeline**: added `qwm run` (one-command 4-part walkthrough), `qwm ui` alias for `qwm serve`, `--mode lsb/opap --reference` in `qwm verify`, RGB + native-resolution support on local files in `qwm embed`, and `OFFLINE=1` mode in `scripts/reproduce_all.sh`.
- **Dashboard (`qwm ui`)**: compact 2-column scheme selector, viewport-anchored 1-Click `Run Full Demo`, and a dedicated `Paper Tables` view (`GET /api/paper`) displaying Table 21 vs v2/v3, 2-bpp PSNR limits, Table 9 consistency, and FRQI vs NEQR Table 11.
- **Security, SDLC & Release (`3.0.1`)**: hardened HTTP `POST` `Content-Length`/JSON-object validation and HTTPS-only dataset downloads, added `GET /api/health` readiness endpoint, containerized deployment (`Dockerfile` / `.dockerignore`), CI security + coverage + wheel checks, and governance docs (`docs/SDLC.md`, `SECURITY.md`, `CONTRIBUTING.md`).

## 3.0.0

Addresses the remaining classical-simulation and NISQ depth limitations beyond
v2 while remaining 100% backward-compatible with v1 and v2 APIs.

### Added
- **True NEQR superposition & Grover tamper search**
  (`qwm.circuits.superposition`, `qwm superposition`):
  - `neqr_ppb_superposition_circuit` / `run_neqr_ppb_superposition`: coherent
    coordinate superposition over all pixels of a `2^h x 2^w` image verified
    with exact `Statevector` simulation (13–17 qubits, clean ancilla probability
    1.000000).
  - `neqr_tamper_oracle_circuit` / `run_grover_tamper_search`: blind PPB and
    reference tamper phase oracle + Grover amplitude amplification on NEQR
    coordinate registers (locates a single tampered pixel in a 4×4 patch in
    3 iterations with `0.9613` probability mass / `15.38×` gain).
  - `block_neqr_superposition_circuit`, `run_block_neqr_superposition`, and
    `block_neqr_blind_verify`: uniform multi-block NEQR superposition (`46–47`
    qubits) verified across all blocks simultaneously via Aer MPS (`1.0000`
    shot accuracy matching classical verification).
- **Log-depth Carry-Lookahead (Brent-Kung CLA) circuits** (`qwm.circuits.shallow`):
  - `cla_adder` / `append_cla` (`O(log n)` carry tree, proved unitary-equivalent
    with `Operator` for `n=1..3`, superposition phase exact for `n=4`, and
    exhaustively verified with carry-in and relative-phase Toffolis).
  - `ShallowGenerationCircuit` (69 qubits unmasked / depth `485` vs `888` Lean),
    `ShallowKeyedEmbeddingCircuit` (59 qubits / depth `382` vs `718`), and
    `ShallowBlindVerificationCircuit` (60 qubits / depth `530` vs `866`).
- **T1/T2 ALAP-scheduled idle thermal decoherence study** (`qwm.nisq`,
  `qwm nisq --shallow --thermal`, `qwm.studies.thermal_nisq_study`): compiles to
  native durations and pads idle delays with `ALAPScheduleAnalysis` +
  `PadDelay` + `RelaxationNoisePass` to quantify the wall-duration vs
  gate-count / width tradeoff.
- **OPAP & distortion-optimal keyed blind embedding**:
  - Base `mode="opap"` (`qwm.watermark.embed_image(..., mode="opap")`): Chan-Cheng
    OPAP raises mean PSNR over standard test covers from `44.08 dB` (`lsb`) to
    `46.39 dB` (`SSIM 0.99342`) with zero extraction loss.
  - `SecureWatermark(..., optimize=True)` / `mode="keyed-opt"`: searches 81
    MSB coset shifts `{-4, 0, +4}^4` per 2×2 block to achieve `46.37 dB` mean
    PSNR (`SSIM 0.99329`, MSE `1.499`) with zero receiver changes.
- **Dual-partner 8×8 self-recovery** (`qwm.secure.DualPartnerSelfRecoveringWatermark`,
  `mode="recovery-dual"`, plus `"bicubic"` reconstruction on
  `SelfRecoveringWatermark`): 128 LSB slots (2 bpp) partitioned into 68-bit
  primary companded-Haar quadrant codes, 44-bit disjoint secondary codes, and
  16-bit Toeplitz MAC (`2^-16` forgery probability), maintaining `99.9 %`
  code-restoration at 20 % tampering and `97.7 %` at 40 % tampering.
- **162-d multi-domain forensic descriptors + open-set gate** (`descriptors_v2`,
  `CalibratedOpenSetDetector`): extends the 137-d descriptors with 2D-DCT sub-band
  energy ratios, gradient anisotropy, multiplicative dark/bright noise floor,
  unsharp overshoot, histogram zero-gaps, and bit-plane lag-2 correlations;
  unseen-attack open-set AUROC improves from `0.884` to `0.930` (rejection at
  95 % TPR improves from `34.4 %` to `56.6 %`).
- **Upgraded interactive web demo & CLI**: `qwm serve` now supports all 7 schemes,
  PNG downloads, OOD confidence flagging, shallow CLA + NEQR superposition
  readouts, and live `POST /api/nisq_block` T1/T2 noise simulation.

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
