#!/usr/bin/env bash
# Re-generates every table and figure under results/ from scratch.
#
#   bash scripts/reproduce_all.sh                      # full run (4500 samples, 65,536 features)
#   QUICK=1 OFFLINE=1 bash scripts/reproduce_all.sh    # fast offline smoke run
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=${OUT:-results}
IMAGES=${IMAGES:-}
EXTRA=()
if [[ -n "$IMAGES" ]]; then EXTRA=(--images "$IMAGES"); fi
if [[ "${OFFLINE:-0}" == "1" ]]; then EXTRA+=(--offline); fi

FIRST_IMAGE=${IMAGES%%,*}
echo "== one-command overview"
if [[ -n "$FIRST_IMAGE" ]]; then
  qwm run --image "$FIRST_IMAGE"
else
  qwm run
fi
echo "== worked example";               qwm demo
echo "== circuit figures";              qwm draw --out "$OUT/figures"
echo "== resource analysis";            qwm resources --out "$OUT"
echo "== imperceptibility";             qwm evaluate --out "$OUT" ${EXTRA[@]+"${EXTRA[@]}"}
echo "== robustness (lsb mode)";        qwm attacks --out "$OUT" --mode lsb ${EXTRA[@]+"${EXTRA[@]}"}
echo "== robustness (paper mode)";      qwm attacks --out "$OUT" --mode paper ${EXTRA[@]+"${EXTRA[@]}"}
echo "== quantum noise / decoherence";  qwm quantum-metrics --out "$OUT" --images "${IMAGES:-camera,coins}" --max-blocks 8
if [[ "${QUICK:-0}" == "1" ]]; then
  echo "== attack classification (quick)"; qwm classify --quick --features descriptors_v2 --out "$OUT/classifier/quick" ${EXTRA[@]+"${EXTRA[@]}"}
else
  for features in pixels descriptors descriptors_v2; do
    for params in random table7; do
      echo "== attack classification ($features features, $params attack strengths)"
      qwm classify --features "$features" --params "$params" --out "$OUT/classifier/${features}_${params}" ${EXTRA[@]+"${EXTRA[@]}"}
    done
  done
fi
echo "== v2: consistency checks of reported numbers"; qwm paper-checks --out "$OUT/paper_checks"
echo "== v2: blind tamper localisation, forgery and self-recovery"; qwm tamper-study --out "$OUT/tamper" ${EXTRA[@]+"${EXTRA[@]}"}
echo "== v3: NEQR superposition & Grover tamper search"; qwm superposition --image camera --shots 256
if [[ "${QUICK:-0}" == "1" ]]; then
  echo "== v2/v3: classifier benchmark (quick)"; qwm classifier-benchmark --quick --samples-per-class 60 --unseen-per-attack 20 --out "$OUT/classifier/benchmark_quick"
  echo "== v2/v3: NISQ + thermal study (quick)"; qwm nisq --shallow --thermal --p2 1e-4,1e-3 --shots 200 --out "$OUT/nisq_quick"
else
  echo "== v2/v3: classifier benchmark";          qwm classifier-benchmark --out "$OUT/classifier/benchmark"
  echo "== v2/v3: NISQ + thermal study";          qwm nisq --shallow --thermal --out "$OUT/nisq"
fi
echo "done -> $OUT"
