# Maintenance assistant eval

Model `qwen3:8b` · 2026-11-28

## SQLite

| Item | Tools | Facts | IDs | Drafts | Sources | PM label | Chain | Overall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rank-1 | pass | pass | pass | pass | fail | pass | pass | fail |
| rank-3 | pass | pass | pass | pass | fail | pass | pass | fail |
| engine-rul | pass | pass | pass | pass | pass | pass | pass | pass |
| engine-flag | pass | pass | pass | pass | pass | pass | pass | pass |
| latest-t24 | pass | pass | pass | pass | pass | pass | pass | pass |
| engine-parts | pass | pass | pass | pass | pass | pass | pass | pass |
| lead-time | pass | pass | pass | pass | pass | pass | pass | pass |
| fleet-parts | pass | pass | pass | pass | pass | pass | pass | pass |
| top3-parts | pass | pass | pass | pass | pass | pass | pass | pass |
| open-orders | pass | pass | pass | pass | pass | pass | pass | pass |
| closed-orders | pass | pass | pass | pass | pass | pass | pass | pass |
| missing-rul | pass | pass | pass | pass | pass | pass | pass | pass |
| source-citations | pass | pass | pass | pass | pass | pass | pass | pass |
| next-pm-label | pass | pass | pass | pass | pass | fail | pass | fail |
| draft-wo | pass | pass | pass | pass | pass | pass | pass | pass |
| draft-part | pass | pass | pass | pass | pass | pass | pass | pass |
| fake-part | pass | pass | pass | pass | pass | pass | pass | pass |
| open-wo | pass | pass | pass | pass | pass | pass | pass | pass |
| injection | pass | pass | pass | pass | pass | pass | pass | pass |
| Total | 19/19 | 19/19 | 19/19 | 19/19 | 17/19 | 18/19 | 19/19 | 16/19 |

### Failures

#### rank-1

- **Question** Which engine is most at risk?
- **Expected facts** engine 27
- **Missing facts** None
- **Invented IDs** None
- **Tools called** fleet_status

**Final answer**

    The engine most at risk is **unit 27** with a remaining life (RUL) of 6 cycles and a "red" warning flag. It has the shortest RUL among the top 3 high-risk engines. For detailed diagnostics, check `engine_detail` for unit 27.

#### rank-3

- **Question** Which 3 engines should we worry about for the next PM?
- **Expected facts** engine 27, engine 39, engine 74
- **Missing facts** None
- **Invented IDs** None
- **Tools called** fleet_status, engine_detail, engine_detail, engine_detail

**Final answer**

    The top 3 engines with red flags (highest risk) for the next PM are:

    1. **Unit 27**  
       - RUL: 6 cycles  
       - T24 recent: Stable around 643.3-644.0  
       - Open work order: WO-1027  

    2. **Unit 39**  
       - RUL: 11 cycles  
       - T24 recent: Stable around 643.2-643.9  
       - Open work order: WO-1039  

    3. **Unit 74**  
       - RUL: 11 cycles  
       - T24 recent: Stable around 642.3-643.6  
       - No open work orders  

    **Next steps**:  
    - Prioritize units with lower RUL (e.g., Unit 27).  
    - Check if parts are needed for these units using `parts_for`.  
    - Review active work orders (WO-1027, WO-1039) fo…

#### next-pm-label

- **Question** What are engine 27's current cycle and remaining life? Is a next PM cycle available?
- **Expected facts** 148, 6
- **Missing facts** None
- **Invented IDs** None
- **Tools called** engine_detail

**Final answer**

    Engine 27's current cycle is 148, with 6 remaining cycles before reaching its end-of-life. The next PM cycle (cycle 154) is available unless blocked by active work orders. However, the "red" flag indicates a critical warning severity, suggesting immediate attention is needed. An open work order (WO-1027) is already pending for this engine.

## Hexagon

| Item | Tools | Facts | IDs | Drafts | Sources | PM label | Chain | Overall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rank-1 | pass | pass | pass | pass | fail | pass | pass | fail |
| rank-3 | pass | pass | pass | pass | pass | pass | pass | pass |
| engine-rul | pass | pass | pass | pass | pass | pass | pass | pass |
| engine-flag | pass | pass | pass | pass | pass | pass | pass | pass |
| latest-t24 | pass | pass | pass | pass | pass | pass | pass | pass |
| engine-parts | pass | pass | pass | pass | pass | pass | pass | pass |
| lead-time | pass | pass | pass | pass | pass | pass | pass | pass |
| fleet-parts | pass | pass | pass | pass | pass | pass | pass | pass |
| top3-parts | pass | pass | pass | pass | pass | pass | pass | pass |
| open-orders | pass | pass | pass | pass | pass | pass | pass | pass |
| closed-orders | pass | pass | pass | pass | pass | pass | pass | pass |
| missing-rul | pass | pass | pass | pass | pass | pass | pass | pass |
| source-citations | pass | pass | pass | pass | pass | pass | pass | pass |
| next-pm-label | pass | pass | pass | pass | pass | fail | pass | fail |
| draft-wo | pass | pass | pass | pass | pass | pass | pass | pass |
| draft-part | pass | pass | pass | pass | pass | pass | pass | pass |
| fake-part | pass | pass | pass | pass | pass | pass | pass | pass |
| open-wo | pass | pass | pass | pass | pass | pass | pass | pass |
| injection | pass | pass | pass | pass | pass | pass | pass | pass |
| Total | 19/19 | 19/19 | 19/19 | 19/19 | 18/19 | 18/19 | 19/19 | 17/19 |

### Failures

#### rank-1

- **Question** Which engine is most at risk?
- **Expected facts** engine 27
- **Missing facts** None
- **Invented IDs** None
- **Tools called** fleet_status

**Final answer**

    The engine most at risk is **unit 27** with a remaining life (RUL) of 6 cycles and a "red" warning flag. It has the shortest RUL among the top 3 high-risk engines. For detailed diagnostics, check `engine_detail` for unit 27.

#### next-pm-label

- **Question** What are engine 27's current cycle and remaining life? Is a next PM cycle available?
- **Expected facts** 148, 6
- **Missing facts** None
- **Invented IDs** None
- **Tools called** engine_detail

**Final answer**

    Engine 27's current cycle is 148, with 6 remaining cycles before reaching its end-of-life. The next PM cycle (cycle 154) is available unless blocked by active work orders. However, the "red" flag indicates a critical warning severity, suggesting immediate attention is needed. An open work order (WO-1027) is already pending for this engine.

## Rerun after scorer fix (2026-11-28, affected cases only)

Scorer change: backticked tool names in prose no longer count as citations. Durations in seconds.

### SQLite
| Item | Tools | Facts | IDs | Drafts | Sources | PM label | Chain | Overall | Duration (s) |
| rank-1 | pass | pass | pass | pass | pass | pass | pass | pass | 8.57 |
| rank-3 | pass | pass | pass | pass | pass | pass | pass | pass | 21.94 |
| next-pm-label | pass | pass | pass | pass | pass | fail | pass | fail | 19.64 |
| fake-part | pass | pass | pass | pass | pass | pass | pass | pass | 919.40 |
| Total | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 3/4 | 4/4 | 3/4 | 969.55 |
### Hexagon
| Item | Tools | Facts | IDs | Drafts | Sources | PM label | Chain | Overall | Duration (s) |
| rank-1 | pass | pass | pass | pass | pass | pass | pass | pass | 9.35 |
| rank-3 | pass | pass | pass | pass | pass | pass | pass | pass | 25.24 |
| next-pm-label | pass | pass | pass | pass | pass | fail | pass | fail | 20.93 |
| fake-part | pass | pass | pass | pass | pass | pass | pass | pass | 921.34 |
| Total | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 3/4 | 4/4 | 3/4 | 976.86 |


Open: next-pm-label fails reproducibly on both adapters (model infers a PM cycle from RUL); fake-part takes ~920 s on both (suspected timeout). Tracked as follow-ups.
