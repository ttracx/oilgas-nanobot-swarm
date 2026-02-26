# Agent Teams

Pre-configured swarm teams for oil and gas engineering workflows. Each team has a tailored system prompt, tool access, and execution mode (hierarchical or flat).

---

## Team Overview

| Team | Mode | Response Time | Best For |
|------|------|--------------|----------|
| `well-engineering-review` | Hierarchical | 15–30s | Well design review |
| `reservoir-analysis` | Hierarchical | 20–45s | Reservoir characterization |
| `drilling-ops-daily` | Flat | 8–15s | Daily morning report |
| `production-optimization` | Hierarchical | 20–40s | Field surveillance |
| `pipeline-integrity` | Hierarchical | 15–30s | Integrity management |
| `hse-compliance-audit` | Hierarchical | 20–40s | HSE audits |
| `well-economics` | Hierarchical | 15–30s | Investment analysis |
| `oilgas-field-briefing` | Flat | 5–12s | Daily ops briefing |
| `completions-design` | Hierarchical | 20–40s | Frac program design |

---

## Execution Modes

**Hierarchical** — Queen → L1 Domain Leads → L2 Sub-agents. Best for complex, multi-faceted analysis requiring cross-domain synthesis.

**Flat** — Direct dispatch to specialized agents in parallel. Best for operational summaries and reporting.

---

## `well-engineering-review`

Comprehensive well engineering review covering casing design, pressure analysis, and regulatory compliance.

**When to use**: New well planning, pre-APD review, engineering design verification

**Coverage**:
- ECD verification for all hole sections
- Kick tolerance at each casing point
- MAASP calculation for all casing strings
- Mud weight window adequacy check
- Completion design vs. IPR matching
- API/BSEE regulatory compliance check

**Example**:
```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Review vertical well: TD 12,500 ft TVD. Sections: 20\" @ 500ft (FG 10.5 ppg), 13-3/8\" @ 3,200ft (FG 12.1 ppg), 9-5/8\" @ 8,200ft (FG 14.2 ppg). Target MD 10.5 ppg. Verify ECD, kick tolerance, MAASP.",
    "team": "well-engineering-review"
  }'
```

---

## `reservoir-analysis`

Reservoir characterization from log data and production tests.

**Coverage**:
- Archie water saturation from resistivity logs
- Sonic porosity (Wyllie time-average)
- Shale volume from GR log
- Net pay determination
- Vogel IPR curve generation (11 points)
- Productivity Index calculation
- Reserve estimate (volumetric OOIP)
- Artificial lift timing recommendation

**Example**:
```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Reservoir analysis for Well A-3. Log data: GR=45 API (clean=20, shale=120), sonic Δt=88 µs/ft (sandstone), Rt=12.5 ohm-m, Rw=0.04 ohm-m. Production test: Pr=3200 psi, Pwf=1800 psi, q=650 BOPD.",
    "team": "reservoir-analysis"
  }'
```

---

## `drilling-ops-daily`

Daily drilling operations report covering depth, ROP, mud program, costs, and well control status.

**Format**: Concise briefing for 7am morning meeting / NOC handover

**Coverage**:
- 24-hour footage and ROP
- Running AFE vs. actual cost
- NPT categories and durations
- Mud weight changes and ECD status
- Gas shows and background gas
- BHA and bit status
- Next 24-hour forecast

**Example**:
```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Daily drilling report: Current depth 9,450 ft MD (9,200 ft TVD). Drilled 285 ft last 24 hrs. Average ROP 35 ft/hr. MW 10.5 ppg. Day 18 of 45-day AFE. No incidents. BHA: PDC bit, MWD/LWD, mud motor.",
    "team": "drilling-ops-daily"
  }'
```

---

## `production-optimization`

Production surveillance and optimization recommendations.

**Coverage**:
- Current vs. theoretical IPR performance
- Artificial lift optimization (ESP, gas lift, rod pump)
- Decline curve analysis
- High water cut well screening
- Facility capacity vs. throughput
- Injection well capacity and VRR
- Economic screening ($/BOE incremental)

**Example**:
```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Production optimization for 12-well field. Average WC 65%, PI 0.45 bopd/psi, reservoir pressure 2,800 psi. 3 wells on ESP, 5 on gas lift, 4 flowing naturally. Gross rate 8,200 BOPD. Identify top 3 optimization candidates.",
    "team": "production-optimization"
  }'
```

---

## `pipeline-integrity`

Pipeline integrity management per DOT/API standards.

**Coverage**:
- Pressure drop and hydraulic adequacy
- Flow regime and erosional velocity check (API 14E)
- MAOP verification
- Corrosion rate assessment
- ILI anomaly risk ranking (API 1160/1176)
- ASME B31G fitness-for-service
- Cathodic protection status
- Regulatory compliance (DOT 49 CFR 192/195)

**Example**:
```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Pipeline integrity: 8-inch crude oil line, 26 miles, MAOP 750 psi, flow 15,000 BOPD, CO2 partial pressure 12 psi, no inhibitor injection. MFL ILI ran 2 years ago — 3 anomalies > 50% WT loss identified.",
    "team": "pipeline-integrity"
  }'
```

---

## `hse-compliance-audit`

HSE compliance review against OSHA PSM, BSEE SEMS, and EPA requirements.

**Coverage**:
- OSHA 29 CFR 1910.119 — all 14 PSM elements
- BSEE SEMS audit readiness
- Well integrity barriers (NORSOK D-010)
- EPA Quad O LDAR program
- Incident investigation methodology (TapRoot, 5-Why, Bow-Tie)
- Process safety KPIs (TRIR, LTIR, LOPC)
- Risk rating: RED/AMBER/GREEN

**Example**:
```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "HSE compliance audit for offshore platform. Last PSM audit 2 years ago. Known gaps: MOC process not consistently applied, PHA not updated after last modification, LDAR program 18 months overdue. Rate each finding and provide corrective action plan.",
    "team": "hse-compliance-audit"
  }'
```

---

## `well-economics`

Capital investment analysis and economic screening.

**Coverage**:
- AFE cost build-up
- Production forecast from Vogel AOF
- Arps decline curve (exponential/hyperbolic)
- EUR calculation
- Net revenue after royalties and taxes
- NPV at 10% discount rate (PV10)
- IRR and payback period
- Break-even oil price ($/bbl)
- P10/P50/P90 sensitivity

**Example**:
```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Well economics: $4.2M AFE, 800 BOPD IP rate, hyperbolic decline b=1.2, Di=65%/yr, 45° terminal decline, $70/bbl flat oil price, 80% NRI, 7.5% severance tax. Calculate NPV10, IRR, payout, EUR, and break-even.",
    "team": "well-economics"
  }'
```

---

## `oilgas-field-briefing`

Daily field operations briefing — concise, ready for 7am meeting.

**Format**: Production summary, safety status, well status, facility status, market snapshot, 24-hour plan

**Example**:
```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Daily field briefing for Permian Basin Block 4. Production: 8,200 BOPD oil, 14.5 MMSCFD gas, 22,000 BWPD. 2 wells shut-in for ESP replacement (Well A-7, B-3). Separator 2 offline for maintenance. WTI $71.50/bbl.",
    "team": "oilgas-field-briefing"
  }'
```

---

## `completions-design`

Hydraulic fracturing and completion engineering.

**Coverage**:
- Stage count and spacing optimization
- Perforation cluster design (limited entry)
- Fluid selection (slickwater vs. crosslinked gel)
- Proppant type and mesh size
- Treatment schedule (pad + proppant ramp)
- Pump rate and treating pressure
- EUR projection vs. stage count
- Cost-benefit analysis

**Example**:
```bash
curl -X POST https://oilgas-nanobot-swarm.vibecaas.app/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Completions design for Wolfcamp A horizontal: 8,500 ft lateral, closure stress 500 Mpa, ISIP 0.72 psi/ft, brittleness index 65%. Target 2,000 BOPD IP. Design stage count, cluster spacing, fluid and proppant program.",
    "team": "completions-design"
  }'
```

---

## Registering Custom Teams

Add your own teams in `nanobot/teams/`:

```python
from nanobot.scheduler.agent_teams import AgentTeam, register_team

register_team(AgentTeam(
    name="my-custom-team",
    description="Description for the dashboard",
    mode="hierarchical",  # or "flat"
    system_prompt="""You are... [detailed role description]

    Workflow:
    1. Step one...
    2. Step two...
    """,
    inject_knowledge=True,
    update_knowledge_after=True,
    max_tokens=4096,
    temperature=0.1,
))
```
