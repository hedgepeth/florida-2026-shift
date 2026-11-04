"""Follow-ups: (A) migration window sweep, (B) in-state vs out-of-state migration (IRS SOI).

Run after build.py:  python src/windows.py
Writes results/windows.csv, results/irs_split.csv, figures/fig4_windows.png
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parents[1]
RAW, RES, FIG = ROOT / "data/raw", ROOT / "results", ROOT / "figures"
RES.mkdir(exist_ok=True)

d = pd.read_csv(ROOT / "data/processed/fl_counties.csv", dtype={"COUNTY": str})
c = pd.read_csv(RAW / "census_co_est2025_fl.csv", dtype={"COUNTY": str})
d = d.merge(c, on="COUNTY")
e = pd.read_csv(RAW / "census_ethnicity2025_fl.csv", dtype={"COUNTY": str})
d = d.merge(e, on="COUNTY")
assert (d.TOT_POP == d.pop_2025).all()
d["pct_hisp"] = 100 * d.HISP / d.TOT_POP
d["pct_black"] = 100 * d.NH_BLACK_ALONE / d.TOT_POP

CTRL = {"none": "", "age": " + pct_65plus", "full": " + pct_65plus + turnout_retention + margin_2024_dem",
        "full+race": " + pct_65plus + turnout_retention + margin_2024_dem + pct_hisp + pct_black"}


def fit(dv, xs, ctrl, data=None):
    data = d if data is None else data
    m = smf.wls(f"{dv} ~ {' + '.join(xs)}{CTRL[ctrl]}", data, weights=data.votes_2026).fit(cov_type="HC1")
    return m

# ---------------- A. Window sweep (Census PEP; year Y = Jul Y-1 .. Jun Y) ----------------
WINDOWS = {
    "Jul20-Jun21": [2021], "Jul21-Jun22": [2022], "Jul22-Jun23": [2023], "Jul23-Jun24": [2024], "Jul24-Jun25": [2025],
    "Jul21-Jun23": [2022, 2023], "Jul22-Jun24": [2023, 2024], "Jul23-Jun25": [2024, 2025],
    "Jul22-Jun25": [2023, 2024, 2025], "Jul20-Jun24": [2021, 2022, 2023, 2024],
}
rows = []
for name, ys in WINDOWS.items():
    d["mig"] = 100 * d[[f"DOMESTICMIG{y}" for y in ys]].sum(axis=1) / d.POPESTIMATE2024 / len(ys)  # annualised %
    for dv, cutoff in (("shift_vs_2024", 2024.84), ("shift_vs_2022", 2022.84)):
        start = min(ys) - 1 + 0.5
        for ctrl in CTRL:
            m = fit(dv, ["mig"], ctrl)
            rows.append({"window": name, "dv": dv, "controls": ctrl,
                         "arrived_after_baseline": start > cutoff,
                         "b_per_1pct_yr": round(m.params.mig, 2), "se": round(m.bse.mig, 2), "p": round(m.pvalues.mig, 3)})
W = pd.DataFrame(rows)
W.to_csv(RES / "windows.csv", index=False)

# ---------------- B. In-state vs out-of-state (IRS SOI county flows, people = n2) ----------------
# IRS "2021" = address change between TY2020 and TY2021 returns (~spring 2021 to spring 2022 filing); "22" and "23" likewise.
irs = pd.read_csv(RAW / "irs_soi_fl_county_flows.csv", dtype={"COUNTY": str}).fillna(0)
for y in ("21", "22", "23"):
    irs.loc[irs.COUNTY == "086", f"i{y}_086"] = 0  # self-flow = non-migrants
    irs.loc[irs.COUNTY == "011", f"i{y}_011"] = 0
avg = lambda k: irs[[f"{k[0]}{y}_{k[1:]}" for y in ("21", "22", "23")]].mean(axis=1)
irs["in_instate"], irs["out_instate"] = avg("i001"), avg("o001")
irs["in_interstate"], irs["out_interstate"] = avg("i003"), avg("o003")
irs["in_from_mdade_broward"] = avg("i086") + avg("i011")
d = d.merge(irs[["COUNTY", "in_instate", "out_instate", "in_interstate", "out_interstate", "in_from_mdade_broward"]], on="COUNTY")
P = d.POPESTIMATE2024 / 100
d["net_instate_rate"] = (d.in_instate - d.out_instate) / P
d["net_interstate_rate"] = (d.in_interstate - d.out_interstate) / P
d["gross_interstate_in_rate"] = d.in_interstate / P
d["gross_instate_in_rate"] = d.in_instate / P
d["mdade_broward_in_rate"] = d.in_from_mdade_broward / P
d["interstate_share_of_inflow"] = 100 * d.in_interstate / (d.in_interstate + d.in_instate)

specs = {
    "net split": ["net_interstate_rate", "net_instate_rate"],
    "gross in split": ["gross_interstate_in_rate", "gross_instate_in_rate"],
    "SoFla spillover": ["mdade_broward_in_rate", "net_interstate_rate"],
}
rows = []
for sname, xs in specs.items():
    for dv in ("shift_vs_2024", "shift_vs_2022"):
        for ctrl in CTRL:
            m = fit(dv, xs, ctrl)
            for x in xs:
                rows.append({"spec": sname, "dv": dv, "controls": ctrl, "var": x,
                             "b": round(m.params[x], 2), "se": round(m.bse[x], 2), "p": round(m.pvalues[x], 3), "r2": round(m.rsquared, 3)})
B = pd.DataFrame(rows)
B.to_csv(RES / "irs_split.csv", index=False)
d[["COUNTY", "county", "net_instate_rate", "net_interstate_rate", "gross_interstate_in_rate", "gross_instate_in_rate",
   "mdade_broward_in_rate", "interstate_share_of_inflow"]].round(3).to_csv(ROOT / "data/processed/fl_irs_rates.csv", index=False)

# ---------------- Figure: window sweep ----------------
INK, MUTED, GRID, A, Bc = "#1f2328", "#6e7781", "#e6e8eb", "#2563eb", "#c2410c"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10.5, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": GRID, "xtick.color": MUTED, "ytick.color": MUTED})
fig, axes = plt.subplots(1, 2, figsize=(10, 4.8), dpi=160, sharey=True)
order = list(WINDOWS)
for ax, dv, ttl in zip(axes, ("shift_vs_2024", "shift_vs_2022"), ("vs 2024 presidential", "vs 2022 governor (midterm to midterm)")):
    for ctrl, col, off, lab in (("none", MUTED, -0.18, "no controls"), ("full", A, 0.18, "age + turnout + 2024 margin")):
        s = W[(W.dv == dv) & (W.controls == ctrl)].set_index("window").loc[order]
        y = np.arange(len(order))[::-1] + off
        ax.errorbar(s.b_per_1pct_yr, y, xerr=1.96 * s.se, fmt="o", ms=5, color=col, ecolor=col, elinewidth=1.5, capsize=0, label=lab)
    ax.axvline(0, color=INK, lw=1)
    ax.set_title(ttl, loc="left", fontsize=10.5, color=INK)
    ax.grid(axis="x", color=GRID); ax.set_axisbelow(True)
    ax.set_xlabel("Shift (pts) per +1% of pop/yr net domestic migration")
axes[0].set_yticks(np.arange(len(order))[::-1], order)
h_, l_ = axes[0].get_legend_handles_labels()
fig.legend(h_, l_, frameon=False, fontsize=9, loc="upper left", ncol=2, bbox_to_anchor=(0.02, 0.93))
fig.suptitle("No migration window survives the controls — and midterm-to-midterm, it flips sign",
             x=0.02, ha="left", fontsize=12.5, fontweight="bold", color=INK)
fig.text(0.02, 0.01, "Vote-weighted county regressions, robust 95% CIs. Census PEP V2025 net domestic migration, annualised.",
         fontsize=7.5, color=MUTED)
fig.tight_layout(rect=(0, 0.03, 1, 0.88)); fig.savefig(FIG / "fig4_windows.png"); plt.close(fig)

# ---------------- Figure 5: in-state vs out-of-state, both baselines ----------------
fig, ax = plt.subplots(figsize=(9, 4.4), dpi=160)
labs, y = [], 0
for dv, nm in (("shift_vs_2024", "vs 2024 pres"), ("shift_vs_2022", "vs 2022 gov")):
    for var, col, vn in (("gross_interstate_in_rate", Bc, "Out-of-state arrivals"), ("gross_instate_in_rate", MUTED, "In-Florida movers")):
        for ctrl, mk in (("age", "o"), ("full+race", "D")):
            r_ = B[(B.spec == "gross in split") & (B.dv == dv) & (B["var"] == var) & (B.controls == ctrl)].iloc[0]
            ax.errorbar(r_.b, -y, xerr=1.96 * r_.se, fmt=mk, color=col, ecolor=col, ms=6, elinewidth=1.6)
            labs.append(f"{vn}, {nm} ({'age only' if ctrl == 'age' else 'all controls'})"); y += 1
    y += 0.6
ys = [-i for i in range(4)] + [-(i + 4.6) for i in range(4)]
ax.set_yticks(ys, labs, fontsize=8.5); ax.axvline(0, color=INK, lw=1)
ax.grid(axis="x", color=GRID); ax.set_axisbelow(True)
ax.set_xlabel("Shift (pts) per +1% of pop/yr gross in-migration (IRS, filers 2020-23)")
fig.suptitle("Out-of-state arrivals predict a smaller shift from 2024, but not from 2022",
             x=0.02, ha="left", fontsize=12, fontweight="bold", color=INK)
fig.text(0.02, 0.01, "All controls = 65+, turnout retention, 2024 margin, % Hispanic, % Black. Vote-weighted, robust 95% CIs.",
         fontsize=7.5, color=MUTED)
fig.tight_layout(rect=(0, 0.03, 1, 0.95)); fig.savefig(FIG / "fig5_instate_vs_interstate.png"); plt.close(fig)

# ---------------- Size it: votes implied by the out-of-state coefficient ----------------
m = fit("shift_vs_2024", specs["gross in split"], "full+race")
b, se = m.params.gross_interstate_in_rate, m.bse.gross_interstate_in_rate
lo = d.gross_interstate_in_rate.min()
size = {}
for lab, bb in (("point", b), ("ci_lo", b - 1.96 * se), ("ci_hi", b + 1.96 * se)):
    pts = bb * (d.gross_interstate_in_rate - lo)
    size[lab] = {"coef": round(bb, 2), "sumter_pts": round(float(pts[d.county == "Sumter"].iloc[0]), 1),
                 "statewide_net_votes": int(round((pts / 100 * d.votes_2026).sum()))}
pd.Series(size).to_json(RES / "interstate_sizing.json", indent=1)

if __name__ == "__main__":
    print(size)
    pd.set_option("display.width", 200)
    print(W.pivot_table(index="window", columns=["dv", "controls"], values="p", aggfunc="first").loc[order])
    print(W[W.controls == "full"].pivot_table(index="window", columns="dv", values="b_per_1pct_yr").loc[order])
    print(B[B.controls != "none"].to_string(index=False))
    s = d[d.county == "Sumter"].iloc[0]
    print("Sumter:", s[["net_instate_rate", "net_interstate_rate", "interstate_share_of_inflow", "mdade_broward_in_rate"]].round(2).to_dict())
    print("State interstate share of inflow (median county):", round(d.interstate_share_of_inflow.median(), 1))
    print(d.nlargest(6, "interstate_share_of_inflow")[["county", "interstate_share_of_inflow", "shift_vs_2024"]].round(1).to_string(index=False))
