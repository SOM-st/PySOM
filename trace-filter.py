# This script will remove things from the input that make it harder to diff
# traces.
#
# To generate a trace, for instance run:
#  PYPYLOG=jit-log-opt:List-new.log ./som-ast-jit -cp Smalltalk:Examples/Benchmarks/LanguageFeatures Examples/Benchmarks/BenchmarkHarness.som List 65 0  100
#
# Afterwards, the file can be filtered, for instance with:
#  cat List-new.log | python trace-filter.py > List-new.log-filtered
#
import fileinput
import sys

import re

pointer = re.compile("0x[0-9a-f]{9,12}")
target_token = re.compile("TargetToken\\([0-9]*\\)")
address = re.compile("\\[[0-9a-f]{8,12}]")
line_num = re.compile("^\\+\\d*:")
long_number = re.compile("\\d{8,}")

for line in fileinput.input():
    filtered_line = re.sub(pointer, "(ptr)", line)
    filtered_line = re.sub(target_token, "TargetToken(tkn)", filtered_line)
    filtered_line = re.sub(address, "[adr]", filtered_line)
    filtered_line = re.sub(line_num, "", filtered_line)
    filtered_line = re.sub(long_number, "(num)", filtered_line)

    sys.stdout.write(filtered_line)
