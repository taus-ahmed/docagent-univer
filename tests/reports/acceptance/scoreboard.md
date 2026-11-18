# Acceptance scoreboard

| Run | State | Expected | Correct | Wrong | Missing | Silent | False flags | Approve-only |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| flowparse_bank_us | READY | 29 | 7 | 2 | 20 | 16 | 0 | no |
| flowparse_po | READY | 18 | 18 | 0 | 0 | 0 | 1 | no |
| irs_w2_mod11 | READY | 13 | 1 | 0 | 12 | 12 | 1 | no |
| irs_1099nec_ellis | READY | 8 | 1 | 0 | 7 | 7 | 0 | no |
| **Total** |  | **68** | **27** | **2** | **39** | **35** | **2** | **0 run(s)** |

Gate: FAIL

- flowparse_bank_us: 16 silent defect(s)
- flowparse_bank_us: READY with 20 missing value(s)
- irs_w2_mod11: 12 silent defect(s)
- irs_w2_mod11: READY with 12 missing value(s)
- irs_1099nec_ellis: 7 silent defect(s)
- irs_1099nec_ellis: READY with 7 missing value(s)
