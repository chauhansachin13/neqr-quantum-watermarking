# Algorithm reference

This document describes, module by module, what the package implements and
how each piece maps to the simulation-level NEQR watermarking framework it
reproduces. Section and figure numbers refer to the reference design
(*AI-assisted simulation-based quantum image watermarking using NEQR and
reversible quantum logic*, Array 31 (2026) 101035).

## 1. Image representation - NEQR (`qwm.neqr`)

A grayscale image of size `2^n x 2^n` with `q = 8` bit pixels is encoded as

```
|I> = 1/2^n  sum_{Y=0}^{2^n-1} sum_{X=0}^{2^n-1} |f(Y,X)> (x) |Y X>
```

The preparation circuit (Algorithms 1 and 2) uses

* `q` intensity qubits (qubits `0..7`, LSB first) and `2n` position qubits,
* Hadamard gates on the position qubits,
* for every pixel, one multi-controlled NOT per set bit of the intensity,
  controlled on the position register (`X` gates select the coordinate).

For the `2x2` blocks used by the watermarking scheme the circuit has
`8 + 2 = 10` qubits (`intensity` and `idx` registers of Algorithm 1) and the
controls are Toffoli (`ccx`) gates, as in Fig. 8.  `neqr_statevector` gives
the same state in closed form (amplitude `1/2` at index `(p << 8) | f_p`);
`decode_statevector` / `decode_counts` read the image back from a statevector
or from Aer measurement counts.

## 2. Reversible modules (`qwm.gates`)

All modules are permutation circuits (X, CNOT, Toffoli, SWAP, multi-controlled
NOT).  They keep their inputs recoverable, so each one is its own inverse up
to the ancilla content, and they can be simulated exactly for hundreds of
qubits with `qwm.simulation.BasisStateSimulator`.

| Module | Qubits | Function | Wire semantics |
|---|---|---|---|
| RHA (Fig. 1a) | 4 | half adder | `\|x>\|0>\|y>\|0> -> \|x>\|y>\|x^y>\|x&y>` |
| RFA (Fig. 1b) | 5 | full adder | `\|z>\|x>\|0>\|y>\|0> -> \|z>\|x>\|y>\|x^y^z>\|carry>` |
| RPA (Fig. 1c) | `4n` | ripple-carry adder: 1 RHA + `n-1` RFA | `x` kept, `y` wires hold the sum, ancillas hold a copy of `y` and the carries (`z_{n-1}` = carry-out) |
| RHS (Fig. 4a) | 4 | half subtractor | `\|x>\|0>\|y>\|0> -> \|x>\|y>\|x^y>\|~x&y>` |
| RFS (Fig. 4b) | 5 | full subtractor | `\|z>\|x>\|0>\|y>\|0> -> \|z>\|x>\|y>\|x^y^z>\|borrow>` |
| RPS (Fig. 4c) | `4n` | ripple-borrow subtractor | same layout as RPA, difference on the `y` wires |
| D4 (Fig. 2) | `n+2` | `floor(M/4)` | SWAP network shifting the register by two positions; the two `\|0>` ancillas become the new MSBs and the dropped LSBs are kept as garbage |
| QE (Fig. 3) | `2n+1` | equality test | `CNOT(i_k -> j_k)` for all `k`, an `n`-controlled NOT (controls on `\|0>`) on the ancilla, then the CNOTs again to restore `J`; ancilla = 1 iff `I == J` |

Every module class exposes `.circuit`, `.gate`, the index lists of its
registers, a classical reference (`add`, `subtract`, `divide`, `equal`) and
`.simulate(...)`, and the test-suite checks them exhaustively for small `n`.

## 3. Watermark generation (`qwm.watermark.generation`, `qwm.circuits.generation`)

For every non-overlapping `2x2` block `[[C00, C01], [C10, C11]]`:

### 3.1 Pixel position bits (Sec. 3.2.1, Fig. 9)

Each pixel `P_i` is split into the low nibble `P_i^(L) = b3 b2 b1 b0` and the
high nibble `P_i^(R) = b7 b6 b5 b4`.  A 4-bit RPA adds the two nibbles and
yields two 4-qubit registers - the sum bits `T_{i,2}` and the carries
`T_{i,1}`.  A CNOT chain (`CNOT^(x)4`) folds each register into its parity,
and one more CNOT combines the two parities:

```
PPB_{i,1} = parity(carries)
PPB_{i,2} = parity(sum bits) xor PPB_{i,1}
```

For the worked example this gives `PPB_1 = (1,1)`, `PPB_2 = (0,0)`,
`PPB_3 = (0,0)`, `PPB_4 = (0,1)` - the values shown in Fig. 9.

### 3.2 Arithmetic average (Sec. 3.2.2)

Three RPAs compute `S = C00 + C01 + C10 + C11` (8-, 8- and 9-bit adders), a
fourth RPA adds the rounding constant `|2>` and the D4 module divides by
four, so that `AA = floor(S/4 + 0.5)`.  `50 + 60 + 48 + 32 = 190 -> 48`.

### 3.3 Watermark bits (Fig. 10 / 11)

```
Wb_k = s_k xor PPB_{floor(k/2)+1, (k mod 2)+1},   k = 0..7
```

where `s_k` is bit `k` of `AA`.  Example: `Wb = 1,1,0,0,1,1,0,1`.

The Qiskit circuit `WatermarkGenerationCircuit` builds exactly this pipeline
(4 RPA(4) + 2 RPA(8) + RPA(9) + RPA(10) + D4(10) + CNOT chains + 8 CNOTs,
146 qubits) and its exact simulation reproduces the classical reference for
every block (tested on random blocks).

## 4. Embedding (`qwm.watermark.embedding`, `qwm.circuits.embedding`)

The two least significant bits of every pixel carry two watermark bits
(`Wb_{2i}`, `Wb_{2i+1}` for pixel `i` of the block), giving a payload of
`8 bits / 4 pixels = 2 bpp`.

`mode="paper"` follows the reversible procedure of Sec. 3.3 / Table 3 for
bit `k in {0, 1}`:

1. `RPA(C^{k+1}, Wb)` - the 1-qubit adder result, read as *sum or carry* so that
   `|1> + |1> -> |1>` as in Table 3;
2. `XOR` with `C^{k+1}`;
3. `QE` comparison with the current bit `C^k`;
4. `Pauli-X` when the QE reports equality;
5. the result replaces `C^k` (a SWAP in the circuit, keeping it reversible).

Steps 3-4 map any value to `not C^k`; consequently this rule inverts both
LSBs of every pixel (`50 -> 49`, `60 -> 63`, `48 -> 51`, `32 -> 35`).  The
watermarked image therefore does not depend on the watermark content - the
content is verified at extraction time by the QE model.

`mode="lsb"` performs the plain LSB replacement described in Step 1 of
Sec. 3.3 (`Wb_0 -> C^0`, `Wb_1 -> C^1`), which produces a blind,
content-carrying watermark that can be read back without a reference.

## 5. Extraction (`qwm.watermark.extraction`, `qwm.circuits.extraction`)

For bit `k in {0, 1}` of every watermarked pixel (Sec. 3.4 / Table 4):

1. `XOR`: `x = W^{k+1} xor W^k`;
2. `RPS`: `d = x - W^{k+1}` (1-qubit subtractor) - this equals the embedded bit `W^k`;
3. `QE`: compare `d` with the reference bit `Wb`;
4. `Pauli-X` if they differ.

The bits after step 2 are the *raw* (blind) watermark; the bits after step 4
are the reference-verified output.  `bit_error_rate`, `normalized_correlation`
and `tamper_map` compare raw and reference bits, which is what the robustness
experiments report.

## 6. Metrics

* `qwm.metrics.image`: MSE (Eq. 17), PSNR (Eq. 18), SSIM (Eq. 19 with global
  statistics, plus the standard windowed SSIM), histograms and histogram
  intersection.
* `qwm.metrics.quantum`: fidelity (Eq. 20), trace distance (Eq. 21) and purity
  / purity ratio (Eq. 22) of NEQR block states, optionally after depolarising,
  amplitude-damping, phase-damping or bit-flip channels applied to every
  qubit (decoherence modelling, Sec. 4.2).  Pure-state cases use closed forms;
  mixed-state fidelity uses a Hermitian eigendecomposition.

## 7. Attacks (`qwm.attacks`)

Gaussian noise, salt-and-pepper noise, median filtering, histogram
equalisation, JPEG compression, cropping, rotation and text addition
("Confidential"), with the parameters of Table 7 as defaults and randomised
parameters for dataset generation.

## 8. AI-assisted attack classification (`qwm.classifier`)

* Dataset (Sec. 4.8.1): nine balanced classes, 500 samples per class by
  default (4,500 samples), generated from augmented cover images that are
  watermarked and then attacked with randomised parameters.
* Features (Sec. 4.8.2): `256 x 256` normalised intensities flattened to a
  65,536-dimensional vector (`features="pixels"`, the representation of
  Table 17).  A compact 137-dimensional distortion-descriptor vector
  (`features="descriptors"`: histogram statistics, saturated-pixel / border
  statistics, median-residual and gradient statistics, spectral energy,
  8x8 blockiness, bit-plane statistics, 8x8 thumbnail) is provided as an
  alternative that generalises across covers and attack strengths.
* Attack strengths: `params="random"` draws them per sample from realistic
  ranges; `params="table7"` freezes them to the values of Table 7.
* Model (Table 18): `RandomForestClassifier(n_estimators=100, criterion="gini",
  max_depth=None, min_samples_split=2, min_samples_leaf=1, max_features="sqrt",
  bootstrap=True, class_weight=None, random_state=42)`.
* Protocol (Sec. 4.8.4): 80:20 stratified split, stratified 5-fold
  cross-validation on the training set, final fit, accuracy / precision /
  recall / F1 (overall and per class), confusion matrix, 95 % confidence
  interval of the test accuracy (Wald and Wilson) and a one-sided binomial test
  against the 11.11 % chance level.

## 9. Resource analysis (`qwm.resources`)

`reported_resources` reproduces the closed-form budget of Sec. 4.9 (`9n-4`,
`6n+3`, `16n-11` gate complexities; 354 / 400 / 400 qubits for generation /
embedding / extraction with `n = 8`, Table 21) and `measure_*` count the
qubits, gates and depth of the circuits actually built by this package, both
at the reversible level (`X, CNOT, Toffoli, SWAP, MCX`) and after decomposition
into `{U, CNOT}`.
