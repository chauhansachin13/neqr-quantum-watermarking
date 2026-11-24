#!/usr/bin/env bash
# Re-generates every table and figure under results/ from scratch.
#
#   bash scripts/reproduce_all.sh            # full run (classifier: 4500 samples, 65,536 features)
#   QUICK=1 bash scripts/reproduce_all.sh    # fast smoke run
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=${OUT:-results}
IMAGES=${IMAGES:-}
EXTRA=()
if [[ -n "$IMAGES" ]]; then EXTRA=(--images "$IMAGES"); fi

echo "== worked example";               qwm demo
echo "== circuit figures";              qwm draw --out "$OUT/figures"
echo "== resource analysis";            qwm resources --out "$OUT"
echo "== imperceptibility";             qwm evaluate --out "$OUT" "${EXTRA[@]}"
echo "== robustness (lsb mode)";        qwm attacks --out "$OUT" --mode lsb "${EXTRA[@]}"
echo "== robustness (paper mode)";      qwm attacks --out "$OUT" --mode paper "${EXTRA[@]}"
echo "== quantum noise / decoherence";  qwm quantum-metrics --out "$OUT" --images "${IMAGES:-lena,baboon,peppers,camera}" --max-blocks 8
if [[ "${QUICK:-0}" == "1" ]]; then
  echo "== attack classification (quick)"; qwm classify --quick --features descriptors --out "$OUT/classifier/quick"
else
  for features in pixels descriptors; do
    for params in random table7; do
      echo "== attack classification ($features features, $params attack strengths)"
      qwm classify --features "$features" --params "$params" --out "$OUT/classifier/${features}_${params}"
    done
  done
fi
echo "== v2: consistency checks of reported numbers"; qwm paper-checks --out "$OUT/paper_checks"
echo "== v2: blind tamper localisation, forgery and self-recovery"; qwm tamper-study --out "$OUT/tamper" "${EXTRA[@]}"
if [[ "${QUICK:-0}" == "1" ]]; then
  echo "== v2: classifier benchmark (quick)"; qwm classifier-benchmark --quick --samples-per-class 60 --unseen-per-attack 20 --out "$OUT/classifier/benchmark_quick"
  echo "== v2: NISQ study (quick)";          qwm nisq --p2 1e-4,1e-3 --shots 200 --out "$OUT/nisq_quick"
else
  echo "== v2: classifier benchmark";        qwm classifier-benchmark --out "$OUT/classifier/benchmark"
  echo "== v2: NISQ study (several minutes)"; qwm nisq --out "$OUT/nisq"
fi
echo "done -> $OUT"
