# Unit 2A figure gate

**Status: PASS**

| Check | Result | Evidence |
|---|---|---|
| Artist geometry/data | PASS | Exact parsed-JSON equality for both figures |
| Rendered labels | PASS | 3 observed; 3 exact substitutions approved |
| Other rendered text boxes | PASS | Unchanged labels retain exact bounding boxes; approved labels exempt |
| `fig_gap_closure.pdf` | PASS | boxes=True; drawings=True; fonts=True |
| `fig_gap_closure.png` | PASS | 1035×630 `RGBA` |
| `fig_saturation.pdf` | PASS | boxes=True; drawings=True; fonts=True |
| `fig_saturation.png` | PASS | 2148×765 `RGBA` |

Only the three approved rendered strings changed; plotted geometry, data, page boxes, vector drawings, font inventory, and PNG dimensions are unchanged.
