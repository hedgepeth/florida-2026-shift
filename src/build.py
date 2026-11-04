"""Build the county-level analysis table.

Inputs (data/raw):
  nyt_fl_gov_2026_county.csv  - 2026 FL governor county results (NYT results feed, AP data, ~99% expected vote in)
  nyt_hist_margins.csv        - NYT's own 2024 pres + 2022 gov county baselines (same feed)
  pres2024.csv                - tonmcg 2024 county presidential results (independent cross-check of the 2024 baseline)
  census_co_est2025_fl.csv    - Census PEP Vintage 2025 components of change (co-est2025-alldata.csv, FL rows)
  census_agesex2025_fl.csv    - Census PEP Vintage 2025 age/sex (cc-est2025-agesex-12.csv, YEAR=7 i.e. 1 Jul 2025)

Margins are Dem minus Rep, in percentage points of the total vote. Positive shift = more Democratic.
"""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"


def load():
    s = lambda f: pd.read_csv(RAW / f, dtype={"COUNTY": str})
    g26 = s("nyt_fl_gov_2026_county.csv")
    hist = s("nyt_hist_margins.csv")
    pop = s("census_co_est2025_fl.csv")
    age = s("census_agesex2025_fl.csv")

    pres = pd.read_csv(RAW / "pres2024.csv", dtype={"county_fips": str})
    pres = pres[pres.state_name == "Florida"].copy()
    pres["COUNTY"] = pres.county_fips.str[-3:]
    names = pres[["COUNTY", "county_name"]]

    state = {
        "g26": g26[g26.COUNTY == "000"].iloc[0],
        "hist": hist[hist.COUNTY == "000"].iloc[0],
        "pop": pop[pop.COUNTY == "000"].iloc[0],
    }
    df = (
        g26[g26.COUNTY != "000"]
        .merge(hist[hist.COUNTY != "000"], on="COUNTY")
        .merge(pop[pop.COUNTY != "000"], on="COUNTY")
        .merge(age, on="COUNTY")
        .merge(names, on="COUNTY")
        .merge(pres[["COUNTY", "per_dem", "per_gop", "total_votes"]].rename(columns={"total_votes": "tv24_tonmcg"}), on="COUNTY")
    )
    assert len(df) == 67, len(df)
    # cross-check NYT 2024 baseline against tonmcg
    chk = (df.margin_2024_dem - 100 * (df.per_dem - df.per_gop)).abs().max()
    assert chk < 0.01, chk
    assert (df.votes_2024 == df.tv24_tonmcg).all()

    df["county"] = df.county_name.str.replace(" County", "", regex=False)
    df["margin_2026_dem"] = 100 * (df.jolly_d - df.donalds_r) / df.total_votes
    df["shift_vs_2024"] = df.margin_2026_dem - df.margin_2024_dem
    df["shift_vs_2022"] = df.margin_2026_dem - df.margin_2022_dem
    df["turnout_retention"] = 100 * df.total_votes / df.votes_2024  # 2026 votes as % of 2024 votes
    df["pct_65plus"] = 100 * df.AGE65PLUS_TOT / df.POPESTIMATE
    # post-baseline domestic migration: Census "2025" = 1 Jul 2024 - 30 Jun 2025
    df["dommig_25"] = df.DOMESTICMIG2025
    df["dommig_25_rate"] = 100 * df.DOMESTICMIG2025 / df.POPESTIMATE2024
    # the boom years, 1 Jul 2020 - 30 Jun 2024 (these people were mostly already in the 2024 electorate)
    df["dommig_21_24"] = df[[f"DOMESTICMIG{y}" for y in range(2021, 2025)]].sum(axis=1)
    df["dommig_21_24_rate"] = 100 * df.dommig_21_24 / df.POPESTIMATE2024
    df["natchg_25_rate"] = 100 * df.NATURALCHG2025 / df.POPESTIMATE2024

    keep = ["COUNTY", "county", "POPESTIMATE2025", "pct_65plus", "votes_2022", "votes_2024", "total_votes",
            "margin_2022_dem", "margin_2024_dem", "margin_2026_dem", "shift_vs_2024", "shift_vs_2022",
            "turnout_retention", "dommig_25", "dommig_25_rate", "dommig_21_24", "dommig_21_24_rate",
            "natchg_25_rate", "eevp"]
    df = df[keep].rename(columns={"total_votes": "votes_2026", "POPESTIMATE2025": "pop_2025"})
    return df, state


if __name__ == "__main__":
    df, _ = load()
    OUT.mkdir(parents=True, exist_ok=True)
    df.round(3).to_csv(OUT / "fl_counties.csv", index=False)
    print(df.sort_values("shift_vs_2024").head(8).round(2).to_string(index=False))
