#!/usr/bin/env bash
set +e

if ! command -v sccache &>/dev/null || [ "${RUSTC_WRAPPER:-}" != "sccache" ]; then
  echo "sccache not enabled, skipping statistics"
  exit 0
fi

echo "=== sccache Statistics ==="
sccache_output=$(sccache --show-stats 2>&1 || echo "ERROR")
echo "$sccache_output"

# Parse and display metrics
if echo "$sccache_output" | grep -q "Cache hits"; then
  hits=$(echo "$sccache_output" | grep "Cache hits" | head -1 | awk '{print $3}' | tr -dc '0-9' || true)
  misses=$(echo "$sccache_output" | grep "Cache misses" | head -1 | awk '{print $3}' | tr -dc '0-9' || true)
  hits=${hits:-0}
  misses=${misses:-0}
  total=$((hits + misses))

  if [ "$total" -gt 0 ]; then
    hit_rate=$((hits * 100 / total))
    echo "Hit Rate: ${hit_rate}%"

    if [ "$hit_rate" -lt 20 ]; then
      echo "Very low hit rate"
    elif [ "$hit_rate" -lt 50 ]; then
      echo "Moderate hit rate"
    else
      echo "Good hit rate"
    fi

    # Write to job summary
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
      echo "### sccache: ${hit_rate}% hit rate ($hits hits, $misses misses)" >>"$GITHUB_STEP_SUMMARY"
    fi
  fi
fi

exit 0
