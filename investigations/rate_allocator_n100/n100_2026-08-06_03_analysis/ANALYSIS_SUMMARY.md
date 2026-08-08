# Paired n=100 rate-allocator analysis

The sealed campaign contains 13,400 paired jobs (26,800 simulations), with 100
paired samples in each of 134 arms. All 13,400 legacy halves reproduce their
frozen references exactly in binary64.

## Main model-sensitivity result

Across the 32 matched equal/proportional cells, the network-wide allocator
multiplies the proportional policy's advantage by **1.028654**
(seed-clustered 95% bootstrap CI **[1.027142,
1.030205]**). The cluster is the sample ID: all 32 cells stay
together in every bootstrap draw. At the cell level, 23 geometric effects are
above one, nine are exactly one, and none is below one. Cell intervals are
pointwise and have no multiplicity correction; the clustered headline is the
primary inference.

The mechanism is concrete: all 4,800 static equal-split pairs are bit-identical
between allocators, while network max-min improves 1,036 of 3,200 proportional
pairs and is bit-identical in the other 2,164. Thus the legacy link-local model
masked part of proportional splitting's benefit rather than creating it.

## Frozen-controller boundary

The frozen adaptive controller is diagnostic only. It is slower under max-min
in 84 of 800 pairs; 70
of those slower pairs also change the number of adaptive events. Across all 800
pairs, 523 change event count. This is
evidence that allocator and controller decisions are coupled, so a fair method
comparison requires recalibration on disjoint seeds before evaluation.

## Runtime and next gate

The measured eight-worker n=100 pool time is
28.49 minutes. A linear same-matrix
n=1000 planning projection is
4.75
hours; it is not a confidence interval. No n=1000 run was started. The next
scientific gate is controller recalibration on separate seeds, followed by an
Ibrahem decision on the production n=1000 scope.
