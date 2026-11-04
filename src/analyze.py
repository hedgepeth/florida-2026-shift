"""Test: did retiree transplants blunt Florida's 2026 blue shift?

Run:  python src/build.py && python src/analyze.py
Writes figures/*.png and results/results.json
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from build import load

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
RES = ROOT / "results"
FIG.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)

df, state = load()
S = df[df.county == "Sumter"].iloc[0]
rest = df[df.county != "Sumter"]
r = {}

# ---------- 0. Statewide facts ----------
g, h, p = state["g26"], state["hist"], state["pop"]
r["state_margin_2026_dem"] = round(100 * (g.jolly_d - g.donalds_r) / g.total_votes, 2)
r["state_margin_2024_dem"] = h.margin_2024_dem
r["state_margin_2022_dem"] = h.margin_2022_dem
r["state_vote_gap_2026"] = int(g.donalds_r - g.jolly_d)
r["state_turnout_retention"] = round(100 * g.total_votes / h.votes_2024, 1)
r["median_county_shift_vs_2024"] = round(df.shift_vs_2024.median(), 1)
r["median_county_shift_vs_2022"] = round(df.shift_vs_2022.median(), 1)
r["counties_shifting_right_vs_2024"] = df[df.shift_vs_2024 < 0].county.tolist()
r["counties_shifting_right_vs_2022"] = df[df.shift_vs_2022 < 0].county.tolist()

# ---------- 1. The "25% of Florida's net migration" stat ----------
pos = df.dommig_25.clip(lower=0).sum()
neg = df.dommig_25.clip(upper=0).sum()
r["fl_net_domestic_mig_jul24_jun25"] = int(p.DOMESTICMIG2025)
r["sumter_net_domestic_mig_jul24_jun25"] = int(S.dommig_25)
r["sumter_share_of_fl_net"] = round(100 * S.dommig_25 / p.DOMESTICMIG2025, 1)
r["sum_of_positive_county_nets"] = int(pos)
r["sum_of_negative_county_nets"] = int(neg)
r["sumter_share_of_positive_county_nets"] = round(100 * S.dommig_25 / pos, 1)
r["sumter_share_of_fl_pop"] = round(100 * S.pop_2025 / p.POPESTIMATE2025, 2)
r["biggest_losers"] = df.nsmallest(3, "dommig_25")[["county", "dommig_25"]].values.tolist()

# ---------- 2. County regressions ----------
def fit(formula, weighted, data=df):
    m = (smf.wls(formula, data, weights=data.votes_2026) if weighted else smf.ols(formula, data)).fit(cov_type="HC1")
    return {
        "formula": formula, "weighted_by_2026_votes": weighted, "n": int(m.nobs), "r2": round(m.rsquared, 3),
        "coefs": {k: {"b": round(v, 3), "se": round(m.bse[k], 3), "p": round(m.pvalues[k], 4)}
                  for k, v in m.params.items() if k != "Intercept"},
    }

forms = [
    "shift_vs_2024 ~ dommig_25_rate",
    "shift_vs_2024 ~ pct_65plus",
    "shift_vs_2024 ~ dommig_25_rate + pct_65plus",
    "shift_vs_2024 ~ dommig_25_rate + pct_65plus + turnout_retention + margin_2024_dem",
    "shift_vs_2024 ~ dommig_21_24_rate + pct_65plus + turnout_retention + margin_2024_dem",
    "shift_vs_2022 ~ dommig_25_rate + pct_65plus + turnout_retention + margin_2024_dem",
]
r["regressions"] = [fit(f, w) for f in forms for w in (False, True)]
r["regression_full_ex_sumter_weighted"] = fit(forms[3], True, rest)

# ---------- 3. Hold Sumter out: does age alone predict it? ----------
def holdout(formula):
    m = smf.ols(formula, rest).fit()
    pr = m.get_prediction(df[df.county == "Sumter"]).summary_frame(alpha=0.05).iloc[0]
    return {"formula": formula, "pred": round(pr["mean"], 2),
            "pi95": [round(pr.obs_ci_lower, 2), round(pr.obs_ci_upper, 2)], "observed": round(S.shift_vs_2024, 2)}

r["sumter_holdout"] = [holdout(f) for f in (
    "shift_vs_2024 ~ pct_65plus",
    "shift_vs_2024 ~ pct_65plus + turnout_retention + margin_2024_dem",
    "shift_vs_2024 ~ dommig_25_rate",
)]

# ---------- 4. Napkin: how red would Sumter's newcomers have to be? ----------
# If N post-2024 arrivals voted and everyone else voted exactly like 2024 (margin m0),
# the margin moves by N/V * (m_new - m0). Solve for m_new that explains the whole shift.
V, m0, sh = S.votes_2026, S.margin_2024_dem, S.shift_vs_2024
r["sumter_needed_newcomer_margin"] = {int(N): round(m0 + sh * V / N, 1) for N in (5633, 9000, 12000)}
r["sumter"] = {k: (round(float(v), 2) if isinstance(v, (float, np.floating)) else (int(v) if isinstance(v, (np.integer,)) else v))
               for k, v in S.items()}

# ---------- 5. Counterfactual: how many votes could migration have cost Jolly? ----------
# Uses the full weighted model (age + turnout + 2024 margin + migration). Margin pts * votes / 100 = net votes.
m = smf.wls(forms[3], df, weights=df.votes_2026).fit(cov_type="HC1")
b, se = m.params.dommig_25_rate, m.bse.dommig_25_rate
cf = {}
for lab, bb in (("point", b), ("ci95_edge", b - 1.96 * se)):
    cf[lab] = {
        "coef": round(bb, 3),
        "zero_migration_everywhere": int(round(-(bb * df.dommig_25_rate / 100 * df.votes_2026).sum())),
        "zero_inflow_only": int(round(-(bb * df.dommig_25_rate.clip(lower=0) / 100 * df.votes_2026).sum())),
    }
r["migration_counterfactual_net_dem_votes"] = cf

(RES / "results.json").write_text(json.dumps(r, indent=2, default=str))

# ---------- Figures ----------
INK, MUTED, GRID, DOT, HI = "#1f2328", "#6e7781", "#e6e8eb", "#9aa4ae", "#c2410c"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False})

def scatter(x, xlabel, fname, title, sub, fit_on_rest=True):
    fig, ax = plt.subplots(figsize=(8, 5.6), dpi=160)
    sz = 12 + 600 * df.votes_2026 / df.votes_2026.max()
    o = df[df.county != "Sumter"]
    ax.scatter(o[x], o.shift_vs_2024, s=sz[o.index], color=DOT, alpha=0.75, edgecolor="white", linewidth=1)
    ax.scatter(S[x], S.shift_vs_2024, s=sz[S.name], color=HI, edgecolor="white", linewidth=1.5, zorder=3)
    m = smf.ols(f"shift_vs_2024 ~ {x}", rest).fit()
    xs = np.linspace(df[x].min(), df[x].max(), 50)
    ax.plot(xs, m.params.Intercept + m.params[x] * xs, color=INK, lw=1.5, ls="--", zorder=2)
    ax.axhline(0, color=MUTED, lw=1)
    ax.annotate("Sumter (The Villages)", (S[x], S.shift_vs_2024), xytext=(-10, -22), textcoords="offset points",
                ha="right", color=HI, fontsize=10, fontweight="bold")
    for c in ("Miami-Dade", "Polk", "Pasco", "Osceola", "Charlotte", "St. Johns", "Lee"):
        rw = df[df.county == c].iloc[0]
        ax.annotate(c, (rw[x], rw.shift_vs_2024), xytext=(6, 4), textcoords="offset points", color=MUTED, fontsize=8.5)
    ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)
    ax.set_xlabel(xlabel); ax.set_ylabel("Margin shift, 2024 pres → 2026 gov (pts, + = more Dem)")
    fig.suptitle(title, x=0.02, ha="left", fontsize=13.5, fontweight="bold", color=INK)
    ax.set_title(sub, loc="left", fontsize=9.5, color=MUTED)
    fig.text(0.02, 0.01, "Dot size = 2026 votes. Dashed line fit on the other 66 counties (Sumter held out). "
             "Sources: NYT/AP results feed; Census PEP V2025.", fontsize=7.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(FIG / fname); plt.close(fig)

hs = r["sumter_holdout"]
scatter("pct_65plus", "Share of population aged 65+ (Census, July 2025)", "fig1_age.png",
        "Age explains Sumter: it sits right where the line says it should",
        f"Fit on the other 66 counties predicts Sumter at {hs[0]['pred']:+.1f}; actual {hs[0]['observed']:+.1f}")
scatter("dommig_25_rate", "Net domestic migration, Jul 2024–Jun 2025, % of 2024 pop", "fig2_migration.png",
        "Migration alone misses Sumter by ~9 points",
        f"Fit on the other 66 counties predicts Sumter at {hs[2]['pred']:+.1f}; actual {hs[2]['observed']:+.1f}")

# fig3: baseline choice
fig, ax = plt.subplots(figsize=(8, 3.6), dpi=160)
rows = [("Florida (statewide)", r["state_margin_2026_dem"] - h.margin_2024_dem, r["state_margin_2026_dem"] - h.margin_2022_dem),
        ("Median county", df.shift_vs_2024.median(), df.shift_vs_2022.median()),
        ("Sumter", S.shift_vs_2024, S.shift_vs_2022)]
y = np.arange(len(rows))[::-1]
for yi, (lab, a, b) in zip(y, rows):
    col = HI if lab == "Sumter" else DOT
    ax.barh(yi + 0.18, a, height=0.32, color=col, alpha=0.55)
    ax.barh(yi - 0.18, b, height=0.32, color=col)
    ax.text(a + (0.4 if a >= 0 else -0.4), yi + 0.18, f"{a:+.1f} vs 2024 pres", va="center",
            ha="left" if a >= 0 else "right", fontsize=9, color=INK)
    ax.text(b + 0.4, yi - 0.18, f"{b:+.1f} vs 2022 gov", va="center", fontsize=9, color=INK)
ax.set_yticks(y, [x[0] for x in rows]); ax.axvline(0, color=MUTED, lw=1)
ax.set_xlim(-12, 26); ax.set_xlabel("Margin shift to 2026 (pts, + = more Dem)")
ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
fig.suptitle("Compare midterm to midterm and Sumter shifted blue too", x=0.02, ha="left",
             fontsize=13.5, fontweight="bold", color=INK)
ax.set_title("Zero of 67 counties moved right vs the 2022 governor's race", loc="left", fontsize=9.5, color=MUTED)
fig.tight_layout(); fig.savefig(FIG / "fig3_baseline.png"); plt.close(fig)

print(json.dumps({k: v for k, v in r.items() if k not in ("regressions", "sumter")}, indent=1, default=str))
