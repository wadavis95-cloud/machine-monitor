# Cap the training target at 125 cycles

Early sensor readings give little evidence of exactly how far away failure is. We cap the training target at 125 cycles so the models learn the same target whenever failure is more than 125 cycles away. The dashboard can show about 125 cycles left for a healthy engine even when its true remaining life is longer, since displayed estimates are capped at 125. The results report includes error against both capped and uncapped test labels. [Design](../superpowers/specs/2026-11-21-rul-prediction-design.md#data) · [Results](../../reports/rul_results.md)
