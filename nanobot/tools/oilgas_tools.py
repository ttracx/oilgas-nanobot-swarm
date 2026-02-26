"""
Oil & Gas Engineering Tools — specialized calculations and data lookups
for upstream, midstream, and downstream operations.

Covers:
- Reservoir engineering (pressure, volume, flow rate)
- Drilling engineering (mud weight, pore pressure, equivalent circulating density)
- Production engineering (artificial lift, well performance)
- Pipeline hydraulics (pressure drop, flow regime)
- Equipment sizing and specification lookups
- Safety and regulatory compliance checks
"""

import math
import time
from nanobot.tools.base import BaseTool, ToolResult


# ── Reservoir Engineering ─────────────────────────────────────────────────────

class ReservoirPressureCalcTool(BaseTool):
    """Calculate reservoir pressure, material balance, and drive mechanisms."""

    name = "reservoir_pressure_calc"
    description = (
        "Calculate reservoir pressure parameters. Supports: hydrostatic gradient, "
        "BHP from wellhead pressure, pore pressure from overburden, and abnormal "
        "pressure detection. Essential for well planning and completion design."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "calc_type": {
                "type": "string",
                "enum": [
                    "hydrostatic_gradient",
                    "bhp_from_wellhead",
                    "pore_pressure",
                    "fracture_gradient",
                    "pressure_gradient_from_density",
                ],
                "description": "Type of pressure calculation",
            },
            "fluid_density_ppg": {
                "type": "number",
                "description": "Fluid density in pounds per gallon (ppg)",
            },
            "depth_ft": {
                "type": "number",
                "description": "True vertical depth in feet",
            },
            "wellhead_pressure_psi": {
                "type": "number",
                "description": "Wellhead pressure in psi (for BHP calculation)",
            },
            "overburden_gradient_psi_ft": {
                "type": "number",
                "description": "Overburden gradient in psi/ft (default: 1.0 psi/ft)",
            },
            "poisson_ratio": {
                "type": "number",
                "description": "Poisson's ratio for fracture gradient (default: 0.25)",
            },
        },
        "required": ["calc_type", "depth_ft"],
    }

    async def run(
        self,
        calc_type: str,
        depth_ft: float,
        fluid_density_ppg: float = 8.33,
        wellhead_pressure_psi: float = 0.0,
        overburden_gradient_psi_ft: float = 1.0,
        poisson_ratio: float = 0.25,
        **kwargs,
    ) -> ToolResult:
        start = time.time()
        try:
            results = {}

            if calc_type == "hydrostatic_gradient":
                # P = 0.052 × ρ × TVD
                gradient_psi_ft = 0.052 * fluid_density_ppg
                pressure_psi = gradient_psi_ft * depth_ft
                results = {
                    "fluid_density_ppg": fluid_density_ppg,
                    "depth_ft": depth_ft,
                    "pressure_gradient_psi_ft": round(gradient_psi_ft, 4),
                    "hydrostatic_pressure_psi": round(pressure_psi, 2),
                    "hydrostatic_pressure_kpa": round(pressure_psi * 6.89476, 2),
                    "formula": "P = 0.052 × ρ (ppg) × TVD (ft)",
                }

            elif calc_type == "bhp_from_wellhead":
                # BHP = WHP + hydrostatic head + friction losses (simplified)
                hydrostatic = 0.052 * fluid_density_ppg * depth_ft
                bhp = wellhead_pressure_psi + hydrostatic
                results = {
                    "wellhead_pressure_psi": wellhead_pressure_psi,
                    "hydrostatic_head_psi": round(hydrostatic, 2),
                    "estimated_bhp_psi": round(bhp, 2),
                    "bhp_kpa": round(bhp * 6.89476, 2),
                    "note": "Static BHP estimate; dynamic BHP requires friction loss data",
                }

            elif calc_type == "pore_pressure":
                # Matthews & Kelly method (simplified)
                normal_gradient = 0.433  # psi/ft (freshwater)
                normal_pp = normal_gradient * depth_ft
                results = {
                    "depth_ft": depth_ft,
                    "normal_pore_pressure_psi": round(normal_pp, 2),
                    "normal_gradient_psi_ft": normal_gradient,
                    "equivalent_mud_weight_ppg": round(normal_gradient / 0.052, 2),
                    "note": "Normal gradient estimate (0.433 psi/ft). Use well logs for actual pore pressure.",
                }

            elif calc_type == "fracture_gradient":
                # Hubbert & Willis method: FG = (ν/(1-ν)) × (OBG - PP) + PP
                pore_pressure_gradient = 0.052 * fluid_density_ppg
                fg = (poisson_ratio / (1 - poisson_ratio)) * (
                    overburden_gradient_psi_ft - pore_pressure_gradient
                ) + pore_pressure_gradient
                fg_psi = fg * depth_ft
                fg_emw = fg / 0.052
                results = {
                    "depth_ft": depth_ft,
                    "overburden_gradient_psi_ft": overburden_gradient_psi_ft,
                    "pore_pressure_gradient_psi_ft": round(pore_pressure_gradient, 4),
                    "poisson_ratio": poisson_ratio,
                    "fracture_gradient_psi_ft": round(fg, 4),
                    "fracture_pressure_psi": round(fg_psi, 2),
                    "fracture_gradient_emw_ppg": round(fg_emw, 2),
                    "formula": "FG = (ν/(1-ν)) × (OBG - PP) + PP  [Hubbert & Willis]",
                }

            elif calc_type == "pressure_gradient_from_density":
                gradient = 0.052 * fluid_density_ppg
                results = {
                    "fluid_density_ppg": fluid_density_ppg,
                    "pressure_gradient_psi_ft": round(gradient, 4),
                    "pressure_gradient_kpa_m": round(gradient * 22.6209, 4),
                }

            output = f"Reservoir Pressure Calculation — {calc_type.replace('_', ' ').title()}\n"
            output += "=" * 60 + "\n"
            for key, val in results.items():
                output += f"  {key.replace('_', ' ').title()}: {val}\n"

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=output,
                raw=results,
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Calculation failed: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )


class DrillingEngineeringTool(BaseTool):
    """Drilling engineering calculations: ECD, kick tolerance, surge/swab."""

    name = "drilling_engineering_calc"
    description = (
        "Drilling engineering calculations including equivalent circulating density (ECD), "
        "kick tolerance, surge/swab pressures, and casing seat depth selection. "
        "Critical for well control and borehole stability analysis."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "calc_type": {
                "type": "string",
                "enum": ["ecd", "kick_tolerance", "surge_swab", "casing_seat", "mud_weight_window"],
                "description": "Drilling calculation type",
            },
            "mud_weight_ppg": {"type": "number", "description": "Drilling fluid density in ppg"},
            "depth_ft": {"type": "number", "description": "True vertical depth in feet"},
            "annular_pressure_loss_psi": {"type": "number", "description": "Annular pressure loss in psi"},
            "pit_gain_bbl": {"type": "number", "description": "Pit gain/kick volume in barrels"},
            "dp_capacity_bbl_ft": {"type": "number", "description": "Drillpipe capacity in bbl/ft"},
            "annulus_capacity_bbl_ft": {"type": "number", "description": "Annulus capacity in bbl/ft"},
            "pore_pressure_ppg": {"type": "number", "description": "Pore pressure in ppg EMW"},
            "fracture_gradient_ppg": {"type": "number", "description": "Fracture gradient in ppg EMW"},
        },
        "required": ["calc_type", "depth_ft"],
    }

    async def run(
        self,
        calc_type: str,
        depth_ft: float,
        mud_weight_ppg: float = 9.0,
        annular_pressure_loss_psi: float = 200.0,
        pit_gain_bbl: float = 10.0,
        dp_capacity_bbl_ft: float = 0.0087,
        annulus_capacity_bbl_ft: float = 0.0515,
        pore_pressure_ppg: float = 8.5,
        fracture_gradient_ppg: float = 15.0,
        **kwargs,
    ) -> ToolResult:
        start = time.time()
        try:
            results = {}

            if calc_type == "ecd":
                # ECD = MW + (APL / (0.052 × TVD))
                ecd = mud_weight_ppg + (annular_pressure_loss_psi / (0.052 * depth_ft))
                ecd_psi_ft = ecd * 0.052
                results = {
                    "mud_weight_ppg": mud_weight_ppg,
                    "annular_pressure_loss_psi": annular_pressure_loss_psi,
                    "depth_tvd_ft": depth_ft,
                    "ecd_ppg": round(ecd, 3),
                    "ecd_pressure_gradient_psi_ft": round(ecd_psi_ft, 4),
                    "ecd_bhp_psi": round(ecd_psi_ft * depth_ft, 2),
                    "formula": "ECD = MW + APL / (0.052 × TVD)",
                }

            elif calc_type == "kick_tolerance":
                # Maximum pit gain before wellbore exceeds fracture gradient
                max_kick_intensity = fracture_gradient_ppg - mud_weight_ppg
                kick_tolerance_psi = max_kick_intensity * 0.052 * depth_ft
                # Simplified bubble size: KT = FG - MW (ppg)
                results = {
                    "mud_weight_ppg": mud_weight_ppg,
                    "fracture_gradient_ppg": fracture_gradient_ppg,
                    "pore_pressure_ppg": pore_pressure_ppg,
                    "kick_tolerance_ppg": round(max_kick_intensity, 3),
                    "kick_tolerance_psi": round(kick_tolerance_psi, 2),
                    "safety_margin_ppg": round(mud_weight_ppg - pore_pressure_ppg, 3),
                    "note": "Simplified single-bubble method. Use full well control software for operations.",
                }

            elif calc_type == "mud_weight_window":
                pore_pressure_psi = pore_pressure_ppg * 0.052 * depth_ft
                fracture_pressure_psi = fracture_gradient_ppg * 0.052 * depth_ft
                window_ppg = fracture_gradient_ppg - pore_pressure_ppg
                results = {
                    "depth_ft": depth_ft,
                    "pore_pressure_ppg": pore_pressure_ppg,
                    "pore_pressure_psi": round(pore_pressure_psi, 2),
                    "fracture_gradient_ppg": fracture_gradient_ppg,
                    "fracture_pressure_psi": round(fracture_pressure_psi, 2),
                    "mud_weight_window_ppg": round(window_ppg, 3),
                    "recommended_mud_weight_ppg": round(pore_pressure_ppg + 0.3, 3),
                    "status": "NARROW" if window_ppg < 1.5 else "ADEQUATE" if window_ppg < 3.0 else "WIDE",
                }

            output = f"Drilling Engineering — {calc_type.replace('_', ' ').upper()}\n"
            output += "=" * 60 + "\n"
            for key, val in results.items():
                output += f"  {key.replace('_', ' ').title()}: {val}\n"

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=output,
                raw=results,
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Calculation failed: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )


class ProductionEngineeringTool(BaseTool):
    """Production engineering: inflow performance, IPR, nodal analysis inputs."""

    name = "production_engineering_calc"
    description = (
        "Production engineering calculations including inflow performance relationship (IPR), "
        "productivity index, gas-liquid ratio analysis, and artificial lift sizing. "
        "Supports both oil and gas well performance analysis."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "calc_type": {
                "type": "string",
                "enum": ["productivity_index", "vogel_ipr", "darcy_flow", "gas_well_rate", "artificial_lift_selection"],
                "description": "Production engineering calculation type",
            },
            "reservoir_pressure_psi": {"type": "number", "description": "Static reservoir pressure in psi"},
            "flowing_bhp_psi": {"type": "number", "description": "Flowing bottomhole pressure in psi"},
            "flow_rate_bopd": {"type": "number", "description": "Observed oil flow rate in BOPD"},
            "permeability_md": {"type": "number", "description": "Formation permeability in millidarcies"},
            "thickness_ft": {"type": "number", "description": "Net pay thickness in feet"},
            "viscosity_cp": {"type": "number", "description": "Oil viscosity in centipoise"},
            "wellbore_radius_ft": {"type": "number", "description": "Wellbore radius in feet (default 0.328)"},
            "drainage_radius_ft": {"type": "number", "description": "Drainage radius in feet"},
            "skin_factor": {"type": "number", "description": "Mechanical skin factor"},
            "water_depth_ft": {"type": "number", "description": "Water depth for artificial lift selection"},
            "glr_scf_bbl": {"type": "number", "description": "Gas-liquid ratio in scf/bbl"},
            "water_cut_fraction": {"type": "number", "description": "Water cut as fraction (0-1)"},
        },
        "required": ["calc_type"],
    }

    async def run(
        self,
        calc_type: str,
        reservoir_pressure_psi: float = 3000.0,
        flowing_bhp_psi: float = 1500.0,
        flow_rate_bopd: float = 500.0,
        permeability_md: float = 10.0,
        thickness_ft: float = 50.0,
        viscosity_cp: float = 1.5,
        wellbore_radius_ft: float = 0.328,
        drainage_radius_ft: float = 1320.0,
        skin_factor: float = 0.0,
        water_depth_ft: float = 0.0,
        glr_scf_bbl: float = 500.0,
        water_cut_fraction: float = 0.2,
        **kwargs,
    ) -> ToolResult:
        start = time.time()
        try:
            results = {}

            if calc_type == "productivity_index":
                # PI = Q / (Pr - Pwf)
                drawdown = reservoir_pressure_psi - flowing_bhp_psi
                pi = flow_rate_bopd / drawdown if drawdown > 0 else 0
                aof = pi * reservoir_pressure_psi  # AOF at Pwf=0
                results = {
                    "reservoir_pressure_psi": reservoir_pressure_psi,
                    "flowing_bhp_psi": flowing_bhp_psi,
                    "drawdown_psi": round(drawdown, 2),
                    "flow_rate_bopd": flow_rate_bopd,
                    "productivity_index_bopd_psi": round(pi, 4),
                    "estimated_aof_bopd": round(aof, 2),
                    "formula": "PI = q / (Pr - Pwf)",
                }

            elif calc_type == "vogel_ipr":
                # Vogel's equation: q/q_max = 1 - 0.2(Pwf/Pr) - 0.8(Pwf/Pr)²
                pwf_pr = flowing_bhp_psi / reservoir_pressure_psi
                q_ratio = 1 - 0.2 * pwf_pr - 0.8 * pwf_pr**2
                q_max = flow_rate_bopd / q_ratio if q_ratio > 0 else 0

                # Generate IPR curve points
                ipr_points = []
                for p_frac in [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]:
                    q_fr = 1 - 0.2 * p_frac - 0.8 * p_frac**2
                    ipr_points.append({
                        "pwf_psi": round(p_frac * reservoir_pressure_psi),
                        "q_bopd": round(q_max * q_fr, 1),
                    })

                results = {
                    "reservoir_pressure_psi": reservoir_pressure_psi,
                    "flowing_bhp_psi": flowing_bhp_psi,
                    "observed_rate_bopd": flow_rate_bopd,
                    "q_max_aof_bopd": round(q_max, 2),
                    "current_efficiency_pct": round(q_ratio * 100, 1),
                    "ipr_curve_points": ipr_points,
                    "formula": "q/qmax = 1 - 0.2(Pwf/Pr) - 0.8(Pwf/Pr)²  [Vogel 1968]",
                }

            elif calc_type == "darcy_flow":
                # Darcy's radial flow: q = kh(Pr-Pwf) / (141.2 × μ × Bo × (ln(re/rw) - 0.75 + S))
                bo = 1.2  # assumed formation volume factor
                ln_term = math.log(drainage_radius_ft / wellbore_radius_ft) - 0.75 + skin_factor
                q = (permeability_md * thickness_ft * (reservoir_pressure_psi - flowing_bhp_psi)) / (
                    141.2 * viscosity_cp * bo * ln_term
                )
                results = {
                    "permeability_md": permeability_md,
                    "thickness_ft": thickness_ft,
                    "viscosity_cp": viscosity_cp,
                    "skin_factor": skin_factor,
                    "drainage_radius_ft": drainage_radius_ft,
                    "wellbore_radius_ft": wellbore_radius_ft,
                    "drawdown_psi": round(reservoir_pressure_psi - flowing_bhp_psi, 2),
                    "calculated_flow_rate_bopd": round(q, 2),
                    "ln_term": round(ln_term, 3),
                    "formula": "q = kh·ΔP / (141.2 × μ × Bo × (ln(re/rw) - 0.75 + S))",
                }

            elif calc_type == "artificial_lift_selection":
                # Simple selection guide based on reservoir/well parameters
                recommendations = []
                if flowing_bhp_psi < 200 and glr_scf_bbl > 200:
                    recommendations.append("Gas Lift — ideal for high GLR, offshore/subsea wells")
                if water_cut_fraction > 0.8:
                    recommendations.append("ESP (Electric Submersible Pump) — best for high water cut, high volume")
                if water_cut_fraction < 0.5 and flow_rate_bopd < 500:
                    recommendations.append("Rod Pump (Sucker Rod) — economical for shallow, moderate-volume wells")
                if water_depth_ft > 1000:
                    recommendations.append("ESP or Gas Lift — recommended for deepwater/subsea applications")
                if not recommendations:
                    recommendations.append("Natural Flow — reservoir energy sufficient for current conditions")
                    recommendations.append("Monitor decline; plan for ESP or Gas Lift within 2-3 years")

                results = {
                    "flowing_bhp_psi": flowing_bhp_psi,
                    "water_cut_pct": round(water_cut_fraction * 100, 1),
                    "glr_scf_bbl": glr_scf_bbl,
                    "water_depth_ft": water_depth_ft,
                    "recommendations": recommendations,
                    "note": "Final selection requires nodal analysis and economic evaluation",
                }

            output = f"Production Engineering — {calc_type.replace('_', ' ').upper()}\n"
            output += "=" * 60 + "\n"
            for key, val in results.items():
                if isinstance(val, list):
                    output += f"  {key.replace('_', ' ').title()}:\n"
                    for item in val:
                        if isinstance(item, dict):
                            output += f"    Pwf={item.get('pwf_psi')} psi → Q={item.get('q_bopd')} BOPD\n"
                        else:
                            output += f"    • {item}\n"
                else:
                    output += f"  {key.replace('_', ' ').title()}: {val}\n"

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=output,
                raw=results,
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Calculation failed: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )


class PipelineHydraulicsTool(BaseTool):
    """Pipeline pressure drop, flow regime, and line sizing calculations."""

    name = "pipeline_hydraulics_calc"
    description = (
        "Pipeline hydraulics for oil and gas surface and subsea systems. "
        "Calculates pressure drop (Darcy-Weisbach), flow regime (Reynolds number), "
        "and line sizing for crude oil, natural gas, and multiphase pipelines."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "calc_type": {
                "type": "string",
                "enum": ["pressure_drop", "flow_regime", "line_sizing", "gas_flow_rate"],
                "description": "Hydraulic calculation type",
            },
            "pipe_id_inches": {"type": "number", "description": "Pipe inside diameter in inches"},
            "pipe_length_ft": {"type": "number", "description": "Pipe length in feet"},
            "flow_rate_bopd": {"type": "number", "description": "Liquid flow rate in BOPD"},
            "fluid_density_ppg": {"type": "number", "description": "Fluid density in ppg"},
            "viscosity_cp": {"type": "number", "description": "Dynamic viscosity in centipoise"},
            "roughness_inches": {"type": "number", "description": "Pipe roughness in inches (default 0.0018)"},
            "inlet_pressure_psi": {"type": "number", "description": "Inlet pressure in psi"},
            "gas_flow_rate_mmscfd": {"type": "number", "description": "Gas flow rate in MMSCFD"},
            "gas_gravity": {"type": "number", "description": "Gas specific gravity (air=1.0)"},
            "temperature_f": {"type": "number", "description": "Average temperature in °F"},
        },
        "required": ["calc_type"],
    }

    async def run(
        self,
        calc_type: str,
        pipe_id_inches: float = 6.0,
        pipe_length_ft: float = 5280.0,
        flow_rate_bopd: float = 5000.0,
        fluid_density_ppg: float = 8.33,
        viscosity_cp: float = 5.0,
        roughness_inches: float = 0.0018,
        inlet_pressure_psi: float = 500.0,
        gas_flow_rate_mmscfd: float = 10.0,
        gas_gravity: float = 0.65,
        temperature_f: float = 100.0,
        **kwargs,
    ) -> ToolResult:
        start = time.time()
        try:
            results = {}
            pipe_id_ft = pipe_id_inches / 12.0
            area_ft2 = math.pi * (pipe_id_ft / 2) ** 2

            if calc_type == "flow_regime":
                # Convert BOPD to ft³/s
                flow_ft3_s = flow_rate_bopd * 5.61458 / 86400
                velocity_ft_s = flow_ft3_s / area_ft2
                density_lb_ft3 = fluid_density_ppg * 7.48052
                viscosity_lb_ft_s = viscosity_cp * 0.000672
                re = (density_lb_ft3 * velocity_ft_s * pipe_id_ft) / viscosity_lb_ft_s

                if re < 2300:
                    regime = "LAMINAR"
                elif re < 4000:
                    regime = "TRANSITIONAL"
                else:
                    regime = "TURBULENT"

                results = {
                    "pipe_id_inches": pipe_id_inches,
                    "flow_rate_bopd": flow_rate_bopd,
                    "velocity_ft_s": round(velocity_ft_s, 3),
                    "reynolds_number": round(re, 0),
                    "flow_regime": regime,
                    "fluid_density_ppg": fluid_density_ppg,
                    "viscosity_cp": viscosity_cp,
                }

            elif calc_type == "pressure_drop":
                # Darcy-Weisbach
                flow_ft3_s = flow_rate_bopd * 5.61458 / 86400
                velocity_ft_s = flow_ft3_s / area_ft2
                density_lb_ft3 = fluid_density_ppg * 7.48052
                viscosity_lb_ft_s = viscosity_cp * 0.000672
                re = (density_lb_ft3 * velocity_ft_s * pipe_id_ft) / viscosity_lb_ft_s

                # Friction factor (Colebrook-White, explicit Swamee-Jain)
                if re < 2300:
                    f = 64 / re
                else:
                    f = 0.25 / (math.log10(roughness_inches / (3.7 * pipe_id_inches) + 5.74 / re**0.9)) ** 2

                # Pressure drop: ΔP = f × (L/D) × (ρv²/2)
                dp_lb_ft2 = f * (pipe_length_ft / pipe_id_ft) * (density_lb_ft3 * velocity_ft_s**2 / 2)
                dp_psi = dp_lb_ft2 / 144
                outlet_pressure = inlet_pressure_psi - dp_psi

                results = {
                    "pipe_id_inches": pipe_id_inches,
                    "pipe_length_ft": pipe_length_ft,
                    "flow_rate_bopd": flow_rate_bopd,
                    "velocity_ft_s": round(velocity_ft_s, 3),
                    "reynolds_number": round(re, 0),
                    "friction_factor": round(f, 5),
                    "pressure_drop_psi": round(dp_psi, 2),
                    "inlet_pressure_psi": inlet_pressure_psi,
                    "outlet_pressure_psi": round(outlet_pressure, 2),
                    "formula": "ΔP = f × (L/D) × (ρv²/2)  [Darcy-Weisbach]",
                }

            elif calc_type == "line_sizing":
                # Size pipe for max velocity (typically 3-5 ft/s for liquids)
                max_velocity = 4.0  # ft/s recommended
                flow_ft3_s = flow_rate_bopd * 5.61458 / 86400
                req_area_ft2 = flow_ft3_s / max_velocity
                req_id_ft = 2 * math.sqrt(req_area_ft2 / math.pi)
                req_id_inches = req_id_ft * 12

                # Standard pipe sizes lookup
                std_sizes = [2, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 30, 36]
                recommended = next((s for s in std_sizes if s >= req_id_inches), std_sizes[-1])

                results = {
                    "flow_rate_bopd": flow_rate_bopd,
                    "target_max_velocity_ft_s": max_velocity,
                    "calculated_min_id_inches": round(req_id_inches, 2),
                    "recommended_nominal_pipe_size_inches": recommended,
                    "note": "Based on 4 ft/s max velocity. Verify with pressure drop and erosion criteria.",
                }

            output = f"Pipeline Hydraulics — {calc_type.replace('_', ' ').upper()}\n"
            output += "=" * 60 + "\n"
            for key, val in results.items():
                output += f"  {key.replace('_', ' ').title()}: {val}\n"

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=output,
                raw=results,
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Calculation failed: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )


class WellControlTool(BaseTool):
    """Well control calculations: kill sheet, MAASP, pit gain analysis."""

    name = "well_control_calc"
    description = (
        "Well control and kill sheet calculations including maximum allowable annular surface pressure (MAASP), "
        "kill mud weight, strokes to kill, and pressure schedules. "
        "Use for kick detection, well control planning, and post-kick analysis."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "calc_type": {
                "type": "string",
                "enum": ["maasp", "kill_mud_weight", "driller_method_pressure", "bullheading_pressure"],
                "description": "Well control calculation type",
            },
            "mud_weight_ppg": {"type": "number", "description": "Current mud weight in ppg"},
            "depth_ft": {"type": "number", "description": "True vertical depth in feet"},
            "shoe_depth_ft": {"type": "number", "description": "Casing shoe depth in feet"},
            "fracture_gradient_ppg": {"type": "number", "description": "Fracture gradient at shoe in ppg"},
            "sicp_psi": {"type": "number", "description": "Shut-in casing pressure in psi"},
            "sidpp_psi": {"type": "number", "description": "Shut-in drill pipe pressure in psi"},
            "pit_gain_bbl": {"type": "number", "description": "Observed pit gain in barrels"},
        },
        "required": ["calc_type", "depth_ft"],
    }

    async def run(
        self,
        calc_type: str,
        depth_ft: float,
        mud_weight_ppg: float = 9.0,
        shoe_depth_ft: float = 8000.0,
        fracture_gradient_ppg: float = 14.5,
        sicp_psi: float = 300.0,
        sidpp_psi: float = 200.0,
        pit_gain_bbl: float = 10.0,
        **kwargs,
    ) -> ToolResult:
        start = time.time()
        try:
            results = {}

            if calc_type == "maasp":
                # MAASP = (FG - MW) × 0.052 × shoe depth
                maasp = (fracture_gradient_ppg - mud_weight_ppg) * 0.052 * shoe_depth_ft
                results = {
                    "mud_weight_ppg": mud_weight_ppg,
                    "fracture_gradient_ppg": fracture_gradient_ppg,
                    "shoe_depth_ft": shoe_depth_ft,
                    "maasp_psi": round(maasp, 2),
                    "status": "KICK TAKEN" if sicp_psi > 0 else "NORMAL OPERATIONS",
                    "sicp_psi": sicp_psi,
                    "sicp_vs_maasp": "EXCEEDS MAASP — EMERGENCY PROCEDURES" if sicp_psi > maasp else "Within limits",
                    "formula": "MAASP = (FG - MW) × 0.052 × Dshoe",
                }

            elif calc_type == "kill_mud_weight":
                # KMW = MW + SIDPP / (0.052 × TVD)
                kmw = mud_weight_ppg + sidpp_psi / (0.052 * depth_ft)
                extra_pressure = (kmw - mud_weight_ppg) * 0.052 * depth_ft
                results = {
                    "current_mud_weight_ppg": mud_weight_ppg,
                    "sidpp_psi": sidpp_psi,
                    "depth_ft": depth_ft,
                    "kill_mud_weight_ppg": round(kmw, 2),
                    "extra_hydrostatic_psi": round(extra_pressure, 2),
                    "overbalance_safety_margin_ppg": 0.3,
                    "recommended_kmw_ppg": round(kmw + 0.3, 2),
                    "formula": "KMW = MW + SIDPP / (0.052 × TVD)",
                    "note": "Add 0.3 ppg safety margin for operational purposes",
                }

            elif calc_type == "driller_method_pressure":
                # First circulation kill sheet
                icp = sidpp_psi + (mud_weight_ppg * 0.052 * depth_ft * 0.02)  # simplified circulating losses
                fcp = (sidpp_psi + (0.052 * depth_ft)) * 0.1  # simplified
                kmw = mud_weight_ppg + sidpp_psi / (0.052 * depth_ft)
                results = {
                    "initial_circulating_pressure_psi": round(icp, 2),
                    "kill_mud_weight_ppg": round(kmw, 2),
                    "sidpp_psi": sidpp_psi,
                    "sicp_psi": sicp_psi,
                    "pit_gain_bbl": pit_gain_bbl,
                    "procedure": [
                        "1. Close BOP — record SIDPP and SICP",
                        "2. Circulate kick out at slow pump rate (SPR)",
                        f"3. Hold casing pressure constant at {round(sicp_psi)} psi while pumping",
                        f"4. Kill mud weight: {round(kmw, 2)} ppg",
                        "5. Watch for gas expansion near surface — reduce backpressure carefully",
                    ],
                }

            output = f"Well Control — {calc_type.replace('_', ' ').upper()}\n"
            output += "=" * 60 + "\n"
            for key, val in results.items():
                if isinstance(val, list):
                    output += f"  {key.replace('_', ' ').title()}:\n"
                    for item in val:
                        output += f"    {item}\n"
                else:
                    output += f"  {key.replace('_', ' ').title()}: {val}\n"

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=output,
                raw=results,
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Calculation failed: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )


class OilGasRegulatoryTool(BaseTool):
    """Regulatory and compliance reference tool for oil and gas operations."""

    name = "oilgas_regulatory_reference"
    description = (
        "Look up oil and gas regulatory requirements, standards, and compliance information. "
        "Covers API standards, BSEE/BOEM offshore regulations, EPA emissions rules, "
        "OSHA process safety management (PSM), and international standards (ISO, NORSOK)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query_type": {
                "type": "string",
                "enum": [
                    "api_standards",
                    "bsee_offshore",
                    "osha_psm",
                    "epa_emissions",
                    "international_standards",
                    "well_integrity",
                    "process_safety",
                ],
                "description": "Type of regulatory information to look up",
            },
            "operation_type": {
                "type": "string",
                "description": "Specific operation or equipment (e.g., 'wellhead', 'pipeline', 'tank battery')",
            },
        },
        "required": ["query_type"],
    }

    async def run(self, query_type: str, operation_type: str = "general", **kwargs) -> ToolResult:
        start = time.time()

        REGULATORY_DB = {
            "api_standards": {
                "key_standards": [
                    "API 6A — Wellhead and Tree Equipment",
                    "API 7-1 — Rotary Drill Stem Elements",
                    "API 10A — Specification for Cements",
                    "API 11D1 — Packers and Bridge Plugs",
                    "API 14C — Analysis, Design, Installation of Basic Surface Safety Systems",
                    "API 16A — Drill-Through Equipment (BOP)",
                    "API 17D — Subsea Wellhead and Tree Equipment",
                    "API 19D — Measuring Particle Size Distribution of Fracturing Proppants",
                    "API 570 — Piping Inspection Code",
                    "API 620/650 — Tank Design and Construction",
                    "API 2000 — Venting Atmospheric and Low-Pressure Storage Tanks",
                    "API RP 505 — Recommended Practice for Classifying Hazardous Locations",
                ],
                "note": "Always verify current edition. Standards are updated periodically.",
            },
            "bsee_offshore": {
                "key_regulations": [
                    "30 CFR Part 250 — Oil and Gas and Sulphur Operations in the OCS",
                    "BSEE Production Safety Systems regulations",
                    "Well Control Rule (2016/2019 amendments)",
                    "SEMS — Safety and Environmental Management System (API RP 75)",
                    "Decommissioning guidelines for offshore structures",
                    "BOEM OCSLA compliance requirements",
                ],
                "key_requirements": [
                    "Well permit approval before spudding (APD — Application to Permit a Well)",
                    "Real-time monitoring for deepwater operations",
                    "SAFE Act compliance for offshore facilities",
                    "Quarterly production reporting (OGOR)",
                    "MOC — Management of Change documentation",
                ],
            },
            "osha_psm": {
                "regulation": "29 CFR 1910.119 — Process Safety Management of Highly Hazardous Chemicals",
                "14_elements": [
                    "1. Process Safety Information (PSI)",
                    "2. Process Hazard Analysis (PHA/HAZOP)",
                    "3. Operating Procedures",
                    "4. Training",
                    "5. Contractors",
                    "6. Pre-Startup Safety Review (PSSR)",
                    "7. Mechanical Integrity",
                    "8. Hot Work Permit",
                    "9. Management of Change (MOC)",
                    "10. Incident Investigation",
                    "11. Emergency Planning and Response",
                    "12. Compliance Audits",
                    "13. Trade Secrets",
                    "14. Employee Participation",
                ],
                "threshold_quantities": "Highly hazardous chemicals > 10,000 lbs",
            },
            "epa_emissions": {
                "key_rules": [
                    "40 CFR Part 60 Subpart OOOO/OOOOa — Oil and Gas Standards",
                    "Quad O: VOC emissions from oil and natural gas sector",
                    "Methane monitoring and reporting requirements",
                    "GHGRP — Greenhouse Gas Reporting Program (Subpart W)",
                    "Flaring restrictions and alternatives",
                    "LDAR — Leak Detection and Repair programs",
                ],
                "monitoring_requirements": [
                    "Quarterly component monitoring for high-production wells",
                    "Semiannual monitoring for low-production wells",
                    "Annual monitoring for compressor stations",
                    "OGI (Optical Gas Imaging) camera surveys",
                ],
            },
            "well_integrity": {
                "standards": [
                    "NORSOK D-010 — Well Integrity in Drilling and Well Operations",
                    "ISO 16530-1 — Well Integrity",
                    "API 90-1/90-2 — Annular Casing Pressure Management",
                    "API RP 100-1 — Hydraulic Fracturing — Well Integrity",
                ],
                "key_barriers": [
                    "Primary barrier: Wellbore fluids, tubing, wellhead, xmas tree",
                    "Secondary barrier: Casing strings, cement, wellhead annulus valves",
                    "Minimum 2 independent barriers required at all times",
                    "Pressure testing requirements per API/BSEE",
                ],
            },
            "process_safety": {
                "key_metrics": [
                    "TRIR — Total Recordable Incident Rate",
                    "LTIR — Lost Time Incident Rate",
                    "LOPC — Loss of Primary Containment events",
                    "Near miss reporting and investigation",
                    "Safety critical element performance standards",
                ],
                "bowsite_approach": [
                    "Prevention barriers (left side of bow-tie)",
                    "Mitigation barriers (right side of bow-tie)",
                    "Critical controls identification and monitoring",
                ],
            },
        }

        data = REGULATORY_DB.get(query_type, {"error": f"Query type '{query_type}' not found"})

        output = f"Regulatory Reference — {query_type.replace('_', ' ').upper()}\n"
        output += f"Operation: {operation_type}\n"
        output += "=" * 60 + "\n"
        output += "⚠️  DISCLAIMER: This is a reference guide only. Always consult current\n"
        output += "    regulations and qualified engineers for operational decisions.\n\n"

        def format_dict(d, indent=0):
            result = ""
            for key, val in d.items():
                prefix = "  " * indent
                if isinstance(val, list):
                    result += f"{prefix}{key.replace('_', ' ').title()}:\n"
                    for item in val:
                        result += f"{prefix}  • {item}\n"
                elif isinstance(val, dict):
                    result += f"{prefix}{key.replace('_', ' ').title()}:\n"
                    result += format_dict(val, indent + 1)
                else:
                    result += f"{prefix}{key.replace('_', ' ').title()}: {val}\n"
            return result

        output += format_dict(data)

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=output,
            raw=data,
            duration_seconds=time.time() - start,
        )


class FormationEvaluationTool(BaseTool):
    """Formation evaluation and petrophysics calculations."""

    name = "formation_evaluation_calc"
    description = (
        "Formation evaluation and petrophysics: porosity, water saturation, net pay cutoffs, "
        "permeability estimation from logs, and lithology interpretation. "
        "Supports Archie's equation, Wyllie time-average, and core-log integration."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "calc_type": {
                "type": "string",
                "enum": ["water_saturation_archie", "porosity_sonic", "permeability_timur", "net_pay_cutoff", "shale_volume"],
                "description": "Formation evaluation calculation type",
            },
            "resistivity_ohm_m": {"type": "number", "description": "Formation resistivity Rt in ohm·m"},
            "rw_ohm_m": {"type": "number", "description": "Formation water resistivity Rw in ohm·m"},
            "porosity_fraction": {"type": "number", "description": "Total porosity as fraction (0-1)"},
            "a_cementation": {"type": "number", "description": "Archie's 'a' constant (default 1.0)"},
            "m_cementation": {"type": "number", "description": "Cementation exponent 'm' (default 2.0)"},
            "n_saturation": {"type": "number", "description": "Saturation exponent 'n' (default 2.0)"},
            "dt_log_us_ft": {"type": "number", "description": "Sonic transit time from log in µs/ft"},
            "dt_matrix_us_ft": {"type": "number", "description": "Matrix transit time (sandstone=55.5, limestone=47.6)"},
            "dt_fluid_us_ft": {"type": "number", "description": "Fluid transit time (default 189 µs/ft)"},
            "gr_log": {"type": "number", "description": "Gamma ray log value in API units"},
            "gr_clean": {"type": "number", "description": "Clean sand GR baseline in API"},
            "gr_shale": {"type": "number", "description": "Shale GR baseline in API"},
        },
        "required": ["calc_type"],
    }

    async def run(
        self,
        calc_type: str,
        resistivity_ohm_m: float = 10.0,
        rw_ohm_m: float = 0.05,
        porosity_fraction: float = 0.20,
        a_cementation: float = 1.0,
        m_cementation: float = 2.0,
        n_saturation: float = 2.0,
        dt_log_us_ft: float = 90.0,
        dt_matrix_us_ft: float = 55.5,
        dt_fluid_us_ft: float = 189.0,
        gr_log: float = 50.0,
        gr_clean: float = 20.0,
        gr_shale: float = 120.0,
        **kwargs,
    ) -> ToolResult:
        start = time.time()
        try:
            results = {}

            if calc_type == "water_saturation_archie":
                # Sw^n = (a × Rw) / (φ^m × Rt)
                f = a_cementation / (porosity_fraction**m_cementation)
                sw_n = (f * rw_ohm_m) / resistivity_ohm_m
                sw = sw_n ** (1 / n_saturation)
                sw = min(1.0, max(0.0, sw))
                sh = 1 - sw
                results = {
                    "resistivity_rt_ohm_m": resistivity_ohm_m,
                    "rw_ohm_m": rw_ohm_m,
                    "porosity_fraction": porosity_fraction,
                    "a_cementation_exponent": a_cementation,
                    "m_cementation_exponent": m_cementation,
                    "n_saturation_exponent": n_saturation,
                    "formation_factor_F": round(f, 4),
                    "water_saturation_Sw": round(sw, 4),
                    "water_saturation_pct": round(sw * 100, 2),
                    "hydrocarbon_saturation_pct": round(sh * 100, 2),
                    "interpretation": "HYDROCARBON" if sh > 0.5 else "WATER" if sw > 0.8 else "TRANSITION",
                    "formula": "Sw^n = (a × Rw) / (φ^m × Rt)  [Archie 1942]",
                }

            elif calc_type == "porosity_sonic":
                # Wyllie time-average: φ = (Δt_log - Δt_ma) / (Δt_fl - Δt_ma)
                phi = (dt_log_us_ft - dt_matrix_us_ft) / (dt_fluid_us_ft - dt_matrix_us_ft)
                phi = min(0.45, max(0.0, phi))
                results = {
                    "dt_log_us_ft": dt_log_us_ft,
                    "dt_matrix_us_ft": dt_matrix_us_ft,
                    "dt_fluid_us_ft": dt_fluid_us_ft,
                    "sonic_porosity_fraction": round(phi, 4),
                    "sonic_porosity_pct": round(phi * 100, 2),
                    "matrix_type": "Sandstone (Δtma=55.5)" if abs(dt_matrix_us_ft - 55.5) < 1 else "Limestone (Δtma=47.6)" if abs(dt_matrix_us_ft - 47.6) < 1 else "Custom",
                    "formula": "φ = (Δtlog - Δtma) / (Δtfl - Δtma)  [Wyllie time-average]",
                }

            elif calc_type == "shale_volume":
                # Vsh from GR log (linear)
                igr = (gr_log - gr_clean) / (gr_shale - gr_clean)
                igr = min(1.0, max(0.0, igr))
                # Larionov correction (Tertiary rocks)
                vsh_larionov_tertiary = 0.083 * (2 ** (3.7 * igr) - 1)
                results = {
                    "gr_log_api": gr_log,
                    "gr_clean_api": gr_clean,
                    "gr_shale_api": gr_shale,
                    "igr_linear": round(igr, 4),
                    "vsh_linear_fraction": round(igr, 4),
                    "vsh_larionov_tertiary_fraction": round(min(1.0, vsh_larionov_tertiary), 4),
                    "net_pay_candidate": "POSSIBLE" if igr < 0.35 else "MARGINAL" if igr < 0.5 else "SHALE",
                    "formula": "IGR = (GR - GRclean) / (GRshale - GRclean)",
                }

            output = f"Formation Evaluation — {calc_type.replace('_', ' ').upper()}\n"
            output += "=" * 60 + "\n"
            for key, val in results.items():
                output += f"  {key.replace('_', ' ').title()}: {val}\n"

            return ToolResult(
                tool_name=self.name,
                success=True,
                output=output,
                raw=results,
                duration_seconds=time.time() - start,
            )
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=f"Calculation failed: {e}",
                error=str(e),
                duration_seconds=time.time() - start,
            )


# ── Tool Registry Builder ─────────────────────────────────────────────────────

def get_oilgas_tools() -> list[BaseTool]:
    """Return all oil and gas engineering tools for registration."""
    return [
        ReservoirPressureCalcTool(),
        DrillingEngineeringTool(),
        ProductionEngineeringTool(),
        PipelineHydraulicsTool(),
        WellControlTool(),
        OilGasRegulatoryTool(),
        FormationEvaluationTool(),
    ]
