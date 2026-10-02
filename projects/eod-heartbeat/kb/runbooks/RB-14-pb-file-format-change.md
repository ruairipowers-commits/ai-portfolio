---
id: RB-14
title: Prime broker file format change
break_types: [missing_file, position_break]
hints: [format]
owner: fund-operations
---

# RB-14 Prime broker file format change

## Symptoms
The prime-broker file arrives but loads zero rows, or columns are shifted.

## Likely causes
- The broker added, renamed or reordered columns without notice.

## Steps
1. Compare the file header with the expected header in the loader.
2. Ask the broker to confirm the change and the effective date.
3. Update the loader mapping through a reviewed change, then reload the date.

## Escalation
If the mapping can't be fixed before cutoff, the ops lead decides whether to use the broker portal export.
