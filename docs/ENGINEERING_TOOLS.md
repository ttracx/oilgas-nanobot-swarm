# Engineering Tools Reference

OilGas Nanobot Swarm includes 7 built-in petroleum engineering calculators. All agents have access to these tools during task execution. They can also be invoked directly by describing the calculation in your goal.

---

## 1. `reservoir_pressure_calc`

Reservoir pressure calculations for well planning and completion design.

### Calculation Types

| Type | Description |
|------|-------------|
| `hydrostatic_gradient` | Pressure gradient from fluid density |
| `bhp_from_wellhead` | Static BHP from wellhead pressure + mud weight |
| `pore_pressure` | Normal pore pressure estimate |
| `fracture_gradient` | Hubbert & Willis fracture gradient |
| `pressure_gradient_from_density` | Convert ppg to psi/ft |

### Fracture Gradient (Hubbert & Willis 1957)

```
FG = (ν / (1-ν)) × (OBG - PP) + PP
```

| Parameter | Symbol | Units |
|-----------|--------|-------|
| Poisson's ratio | ν | dimensionless |
| Overburden gradient | OBG | psi/ft |
| Pore pressure gradient | PP | psi/ft |

### Example Request

```
Goal: "Calculate fracture gradient at 10,000 ft TVD.
       Overburden gradient: 0.98 psi/ft,
       Mud weight: 9.5 ppg (pore pressure equivalent),
       Poisson's ratio: 0.27"
```

### Example Response

```
Fracture Gradient (Hubbert & Willis)
TVD:                     10,000 ft
Overburden gradient:     0.98 psi/ft
Pore pressure gradient:  0.4940 psi/ft
Poisson's ratio:         0.27
Fracture gradient:       0.7194 psi/ft  →  13.84 ppg EMW
```

---

## 2. `drilling_engineering_calc`

Drilling fluid and wellbore pressure calculations.

### Calculation Types

| Type | Description | Key Formula |
|------|-------------|-------------|
| `ecd` | Equivalent Circulating Density | `ECD = MW + APL / (0.052 × TVD)` |
| `kick_tolerance` | Maximum kick before fracturing shoe | `KT = FG - MW (ppg)` |
| `mud_weight_window` | Safe drilling margin | `Window = FG - PP (ppg)` |
| `surge_swab` | Pressure change from pipe movement | Bingham plastic model |
| `casing_seat` | Minimum depth for casing shoe | Based on pore pressure ramp |

### ECD Formula

```
ECD (ppg) = MW (ppg) + APL (psi) / (0.052 × TVD (ft))
```

### Example

```
Goal: "Calculate ECD for 10.5 ppg mud at 9,800 ft TVD with 350 psi annular pressure loss"

Result:
  Mud weight:              10.5 ppg
  Annular pressure loss:   350 psi
  TVD:                     9,800 ft
  ECD:                     11.19 ppg
```

### Mud Weight Window Status

| Window (ppg) | Status |
|-------------|--------|
| < 1.5 | NARROW — high risk |
| 1.5 – 3.0 | ADEQUATE |
| > 3.0 | WIDE — good margin |

---

## 3. `production_engineering_calc`

Well inflow performance and production optimization.

### Calculation Types

| Type | Description | Reference |
|------|-------------|-----------|
| `productivity_index` | PI = q / (Pr - Pwf) | Darcy (1856) |
| `vogel_ipr` | Full IPR curve (11 points) | Vogel (1968) |
| `darcy_flow` | Radial flow rate estimate | Darcy's law |
| `artificial_lift_selection` | ESP/Gas Lift/Rod Pump guidance | Rules-based |

### Vogel IPR Equation (1968)

```
q/q_max = 1 - 0.2(Pwf/Pr) - 0.8(Pwf/Pr)²
```

Rearrange to find q_max (AOF) from one measured data point:
```
q_max = q_measured / (1 - 0.2(Pwf/Pr) - 0.8(Pwf/Pr)²)
```

### Darcy Radial Flow (Oil)

```
q (BOPD) = k·h·ΔP / (141.2 × μ × Bo × (ln(re/rw) - 0.75 + S))
```

### Artificial Lift Selection Guide

| Condition | Recommended |
|-----------|-------------|
| WC > 80%, high rate | ESP |
| High GLR, offshore | Gas Lift |
| Shallow, moderate rate, WC < 50% | Rod Pump |
| Deepwater/subsea | ESP or Gas Lift |

---

## 4. `pipeline_hydraulics_calc`

Surface and subsea pipeline pressure and flow calculations.

### Calculation Types

| Type | Formula |
|------|---------|
| `pressure_drop` | Darcy-Weisbach: ΔP = f(L/D)(ρv²/2) |
| `flow_regime` | Reynolds number Re = ρvD/μ |
| `line_sizing` | Min ID for target velocity (4 ft/s liquid) |
| `gas_flow_rate` | Weymouth/Panhandle equation |

### Darcy-Weisbach Pressure Drop

```
ΔP (psi) = f × (L/D) × (ρv²/2) / 144
```

Friction factor (Swamee-Jain explicit):
```
f = 0.25 / [log10(ε/(3.7D) + 5.74/Re^0.9)]²
```

### Flow Regimes

| Reynolds Number | Regime |
|----------------|--------|
| Re < 2,300 | Laminar |
| 2,300 – 4,000 | Transitional |
| Re > 4,000 | Turbulent |

### Erosional Velocity (API 14E)

```
Ve = C / √ρ
```
- C = 100 (continuous service)
- C = 150 (intermittent service)

---

## 5. `well_control_calc`

Well control calculations for kill operations and pressure management.

### Calculation Types

| Type | Formula |
|------|---------|
| `maasp` | MAASP = (FG - MW) × 0.052 × Dshoe |
| `kill_mud_weight` | KMW = MW + SIDPP / (0.052 × TVD) |
| `driller_method_pressure` | Kill schedule, ICP, FCP |

### Kill Mud Weight (Driller's Method)

```
KMW (ppg) = MW + SIDPP / (0.052 × TVD)
```

Add 0.3 ppg safety margin for operations.

### MAASP

```
MAASP (psi) = (FG - MW) × 0.052 × Dshoe
```

**CRITICAL**: Compare SICP to MAASP immediately after shut-in. If SICP > MAASP, initiate emergency well control procedures.

---

## 6. `formation_evaluation_calc`

Petrophysics and log interpretation calculations.

### Calculation Types

| Type | Formula | Reference |
|------|---------|-----------|
| `water_saturation_archie` | Sw^n = (a·Rw)/(φ^m·Rt) | Archie (1942) |
| `porosity_sonic` | φ = (Δt_log - Δt_ma)/(Δt_fl - Δt_ma) | Wyllie (1956) |
| `shale_volume` | Vsh = IGR = (GR - GRmin)/(GRmax - GRmin) | Linear |
| `permeability_timur` | k = 0.136×φ^4.4/Swi² | Timur (1968) |

### Archie's Equation (1942)

```
Sw^n = (a × Rw) / (φ^m × Rt)
```

| Parameter | Typical Sandstone | Typical Carbonate |
|-----------|------------------|-------------------|
| a | 1.0 | 1.0 |
| m | 2.0 | 2.0 |
| n | 2.0 | 2.0 |

### Net Pay Cutoffs (Typical)

| Parameter | Cutoff |
|-----------|--------|
| Porosity (φ) | > 0.08 (8%) |
| Water Saturation (Sw) | < 0.60 (60%) |
| Shale Volume (Vsh) | < 0.35 (35%) |

### Matrix Transit Times (Sonic)

| Lithology | Δtma (µs/ft) |
|-----------|-------------|
| Sandstone | 55.5 |
| Limestone | 47.6 |
| Dolomite | 43.5 |

---

## 7. `oilgas_regulatory_reference`

Regulatory standards and compliance reference tool.

### Query Types

| Type | Covers |
|------|--------|
| `api_standards` | API 6A, 7-1, 10A, 16A, 17D, 570, 620/650, 2000 |
| `bsee_offshore` | 30 CFR 250, SEMS, Well Control Rule, OCSLA |
| `osha_psm` | 29 CFR 1910.119 — all 14 PSM elements |
| `epa_emissions` | Quad O, LDAR, GHGRP Subpart W |
| `international_standards` | NORSOK D-010, ISO 16530 |
| `well_integrity` | NORSOK D-010, API 90-1/90-2, barrier philosophy |
| `process_safety` | TRIR, LOPC, Bow-tie methodology |

### OSHA PSM 14 Elements

1. Process Safety Information (PSI)
2. Process Hazard Analysis (PHA/HAZOP)
3. Operating Procedures
4. Training
5. Contractors
6. Pre-Startup Safety Review (PSSR)
7. Mechanical Integrity
8. Hot Work Permit
9. Management of Change (MOC)
10. Incident Investigation
11. Emergency Planning and Response
12. Compliance Audits
13. Trade Secrets
14. Employee Participation

---

> **⚠️ DISCLAIMER**: All tool outputs are for reference only. Engineering decisions must be verified by licensed petroleum engineers against current codes and site-specific conditions.
