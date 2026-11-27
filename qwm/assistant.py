"""
Local Hybrid RAG Assistant for the NEQR Quantum Image Watermarking project.

Indexes curated first-person engineering knowledge alongside live markdown
sections parsed directly from the GitHub repository (`README.md`,
`docs/algorithm.md`, `docs/IMPROVEMENTS.md`, `docs/SDLC.md`, `CHANGELOG.md`)
and test module descriptions (`tests/*.py`). Answers in first person as the
project creator/assistant using word + char-ngram TF-IDF + keyword matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class KnowledgeChunk:
    """One searchable RAG knowledge chunk from project code, docs, tests, or base paper."""

    chunk_id: str
    title: str
    source: str
    tags: str
    answer: str
    followups: tuple[str, ...] = ()
    priority: float = 1.0  # Curated synthesized chunks outrank raw markdown ties cleanly.


_CURATED_CHUNKS: tuple[KnowledgeChunk, ...] = (
    KnowledgeChunk(
        chunk_id="tests_and_qa",
        title="Automated Tests & Research Verification I Ran",
        source="GitHub Repo · tests/ & docs/SDLC.md",
        tags="test tests testing did you run pytest unit integration coverage ruff security ci browser e2e verification suite",
        priority=1.18,
        answer=(
            "I built a multi-layer automated test and validation suite for this project:\n"
            "• **202+ pytest tests (~87.8% coverage)** across 16 test files (`tests/test_gates.py`, `test_circuits.py`, `test_neqr.py`, `test_lean_circuits.py`, `test_shallow_circuits.py`, `test_superposition.py`, `test_watermark.py`, `test_secure.py`, `test_v2_studies.py`, `test_enhancements_v3.py`, `test_classifier_resources.py`, `test_metrics_attacks.py`, `test_cli.py`, `test_web.py`, and `test_assistant.py`).\n"
            "• **Exact Quantum Equivalence Checks:** Exhaustively verified reversible gate truth tables (`RHA/RFA/RPA`, `RHS/RFS/RPS`, `D4`, `QE`) and proved exact unitary equality (`Operator`) for my 44q Lean and 69q Shallow Brent-Kung CLA circuits + Eq. 12–16 unitary inverse `U†|W> = |C> ⊗ |Wb>`.\n"
            "• **Large-Scale Empirical Studies:** Ran 1,320 local tamper/forgery trials (`qwm tamper-study`), noisy IBM heavy-hex + thermal T1/T2 Aer simulations (`qwm nisq`), a 4,500-image + 800-image open-set AI benchmark (`qwm classifier-benchmark`), and Table 9 / sphere-packing consistency checks (`qwm paper-checks`).\n"
            "• **Web E2E, Lint, Security & CI:** Verified desktop & mobile browser flows with zero console/network errors, `ruff` + Bandit (`--select S`) security checks, wheel packaging, and GitHub Actions CI on Python 3.10 & 3.12."
        ),
        followups=(
            "What bugs did you find in the base paper?",
            "How did you test self-recovery against tampering?",
            "How did you test NISQ hardware noise?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="overview",
        title="What I Built in This Project",
        source="GitHub Repo · README.md",
        tags="what is project app objective purpose built made created developer author sachin overview neqr quantum watermarking",
        priority=1.14,
        answer=(
            "I built **PhotoShield / NEQR Quantum Image Watermarking (v3.0.2)** — a complete, tested classical simulation and extension of Sahu et al. (*Array* 31, 2026):\n"
            "• **Invisible Watermarking & Tamper Localization:** Hides a 2-bpp cryptographic/quantum watermark inside any photo so human eyes see >98.4% similarity while edits down to 2×2 or 8×8 blocks are flagged in red.\n"
            "• **Automatic Self-Recovery:** My `recovery-dual` engine hides compressed Haar clones in disjoint partner blocks so erased or forged regions heal back automatically.\n"
            "• **Quantum & AI Extensions Beyond v1:** I shrunk block circuits from 354–400 qubits down to 44–69 qubits, added 15-qubit Grover tamper search & NEQR superposition circuits, audited Table 9 & PSNR physics limits, built a 162-d open-set AI attack detector, and wrapped everything into this interactive web studio + `qwm` CLI."
        ),
        followups=(
            "What tests did you run?",
            "How does watermarking work step by step on the Airplane?",
            "What improvements did you add over the base paper?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="how_watermarking_works",
        title="How My Watermarking Pipeline Works Step by Step",
        source="Base Paper Sec. 3.1–3.4 & docs/algorithm.md",
        tags="how watermarking works step by step airplane example pixel ppb aa xor embedding lsb slots hide lock pipeline",
        priority=1.12,
        answer=(
            "Here is how I encode and embed the watermark in every 256×256 image (like the **Airplane** example):\n"
            "• **1. Split Into 2×2 Blocks:** The image divides into 16,384 tiny 2×2 patches encoded with NEQR (`8` brightness qubits + `2` coordinate qubits = `10` qubits per block).\n"
            "• **2. Build Block Signature:** Each pixel's low/high 4-bit nibbles go through 4-bit Reverse Parallel Adders (`RPA`) + `CNOT` parities for Pixel Position Bits (`PPB`), while all 4 pixels are summed and divided by 4 (`D4`) for the rounded average `AA = floor(S/4 + 0.5)`.\n"
            "• **3. Embed Invisibly (2 bpp):** XORing `PPB` with `AA` (plus a secret `SHAKE-256` Toeplitz MAC in my `v2`/`v3` modes) gives an 8-bit stamp tucked into the bottom 2 bits of the 4 pixels. Worked block `[[50,60],[48,32]]` gives `AA=48` and `Wb=11001101`."
        ),
        followups=(
            "How does your self-recovery heal cut parts?",
            "Why did you use NEQR instead of FRQI?",
            "What is the difference between paper mode and keyed-opt?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="neqr_vs_frqi",
        title="Why I Used NEQR Instead of FRQI (Table 11)",
        source="Base Paper Sec. 1.1 & Table 11",
        tags="why neqr vs frqi difference comparison time complexity operations table 11",
        priority=1.15,
        answer=(
            "FRQI encodes grayscale brightness into continuous qubit rotation angles, causing probabilistic readout and quadratic **O(2^(4n))** gate complexity — **4,294,967,296 operations** for a 256×256 image (`n = 8`).\n"
            "NEQR stores all `q = 8` intensity bits deterministically in basis states `|f(Y,X)> ⊗ |Y X>`, dropping preparation cost over **1,000×** to **O(q·n·2^(2n)) = 4,194,304 operations** and allowing exact reversible arithmetic on pixel bits."
        ),
        followups=(
            "Explain RPA, RPS, D4, and QE modules",
            "How did you run true NEQR superposition circuits?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="v2_v3_upgrades",
        title="How My v2 & v3 Extensions Improve the Base Paper",
        source="GitHub Repo · docs/IMPROVEMENTS.md & CHANGELOG.md",
        tags="what did you improve upgrade difference v1 v2 v3 extensions added beyond base paper enhancements",
        priority=1.16,
        answer=(
            "While **v1** reproduces Sahu et al. faithfully, I built major **v2** and **v3** upgrades to solve its blind spots:\n"
            "• **Blind Forgery Security (`SecureWatermark`):** Replaced the non-blind 131,072-bit reference dependency with a secret-keyed `SHAKE-256` Toeplitz MAC on untouched MSBs (`2^-8` to `2^-16` forgery chance, `99.6%` detection even on LSB-preserving splices, `0` false alarms).\n"
            "• **Dual-Partner Self-Recovery (`recovery-dual`):** Fits 68-bit primary + 44-bit secondary Haar recovery clones + 16-bit MAC inside 8×8 blocks (2 bpp), restoring **99.9%** of erased pixels at 20% damage (**~29.01 dB** recovered).\n"
            "• **Optimal Quality (`keyed-opt`):** Searches all `3^4 = 81` MSB shifts per block to hit **46.37 dB** PSNR (`SSIM 0.9933`).\n"
            "• **Qiskit Engineering:** Cut block circuits from **354/400 qubits down to 44–69 qubits**, added 15q Grover search & Brent-Kung CLA depth reduction, heavy-hex NISQ T1/T2 simulation, Table 9/PSNR audits, and a **162-d open-set AI detector**."
        ),
        followups=(
            "How does Dual-Partner 8x8 self-recovery work?",
            "What bugs did you find in Table 9 and 59.97 dB PSNR?",
            "What tests did you run?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="paper_metadata",
        title="About the Research Base Paper (Array 2026)",
        source="Base Research Paper · Array 31 (2026) 101035",
        tags="research base paper authors sahu journal array 2026 doi title citation dataset images",
        priority=1.1,
        answer=(
            "My project builds on *'AI-assisted simulation-based quantum image watermarking using NEQR and reversible quantum logic'* by **Aditya Kumar Sahu, Swapnaneel Dhar, Subhrajyoti Deb, Amine Khaldi, Monalisa Sahu, and De Rosal Ignatius Moses Setiadi**, published in *Array* Vol. 31 (2026), Article 101035 (`10.1016/j.array.2026.101035`).\n"
            "The paper evaluates 16 standard 256×256 grayscale test images (including Airplane, Lena, Baboon, Peppers, Moon, Man, Boat, Aerial, Clown) using IBM Qiskit 0.36 simulation on classical hardware — no real quantum hardware execution is claimed."
        ),
        followups=(
            "What bugs did you find in Table 9 and 59.97 dB PSNR?",
            "What improvements did you add over the base paper?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="quantum_gates",
        title="Reversible Quantum Modules I Implemented (RPA, RPS, D4, QE)",
        source="Base Paper Sec. 2.2–2.5 & qwm/gates/",
        tags="rpa rps d4 qe rha rfa rhs rfs cnot toffoli pauli-x swap reversible quantum gates modules arithmetic",
        priority=1.12,
        answer=(
            "In `qwm/gates/`, I built both module-faithful v1 components and exhaustive truth-table tests for all four reversible blocks:\n"
            "• **RPA (Reverse Parallel Adder):** Chains 1 `RHA` + `(n-1)` `RFA` blocks (`4n` qubits) so inputs stay intact alongside the sum.\n"
            "• **RPS (Reverse Parallel Subtractor):** Uses `RHS` + `RFS` (`4n` qubits) to reverse addition during watermark extraction.\n"
            "• **D4 (Divide-by-4):** Shifts right by 2 bits (`floor(M/4)`) via SWAPs in v1 or zero-gate wire relabelling in my lean circuits.\n"
            "• **QE (Quantum Equal):** `2n+1` qubits comparing two registers with `CNOT`s and multi-controlled NOT."
        ),
        followups=(
            "How did you shrink 354 qubits down to 44 qubits?",
            "What tests did you run?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="v3_self_recovery",
        title="How My Self-Recovery & Dual-Partner 8×8 Haar Healing Works",
        source="GitHub Repo · qwm/secure/recovery.py & docs/IMPROVEMENTS.md",
        tags="self recovery repair heal dual partner 8x8 haar blocks fix cut deleted region recovery-dual",
        priority=1.15,
        answer=(
            "My **v2 (`recovery`)** 4×4 scheme stores a 20-bit partner average + 12-bit MAC per block, healing tampered holes back to **28–29 dB** (~40 dB whole image) with **0.023%** keyless forgery rate.\n"
            "In **v3 (`recovery-dual`, default in the web app)**, I split every 8×8 block's 128 LSB bits (`2 bpp`) into three pieces:\n"
            "• **68 bits:** Primary companded-Haar backup snapshot stored in keyed partner `π₁(B)`.\n"
            "• **44 bits:** Secondary redundant Haar snapshot stored in disjoint partner `π₂(B)`.\n"
            "• **16 bits:** One-time `SHAKE-256` Toeplitz MAC (`2^-16` forgery bound).\n"
            "Tested across 20% and 40% photo deletions, code-based healing jumps from `96.1% / 86.4%` up to **99.9% and 97.7%**!"
        ),
        followups=(
            "How does blind tamper authentication work without reference bits?",
            "What PSNR image quality do your schemes achieve?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="psnr_opap_coset",
        title="Image Quality (PSNR / SSIM), OPAP & Sphere-Packing Audit",
        source="GitHub Repo · qwm/paper_checks.py & qwm/secure/authentication.py",
        tags="psnr ssim quality imperceptibility 59.97 44.17 46.37 opap keyed-opt coset sphere packing mse airplane",
        priority=1.15,
        answer=(
            "By testing information-theoretic QIM bounds (`qwm paper-checks`), I found that the paper's reported **59.97 dB** PSNR (`MSE = 0.066`) cannot belong to hiding 2 checkable bits per pixel — the asymptotic **sphere-packing limit at 2 bpp is 48.41 dB** (`MSE ≥ 0.94`).\n"
            "Measured quality across 20 images in our implementation:\n"
            "• **Literal paper rule:** `41.17 dB` (`airplane`: `41.16 dB`, SSIM `0.966`)\n"
            "• **2-LSB / `keyed` / `recovery`:** `~44.17–44.29 dB` (`SSIM ~0.985`)\n"
            "• **v3 `opap` & `keyed-opt` (81-coset `{-4,0,+4}^4` search):** **`46.39 dB`** and **`46.37 dB`** (`SSIM 0.9933`), with zero receiver changes!"
        ),
        followups=(
            "What bugs did you find in Table 9?",
            "How does v3 Dual-Partner self-recovery work?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="table9_checks",
        title="Physics Bugs I Found in Table 9 & The Literal Embedding Rule",
        source="GitHub Repo · qwm/paper_checks.py & docs/IMPROVEMENTS.md Sec. 1",
        tags="bugs bug flaws flaw mistakes issues problems gaps violations errors audit find found wrong table 9 fidelity trace distance purity fuchs van de graaf literal rule",
        priority=1.18,
        answer=(
            "Running automated audits (`qwm paper-checks` & `qwm tamper-study`), I uncovered three concrete gaps in the paper's reported results:\n"
            "• **1. Table 9 Violates Quantum Mechanics (6 of 16 rows):** Under Fuchs–van de Graaf (`1 − √F ≤ T ≤ √(1 − F)`), rows for *Bird, Man, Boat, House 1, House 2,* and *Aerial* are mathematically impossible (e.g., *House 1* lists `F=1, T=0.4378`, purity `1.3202`). Every simulation generated by my code passes 100%.\n"
            "• **2. 59.97 dB Exceeds the 2-bpp Limit:** Optimal 2-bpp lattice embedding peaks near `47.25 dB` (`48.41 dB` sphere packing).\n"
            "• **3. Non-Blind Literal Rule Flaw:** The literal `RPA → XOR → QE → Pauli-X` rule flips both LSBs regardless of watermark content, detects **0%** of LSB-preserving splices, and needs `131,072` stored reference bits."
        ),
        followups=(
            "How did your v2 keyed scheme fix blind tamper detection?",
            "What tests did you run to verify your code?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="lean_shallow_nisq",
        title="Qubit Reduction (354 → 44 Qubits), Shallow CLA & NISQ Simulation",
        source="GitHub Repo · qwm/circuits/lean.py, shallow.py & qwm/nisq.py",
        tags="qubits lean circuit 44 69 354 400 shallow brent-kung cla nisq noise heavy-hex thermal t1 t2 ibm hardware",
        priority=1.15,
        answer=(
            "I engineered progressively cleaner quantum circuits and tested them on realistic IBM heavy-hex noise:\n"
            "• **8× Qubit Reduction (`qwm/circuits/lean.py`):** Cut block generation/embedding/extraction from `354 / 400 / 400` qubits (Table 21) down to **`44 / 40 / 41` qubits** via Cuccaro adders, zero-gate D4 wire relabelling, Bennett uncomputation, and 3-CNOT Margolus Toffolis (`44q`/`45q` for keyed).\n"
            "• **38–45% Depth Cut (`qwm/circuits/shallow.py`):** Replaced linear ripple carries with my Brent-Kung CLA adder (`69q`, depth `485` vs `888`).\n"
            "• **NISQ Reality Check (`qwm nisq`):** With `ALAPScheduleAnalysis` + `T1 = 300 us` + `p2 = 1e-3` on heavy-hex, 44q lean hits `24.9%` block exactness (`71.0%` at `p2=5e-4`, ahead of Shallow's `64.0%` due to fewer CNOTs). Achieving `99%` per block requires **error correction with `p2 < 1e-5`**."
        ),
        followups=(
            "How did you run 15-qubit Grover tamper search?",
            "Explain the RPA, RPS, D4, and QE gates",
        ),
    ),
    KnowledgeChunk(
        chunk_id="superposition_grover",
        title="True NEQR Superposition & 15-Qubit Grover Tamper Oracle (v3)",
        source="GitHub Repo · qwm/circuits/superposition.py",
        tags="superposition grover search statevector mps 15 qubit 46 47 qubits quantum parallelism",
        priority=1.14,
        answer=(
            "In **v3**, I moved beyond single-basis classical block calls to true coherent NEQR superpositions (`qwm superposition`):\n"
            "• **`neqr_ppb_superposition_circuit`:** Evaluates `PPB` across all image coordinates in quantum superposition simultaneously (`Statevector` verified, ancilla clean probability `1.000000`).\n"
            "• **15-Qubit Grover Tamper Search:** Uses phase-kickback + Grover diffusion in `3` iterations to amplify edited coordinates in a `4×4` patch to **`0.9613` probability mass (`15.38×` gain over uniform)**.\n"
            "• **46–47q MPS Verification:** Runs multi-block blind superposition verification via Qiskit Aer MPS with **`1.0000` shot accuracy**."
        ),
        followups=(
            "How accurate is your AI attack classifier?",
            "How many qubits do the lean circuits use?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="ai_classifier",
        title="My AI Attack Detective (162-d Forensic Descriptors & OOD Gate)",
        source="GitHub Repo · qwm/classifier/ & docs/IMPROVEMENTS.md Sec. 6",
        tags="ai classifier random forest detective attack classification accuracy 96.56 162 ood open set unseen covers",
        priority=1.15,
        answer=(
            "I audited the paper's 9-class Random Forest (100 trees, `4,500` images, Table 18) and upgraded its feature engineering:\n"
            "• **Raw-Pixel Leak Audit:** When tested strictly on **unseen cover images** (`StratifiedGroupKFold`), the paper's 65,536-d raw pixels drop from their reported `96.56%` (random split) down to **`56.13%`** (`66.11%` random split).\n"
            "• **My 162-d Forensic Upgrade (`descriptors_v2`):** Combining statistical, 2D-DCT spectral, gradient anisotropy, median-residual, and bit-plane correlations raises cover-disjoint RF accuracy to **`99.21%`**!\n"
            "• **Open-Set Unknown Attack Detection (`CalibratedOpenSetDetector`):** Flags unseen manipulations at **`0.930` AUROC** (`56.6%` unknown rejection while keeping `95%` of known attacks)."
        ),
        followups=(
            "Which attacks did you test on the images?",
            "What tests did you run?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="attacks_robustness",
        title="Image Attacks & Local Tamper Scenarios I Evaluated",
        source="GitHub Repo · qwm/attacks.py & qwm/tamper.py",
        tags="attacks gaussian noise salt pepper median blur histogram equalization jpeg compression crop rotate text blackout copy-move splice",
        priority=1.1,
        answer=(
            "I implemented and tested both **8 global signal attacks** (`Gaussian noise`, `Salt & pepper`, `Median filter`, `Histogram equalization`, `JPEG compression`, `Cropping`, `Rotation`, `Text addition` in `qwm.attacks`) and **7 local forgery attacks** (`blackout`, `copy-move`, `splice`, `LSB-preserving splice`, `text overlay`, `local blur`, `re-embedded watermark forgery` in `qwm.tamper`).\n"
            "Across all `1,320` local tamper runs, my keyed blind schemes hit **99.6%–99.97% block detection** with **0 false alarms** — including catching sneaky LSB-preserving splices that completely fool the base scheme (`0%`)."
        ),
        followups=(
            "How does Dual-Partner self-recovery repair those blackouts?",
            "How accurate is your AI classifier on these attacks?",
        ),
    ),
    KnowledgeChunk(
        chunk_id="tech_stack_commands",
        title="Tech Stack, Architecture, CLI & Deployment I Built",
        source="GitHub Repo · pyproject.toml, qwm/cli.py, Dockerfile",
        tags="python qiskit cli commands docker install stack web server api health architecture files structure",
        priority=1.1,
        answer=(
            "Everything runs in **Python ≥ 3.10** with `Qiskit ≥ 1.0`, `Qiskit Aer`, `NumPy`, `SciPy`, `scikit-learn`, `scikit-image`, `OpenCV`, `Pillow`, and `Matplotlib`:\n"
            "• **Zero-Framework Web Backend (`qwm/web/server.py`):** Custom `ThreadingHTTPServer` raising secondary thread stack sizes (`64 MiB`) so Qiskit's Rust core simulates safely per-click, with `/api/health`, `/api/paper`, `/api/ask`, `12 MiB` body validation, and path-traversal guards.\n"
            "• **Full CLI (`qwm`):** Includes `qwm ui`, `qwm run`, `qwm embed`, `qwm verify`, `qwm paper-checks`, `qwm nisq`, `qwm tamper-study`, `qwm superposition`, and `qwm classifier-benchmark`.\n"
            "• **Container & CI:** Ships a non-root `Dockerfile` with healthcheck, reproducible `scripts/reproduce_all.sh`, and automated GitHub Actions CI."
        ),
        followups=(
            "What tests did you run?",
            "What improvements did you add over the base paper?",
        ),
    ),
)

_SLANG_AND_EXPANSIONS: dict[str, str] = {
    "u": "you",
    "ur": "your",
    "r": "are",
    "qsn": "question",
    "ques": "question",
    "algo": "algorithm",
    "wm": "watermark watermarked watermarking",
    "tests": "tests pytest testing verification benchmark ran",
    "test": "tests pytest testing verification check ran",
    "tested": "tests pytest testing verification experiments",
    "made": "built implemented project created",
    "build": "built implemented project created",
    "created": "built implemented project created",
    "heal": "recovery self-recovery repair fix restore",
    "fix": "recovery self-recovery heal repair fix",
    "tamper": "tamper edit fake splice blackout cut forgery",
    "ai": "ai classifier random forest detective features 162 ood",
    "paper": "paper",
    "citation": "authors sahu journal array 2026 doi title citation",
    "authors": "authors sahu journal array 2026 doi title citation",
    "bugs": "bugs issues flaws violations audit table 9 fuchs",
    "bug": "bugs issues flaws violations audit table 9 fuchs",
    "flaws": "bugs issues flaws violations audit table 9 fuchs",
    "issues": "bugs issues flaws violations audit table 9 fuchs",
    "quantum": "qubit circuit qiskit neqr rpa rps d4 qe nisq grover",
    "speed": "complexity operations ms time",
    "airplane": "airplane example sample cover image 2x2 block",
}

_STOP_WORDS = frozenset({
    "what", "how", "why", "who", "when", "where", "which", "is", "are", "was", "were",
    "the", "a", "an", "in", "on", "to", "for", "of", "this", "that", "it", "my", "your",
    "you", "i", "we", "me", "our", "from", "with", "do", "does", "did", "can", "could",
    "would", "should", "explain", "tell", "about", "please", "pls", "plss", "and", "or",
})

_GREETING_RE = re.compile(r"^(hi|hello|hey|yo|hola|namaste|good\s*(morning|afternoon|evening)|who are you|help)[!.?\s]*$", re.I)
_FOLLOWUP_RE = re.compile(
    r"^(tell me more|more details|explain more|why|how does that work|what else|continue|elaborate|go deeper|details)[?.!\s]*$",
    re.I,
)


def _clean_md_text(raw: str) -> str:
    """Turn raw markdown paragraphs/tables into crisp plain prose."""
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("<") or s.startswith("![") or set(s) <= set("|-: "):
            continue
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            s = " · ".join(c for c in cells if c)
        s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
        s = re.sub(r"[*_`]+", lambda m: m.group(0) if "`" in m.group(0) else "", s)
        lines.append(s)
    text = "\n".join(lines).strip()
    return text[:680] + ("..." if len(text) > 680 else "")


def _load_repo_markdown_chunks() -> list[KnowledgeChunk]:
    """Dynamically ingest markdown sections from repo docs into RAG chunks."""
    docs = (
        ("README.md", "GitHub Repo · README.md"),
        ("docs/algorithm.md", "GitHub Repo · docs/algorithm.md"),
        ("docs/IMPROVEMENTS.md", "GitHub Repo · docs/IMPROVEMENTS.md"),
        ("docs/SDLC.md", "GitHub Repo · docs/SDLC.md"),
        ("CHANGELOG.md", "GitHub Repo · CHANGELOG.md"),
    )
    chunks: list[KnowledgeChunk] = []
    for rel, source in docs:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        sections = re.split(r"(?m)^(#{2,3}\s+.+)$", content)
        for i in range(1, len(sections) - 1, 2):
            heading = sections[i].lstrip("# ").strip()
            heading_clean = re.sub(r"^\d+(\.\d+)*\.?\s*", "", heading)
            body = _clean_md_text(sections[i + 1])
            if len(body) < 40:
                continue
            chunks.append(
                KnowledgeChunk(
                    chunk_id=f"doc:{rel}:{i}",
                    title=heading_clean,
                    source=source,
                    tags=f"{rel} {heading_clean.lower()}",
                    answer=body,
                    priority=0.86,
                )
            )
    return chunks


def _load_test_inventory_chunks() -> list[KnowledgeChunk]:
    """Dynamically ingest every test module docstring from tests/*.py into RAG."""
    tdir = REPO_ROOT / "tests"
    if not tdir.exists():
        return []
    summaries = []
    for p in sorted(tdir.glob("test_*.py")):
        head = p.read_text(encoding="utf-8", errors="ignore")[:320]
        m = re.search(r'"""(.*?)"""', head, re.S)
        desc = " ".join(m.group(1).split()) if m else "automated unit & integration checks"
        summaries.append(f"• `{p.name}`: {desc}")
    if not summaries:
        return []
    return [
        KnowledgeChunk(
            chunk_id="test_inventory_files",
            title="Full Breakdown of Test Files (`tests/*.py`)",
            source="GitHub Repo · tests/",
            tags="test files breakdown test_gates test_circuits test_lean test_shallow test_superposition test_secure test_web test_assistant test_cli test_v2",
            answer="Here is the file-by-file breakdown of the test suite I wrote in `tests/`:\n" + "\n".join(summaries[:10]),
            followups=("What tests did you run overall?", "How is CI/CD set up?"),
            priority=0.98,
        )
    ]


class ProjectAssistant:
    """First-person Hybrid RAG Assistant indexed over repo docs, tests, and base paper."""

    def __init__(self) -> None:
        self.chunks: list[KnowledgeChunk] = [
            *_CURATED_CHUNKS,
            *_load_test_inventory_chunks(),
            *_load_repo_markdown_chunks(),
        ]
        corpus = [f"{c.title}. {c.tags}. {c.answer}" for c in self.chunks]
        self._word_vec = TfidfVectorizer(ngram_range=(1, 2), lowercase=True, stop_words="english")
        self._word_mat = self._word_vec.fit_transform(corpus)
        self._char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), lowercase=True)
        self._char_mat = self._char_vec.fit_transform(corpus)

    @staticmethod
    def _preprocess_query(query: str) -> tuple[str, set[str]]:
        raw_tokens = re.findall(r"[a-zA-Z0-9_-]+", query.lower())
        normalized = [_SLANG_AND_EXPANSIONS.get(t, t) for t in raw_tokens]
        expanded = " ".join(normalized)
        meaningful = set(re.findall(r"[a-z0-9_-]+", expanded.lower())) - _STOP_WORDS
        return f"{query} {expanded}".strip(), meaningful

    @staticmethod
    def _overlap_bonus(meaningful: set[str], chunk: KnowledgeChunk) -> float:
        if not meaningful:
            return 0.0
        hay = set(re.findall(r"[a-z0-9_-]+", f"{chunk.title} {chunk.tags}".lower()))
        hits = len(meaningful & hay)
        return 0.16 * (hits / max(1, len(meaningful)))

    def ask(self, question: str, last_topic: str | None = None) -> dict:
        """Answer a visitor's question naturally using Hybrid RAG over project & paper."""
        q = (question or "").strip()
        if not q:
            raise ValueError("please enter a question")
        if len(q) > 500:
            raise ValueError("question must be under 500 characters")

        if _GREETING_RE.match(q):
            return {
                "grounded": True,
                "topic_id": "overview",
                "title": "Welcome to PhotoShield",
                "answer": (
                    "Hey! I built this NEQR Quantum Image Watermarking project (v3.0.2). "
                    "Ask me anything — like how Airplane watermarking works, what 202+ tests and experiments I ran, "
                    "what bugs I uncovered in the Array 2026 base paper, or how our v2/v3 blind self-recovery heals tampered images."
                ),
                "sources": ["GitHub Repo · README.md"],
                "suggestions": list(_CURATED_CHUNKS[0].followups),
            }

        query_for_search = q
        if last_topic and _FOLLOWUP_RE.match(q):
            match_prev = next((c for c in self.chunks if c.chunk_id == last_topic), None)
            if match_prev:
                query_for_search = f"{q} {match_prev.title} {match_prev.tags}"

        expanded, meaningful = self._preprocess_query(query_for_search)
        w_scores = cosine_similarity(self._word_vec.transform([expanded]), self._word_mat)[0]
        c_scores = cosine_similarity(self._char_vec.transform([expanded]), self._char_mat)[0]

        ranked = sorted(
            (
                (
                    (0.68 * float(w_scores[i]) + 0.32 * float(c_scores[i]) + self._overlap_bonus(meaningful, self.chunks[i]))
                    * self.chunks[i].priority,
                    i,
                )
                for i in range(len(self.chunks))
            ),
            reverse=True,
        )

        best_score, best_idx = ranked[0]
        if best_score < 0.135:
            return {
                "grounded": False,
                "topic_id": None,
                "answer": (
                    "That falls outside my NEQR Quantum Watermarking project! "
                    "Ask me instead about the automated tests & benchmarks I ran, how Airplane watermarking & auto-healing work, "
                    "my v2/v3 blind security upgrades, Qiskit circuit qubit savings, or findings from the Array 2026 research paper."
                ),
                "sources": [],
                "suggestions": [
                    "What tests did you run?",
                    "What did you build in this project?",
                    "How does watermarking work step by step?",
                    "What bugs did you find in Table 9 and PSNR?",
                ],
            }

        top = self.chunks[best_idx]
        chosen = [top]
        # Optionally enrich with 1 complementary chunk that adds genuinely different source context.
        for score_k, idx_k in ranked[1:5]:
            cand = self.chunks[idx_k]
            if cand.chunk_id != top.chunk_id and score_k >= max(0.18, best_score * 0.72) and len(chosen) < 2:
                if cand.title.lower() not in top.title.lower():
                    chosen.append(cand)

        answer = top.answer if len(chosen) == 1 else f"{top.answer}\n\n**{chosen[1].title}:**\n{chosen[1].answer}"
        suggestions = list(top.followups) if top.followups else [
            "What tests did you run?",
            "What did v2 and v3 improve over the base paper?",
        ]

        return {
            "grounded": True,
            "topic_id": top.chunk_id,
            "title": top.title,
            "answer": answer,
            "sources": list(dict.fromkeys(c.source for c in chosen)),
            "confidence": round(min(1.0, best_score), 3),
            "suggestions": suggestions,
        }
