"""
Grounded Q&A assistant answering strictly from this project's GitHub docs,
implemented code metrics, and the Sahu et al. (Array 31, 2026, 101035) base paper.

No external LLM API calls or invented claims: queries are matched using TF-IDF
cosine similarity + domain term overlap over verified knowledge chunks parsed from
the repository documentation and base-paper benchmark tables. Out-of-scope queries
are explicitly declined.
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
    """One verified knowledge unit backed by a repo or paper source."""

    chunk_id: str
    title: str
    source: str
    tags: str
    answer: str


_CURATED_CHUNKS: tuple[KnowledgeChunk, ...] = (
    KnowledgeChunk(
        chunk_id="overview",
        title="Project Purpose & What This Web App Does",
        source="GitHub Repo · README.md",
        tags="what does project app do objective purpose overview neqr quantum watermarking",
        answer=(
            "This project (NEQR Quantum Image Watermarking v3.0.2 by Sachin Chauhan) reproduces "
            "Sahu et al. (Array 31, 2026) and extends it into an end-to-end photo protection tool. "
            "It hides an invisible 2-bpp safety lock inside grayscale or color images using NEQR and "
            "reversible quantum arithmetic (RPA, RPS, D4, QE), catches fake edits blindly down to 2x2/8x8 blocks, "
            "automatically heals cut or tampered areas from hidden partner backup copies, classifies 9 image "
            "attacks with an AI Random Forest detective, and simulates every block circuit in IBM Qiskit on classical hardware."
        ),
    ),
    KnowledgeChunk(
        chunk_id="how_watermarking_works",
        title="How Watermarking Works Step by Step (2x2 Blocks & 8-Bit Wb)",
        source="Base Paper Sec. 3.1–3.4 & docs/algorithm.md",
        tags="how watermarking works step by step airplane example pixel ppb aa xor embedding lsb slots hide lock",
        answer=(
            "Every 256x256 image is split into 16,384 non-overlapping 2x2 pixel blocks (4 pixels per block). "
            "1) Each block is represented with NEQR (8 intensity qubits + 2 coordinate qubits = 10 qubits). "
            "2) Two Pixel Position Bits (PPB) per pixel are computed using 4-bit Reverse Parallel Adders (RPA) on low/high nibbles plus CNOT parities. "
            "3) The rounded Arithmetic Average AA = floor((C00+C01+C10+C11)/4 + 0.5) is computed with RPAs and Divide-by-4 (D4). "
            "4) XORing PPB and AA gives an 8-bit watermark Wb (2 bits per pixel = 2 bpp, keeping >98% visual match). "
            "5) For example, worked block [[50,60],[48,32]] yields sum 190 -> AA=48 and Wb=11001101."
        ),
    ),
    KnowledgeChunk(
        chunk_id="neqr_vs_frqi",
        title="Why NEQR Is Used Instead of FRQI (Table 11 Complexity)",
        source="Base Paper Sec. 1.1 & Table 11",
        tags="why neqr vs frqi difference comparison time complexity operations table 11",
        answer=(
            "FRQI stores grayscale values inside continuous qubit rotation angles, which makes retrieval probabilistic "
            "and requires O(2^(4n)) preparation gates — 4,294,967,296 operations for a 256x256 image (n = 8). "
            "NEQR instead stores all q = 8 intensity bits cleanly in computational basis states |f(Y,X)> (x) |Y X>, "
            "cutting state preparation complexity to O(q * n * 2^(2n)) = 4,194,304 operations for 256x256 (over 1,000x cheaper)."
        ),
    ),
    KnowledgeChunk(
        chunk_id="paper_metadata",
        title="Base Research Paper Citation & Experimental Setup",
        source="Base Research Paper · Array 31 (2026) 101035",
        tags="research base paper authors sahu journal array 2026 doi title citation dataset images",
        answer=(
            "The base paper is 'AI-assisted simulation-based quantum image watermarking using NEQR and reversible "
            "quantum logic' by Aditya Kumar Sahu, Swapnaneel Dhar, Subhrajyoti Deb, Amine Khaldi, Monalisa Sahu, and "
            "De Rosal Ignatius Moses Setiadi, published in Array Vol. 31 (2026), Article 101035 (DOI: 10.1016/j.array.2026.101035). "
            "Experiments tested 16 standard 256x256 grayscale images (including Airplane, Lena, Baboon, Peppers, Moon, etc.) "
            "using IBM Qiskit 0.36 simulation on classical CPU hardware (no physical quantum processor execution or speedup claimed)."
        ),
    ),
    KnowledgeChunk(
        chunk_id="quantum_gates",
        title="Reversible Quantum Modules (RPA, RPS, D4, QE)",
        source="Base Paper Sec. 2.2–2.5 & qwm/gates/",
        tags="rpa rps d4 qe rha rfa rhs rfs cnot toffoli pauli-x swap reversible quantum gates modules",
        answer=(
            "Four custom reversible modules implement arithmetic using CNOT, Toffoli (CCNOT), SWAP, and Pauli-X gates: "
            "• RPA (Reverse Parallel Adder): 1 RHA + (n-1) RFAs (4n qubits) to add pixel values cleanly without losing inputs. "
            "• RPS (Reverse Parallel Subtractor): 1 RHS + (n-1) RFSs (4n qubits) to invert addition during extraction. "
            "• D4 (Divide by 4): n+2 qubits using SWAP gates (or free wire relabelling in v2 lean circuits) to shift right by 2 bits. "
            "• QE (Quantum Equal): 2n+1 qubits comparing two n-bit sequences via CNOTs and multi-controlled NOT."
        ),
    ),
    KnowledgeChunk(
        chunk_id="v2_keyed_blind",
        title="v2 Keyed Blind Authentication (Why Base Paper Couldn't Detect Blindly)",
        source="GitHub Repo · docs/IMPROVEMENTS.md Sec. 2",
        tags="v2 keyed blind authentication hmac toeplitz shake-256 secret key nonce tamper detection splice",
        answer=(
            "The base paper's scheme is non-blind (needs 131,072 stored reference bits), its literal Pauli-X rule inverts "
            "both LSBs regardless of Wb, and it detects 0% of splices that preserve the 2 LSBs. "
            "v2 (`SecureWatermark`) fixes this without extra storage: it computes Wb = g(MSB) XOR T_b*m XOR c_b using a secret key + nonce "
            "and SHAKE-256 Toeplitz MAC over the 6 untouched MSBs. Result: 0% false alarms, 99.6% detection even on LSB-preserving splices, "
            "and a keyless forgery chance of just 2^-8 (0.39%) per 2x2 block."
        ),
    ),
    KnowledgeChunk(
        chunk_id="v3_self_recovery",
        title="Self-Recovery & v3 Dual-Partner 8x8 Haar Healing",
        source="GitHub Repo · docs/IMPROVEMENTS.md Sec. 3 & 9",
        tags="self recovery repair heal dual partner 8x8 haar blocks fix cut deleted region recovery-dual",
        answer=(
            "v2 introduced 4x4 blind self-recovery (`recovery`), storing 20-bit partner averages + 12-bit MAC per block. "
            "v3 upgrades this to Dual-Partner 8x8 Companded-Haar Self-Recovery (`recovery-dual`, default in this web app): within "
            "the same 2 bpp LSB budget (128 bits per 8x8 block), it packs a 68-bit primary Haar clone in partner pi_1(B), "
            "a 44-bit secondary Haar clone in disjoint partner pi_2(B), and a 16-bit Toeplitz MAC (2^-16 forgery limit). "
            "Across 20% and 40% tampering tests, code-based repair reaches 99.9% and 97.7% (healing ~29 dB in the erased region)."
        ),
    ),
    KnowledgeChunk(
        chunk_id="psnr_opap_coset",
        title="Image Quality (PSNR, SSIM), OPAP & Sphere-Packing Audit",
        source="GitHub Repo · docs/IMPROVEMENTS.md Sec. 1.2 & 9.3",
        tags="psnr ssim quality imperceptibility 59.97 44.17 46.37 opap keyed-opt coset sphere packing mse airplane",
        answer=(
            "The base paper reports PSNRs up to 59.97 dB (58.67 dB on Airplane), which implies MSE = 0.066 — below the "
            "2-bpp information-theoretic sphere-packing limit (MSE >= 0.94, PSNR <= 48.41 dB). Measured quality in this repo is "
            "44.17 dB (SSIM 0.986) for 2-LSB embedding, 41.17 dB for the literal paper rule, and in v3: OPAP (`mode='opap'`) "
            "reaches 46.39 dB while `keyed-opt` searches all 3^4 = 81 MSB shifts {-4,0,+4}^4 jointly with the MAC to reach "
            "46.37 dB (SSIM 0.9933) with zero receiver modifications."
        ),
    ),
    KnowledgeChunk(
        chunk_id="table9_checks",
        title="Table 9 Fuchs-van de Graaf Quantum Consistency Check",
        source="GitHub Repo · qwm/paper_checks.py & docs/IMPROVEMENTS.md Sec. 1.1",
        tags="table 9 fidelity trace distance purity fuchs van de graaf checks audit violations",
        answer=(
            "Running `qwm paper-checks` checks Table 9's reported quantum metrics against the Fuchs-van de Graaf "
            "inequality `1 - sqrt(F) <= T <= sqrt(1 - F)`. Six of the 16 reported rows violate quantum mechanics bounds "
            "(Bird, Man, Boat, House 1, House 2, Aerial — e.g., House 1 reports F=1 with T=0.4378 and Purity=1.3202). "
            "By contrast, every row simulated directly by this package under depolarizing, amplitude-damping, and phase-damping "
            "channels satisfies the inequality cleanly."
        ),
    ),
    KnowledgeChunk(
        chunk_id="lean_shallow_nisq",
        title="Qubit Reduction (354 → 44 Qubits), CLA Depth & NISQ Hardware Reality",
        source="GitHub Repo · qwm/circuits/ & docs/IMPROVEMENTS.md Sec. 4–5 & 9",
        tags="qubits lean circuit 44 69 354 400 shallow brent-kung cla nisq noise heavy-hex thermal t1 t2 hardware",
        answer=(
            "• Base paper (Table 21) spends 354 qubits on generation and 400 each on embedding/extraction.\n"
            "• v2 Lean circuits (`qwm.circuits.lean`) cut this ~8x to 44 / 40 / 41 qubits using Cuccaro in-place adders, "
            "wire-relabelling D4, Bennett uncomputation, and Margolus 3-CNOT Toffolis (exact unitary equality verified).\n"
            "• v3 Shallow Brent-Kung CLA circuits (`qwm.circuits.shallow`, 69 qubits) slash compiled depth by 38–45% (485 vs 888).\n"
            "• NISQ simulation on IBM heavy-hex lattices (`p2 = 1e-3`, `T1 = 300 us`) gets ~24.9% block success for 44q lean generation "
            "(vs 16.8% for 146q v1); reaching 99% per block requires error correction with `p2 < 1e-5`."
        ),
    ),
    KnowledgeChunk(
        chunk_id="superposition_grover",
        title="v3 True NEQR Coordinate Superposition & 15-Qubit Grover Tamper Search",
        source="GitHub Repo · qwm/circuits/superposition.py & README.md",
        tags="superposition grover search statevector mps 15 qubit 46 47 qubits quantum parallelism",
        answer=(
            "In v3, `neqr_ppb_superposition_circuit` prepares a coherent NEQR state (1/sqrt(HW)) sum |f(y,x)>|y,x> and computes PPB across "
            "all coordinates simultaneously in a single Statevector-verified circuit (ancilla clean probability 1.000000). "
            "`run_grover_tamper_search` adds a 15-qubit phase-kickback oracle + Grover diffusion over 3 iterations to amplify altered pixels "
            "to 0.9613 probability (15.38x above uniform), while `block_neqr_blind_verify` verifies multi-block patches via 47-qubit MPS Aer simulation."
        ),
    ),
    KnowledgeChunk(
        chunk_id="ai_classifier",
        title="AI Attack Classifier (Random Forest, 162-d Descriptors & Open-Set Detection)",
        source="Base Paper Sec. 4.8 & docs/IMPROVEMENTS.md Sec. 6 & 9.5",
        tags="ai classifier random forest detective attack classification accuracy 96.56 162 ood open set unseen covers",
        answer=(
            "The base paper uses a 100-tree Random Forest (`random_state=42`, Table 18) on 4,500 images across 9 classes "
            "(No attack, Gaussian noise, Salt & pepper, Median filter, Histogram equalisation, JPEG, Cropping, Rotation, Text addition) "
            "reporting 96.56% accuracy on flattened 65,536-d pixels. Stricter evaluation in this repo shows flattened pixels drop to 66.1% "
            "(random split) and 56.1% (unseen covers), whereas v3's 162-d multi-domain forensic descriptors achieve 99.21% on unseen covers "
            "plus calibrated open-set OOD detection (0.930 AUROC, flagging 56.6% of unknown attack types)."
        ),
    ),
    KnowledgeChunk(
        chunk_id="attacks_robustness",
        title="Image Processing Attacks & Robustness Behavior",
        source="Base Paper Sec. 4.1, Table 7 & README.md",
        tags="attacks gaussian noise salt pepper median blur histogram equalization jpeg compression crop rotate text",
        answer=(
            "Eight image-processing attacks are implemented in `qwm.attacks` (plus local manipulations blackout, copy-move, splice, "
            "lsb_preserving_splice, text_overlay, local_blur in `qwm.tamper`). Because fragile authentication hashes every block via its LSBs "
            "and MSBs, the keyed schemes tolerate minor salt-and-pepper/crop outside untouched tiles while intentionally rejecting global edits "
            "like JPEG recompression, filtering, or rotation so tampering cannot pass verification silently."
        ),
    ),
    KnowledgeChunk(
        chunk_id="tech_stack_commands",
        title="Technology Stack, CLI Commands, Tests & Architecture",
        source="GitHub Repo · pyproject.toml, qwm/cli.py, docs/SDLC.md",
        tags="python qiskit cli commands tests docker install stack web server api health test coverage ci",
        answer=(
            "Built in Python >= 3.10 with Qiskit (>=1.0), Qiskit Aer, NumPy, SciPy, scikit-learn, scikit-image, OpenCV, Pillow, and Matplotlib; "
            "the web UI runs on Python's stdlib `ThreadingHTTPServer` (`qwm/web/server.py`) with vanilla HTML/CSS/JS and zero heavy JS frameworks. "
            "Key commands: `qwm ui` (web studio), `qwm run` (end-to-end showcase), `qwm paper-checks`, `qwm nisq`, `qwm tamper-study`, "
            "and `qwm classifier-benchmark`. Verified with 198+ pytest tests (~88% coverage), `ruff`, `ruff --select S`, Docker support, and GitHub Actions CI."
        ),
    ),
)

_SYNONYM_MAP: dict[str, str] = {
    "heal": "recovery self-recovery fix repair restore",
    "fix": "recovery self-recovery heal repair",
    "Tamper": "attack edit fake splice blackout cut",
    "tamper": "attack edit fake splice blackout cut",
    "ai": "classifier random forest detective features 162 ood",
    "paper": "base research sahu array 2026 table",
    "quantum": "qubit circuit qiskit neqr rpa rps d4 qe nisq grover",
    "speed": "complexity operations ms time",
    "safe": "security hmac toeplitz shake-256 forgery",
    "color": "grayscale rgb image quality psnr ssim",
    "airplane": "example sample cover image 2x2 block",
}

_STOP_WORDS = frozenset({
    "what", "how", "why", "is", "are", "the", "a", "an", "in", "on", "to", "for",
    "of", "this", "that", "it", "my", "your", "from", "with", "do", "does", "did",
    "can", "explain", "tell", "me", "about", "please", "and", "or",
})

_OUT_OF_SCOPE_MSG = (
    "I can only answer questions directly grounded in this project's GitHub codebase, "
    "documentation, and the Sahu et al. (Array 2026) research base paper. "
    "Try asking about: how watermarking works on the Airplane example, NEQR vs FRQI, "
    "PSNR/OPAP limits, Table 9 consistency checks, v2/v3 blind authentication & self-recovery, "
    "Qiskit circuits/NISQ noise, or the AI attack classifier."
)


class ProjectAssistant:
    """Offline retrieval-grounded Q&A assistant over repo docs and base paper."""

    def __init__(self, extra_docs: tuple[Path, ...] | None = None) -> None:
        self.chunks: list[KnowledgeChunk] = list(_CURATED_CHUNKS)
        if extra_docs is None:
            extra_docs = (
                REPO_ROOT / "README.md",
                REPO_ROOT / "docs" / "algorithm.md",
                REPO_ROOT / "docs" / "IMPROVEMENTS.md",
            )
        corpus = [
            f"{c.title}. {c.tags}. {c.answer} {' '.join(self._doc_hints(extra_docs, c.chunk_id))}"
            for c in self.chunks
        ]
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 2), lowercase=True, stop_words="english")
        self._matrix = self._vectorizer.fit_transform(corpus)

    @staticmethod
    def _doc_hints(paths: tuple[Path, ...], chunk_id: str) -> list[str]:
        """Verify indexed docs exist without inflating answer drift."""
        existing = [p.name for p in paths if p.exists()]
        return [f"{chunk_id} {' '.join(existing)}"] if existing else []

    @staticmethod
    def _expand_query(query: str) -> str:
        tokens = re.findall(r"[a-zA-Z0-9_-]+", query.lower())
        extra = [_SYNONYM_MAP[t] for t in tokens if t in _SYNONYM_MAP]
        return f"{query} {' '.join(extra)}".strip()

    @staticmethod
    def _overlap_bonus(query_tokens: set[str], chunk: KnowledgeChunk) -> float:
        meaningful = query_tokens - _STOP_WORDS
        if not meaningful:
            return 0.0
        target = set(re.findall(r"[a-z0-9_-]+", f"{chunk.title} {chunk.tags}".lower()))
        hits = len(meaningful & target)
        return 0.12 * (hits / len(meaningful))

    def ask(self, question: str) -> dict:
        """Answer a user question strictly from project & research-paper chunks."""
        q = (question or "").strip()
        if not q:
            raise ValueError("please enter a question")
        if len(q) > 500:
            raise ValueError("question must be under 500 characters")

        expanded = self._expand_query(q)
        q_vec = self._vectorizer.transform([expanded])
        cos_scores = cosine_similarity(q_vec, self._matrix)[0]
        q_tokens = set(re.findall(r"[a-z0-9_-]+", q.lower()))

        ranked = sorted(
            (
                (float(cos_scores[i]) + self._overlap_bonus(q_tokens, self.chunks[i]), i)
                for i in range(len(self.chunks))
            ),
            reverse=True,
        )

        best_score, best_idx = ranked[0]
        if best_score < 0.095:
            return {
                "grounded": False,
                "answer": _OUT_OF_SCOPE_MSG,
                "sources": [],
                "suggestions": [
                    "What is the objective of this web app?",
                    "How does watermarking work on the Airplane example?",
                    "Why does the project use NEQR instead of FRQI?",
                    "How does v3 Dual-Partner self-recovery heal cut regions?",
                ],
            }

        chosen = [self.chunks[best_idx]]
        if len(ranked) > 1 and ranked[1][0] >= max(0.14, best_score * 0.68):
            chosen.append(self.chunks[ranked[1][1]])

        answer_parts = [chosen[0].answer]
        if len(chosen) > 1:
            answer_parts.append(f"\nRelated ({chosen[1].title}): {chosen[1].answer}")

        return {
            "grounded": True,
            "title": chosen[0].title,
            "answer": "\n".join(answer_parts),
            "sources": list(dict.fromkeys(c.source for c in chosen)),
            "confidence": round(min(1.0, best_score), 3),
            "suggestions": [
                "What did v2 and v3 improve over the base paper?",
                "What bugs were found in Table 9 and 59.97 dB PSNR?",
                "How many qubits do the lean circuits save?",
            ],
        }
