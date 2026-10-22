#!/bin/sh
# Run modules whose host coverage depends on Linux tools or the image Python.
# shellcheck source=tests/lib.sh
. "$(dirname "$0")/lib.sh"
repo=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck disable=SC2016 # expands inside the container
out=$(run_in --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$repo:/repo:ro" --entrypoint sh -- -ec '
for module in test_doctor.py test_seed_atomic.py test_home_concurrency.py test_agents_versions.py test_tools_reset.py test_startup_paths.py test_tools_stamp.py test_launcher_paths.py; do
  python3 -I -B -m unittest discover -s /repo/tests/unit -p "$module"
done
printf "LINUX_UNITS_VERIFIED\n"' 2>&1)
rc=$?
assert_eq "Linux unit modules pass" 0 "$rc"
if [ "$rc" = 0 ]; then
	assert_contains "Linux unit modules completed" LINUX_UNITS_VERIFIED "$out"
else
	printf '%s\n' "$out"
fi
finish
