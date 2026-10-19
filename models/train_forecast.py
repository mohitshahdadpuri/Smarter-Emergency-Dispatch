"""Train and evaluate the hourly call-volume model used by the web app.

Unlike the exploratory notebooks in this folder, evaluation here uses a
time-based split: every model is fit on data up to a cutoff and scored on
the 12 months that follow, which is how a forecast is used in practice.
A random split is also scored to show how much it overstates accuracy.

Usage (from the repository root):

    python models/train_forecast.py

Writes ``call_model.joblib``, ``seasonal_profile.csv`` and ``metrics.json``
to ``webapp/map/data/forecast/``.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_poisson_deviance, mean_squared_error
from sklearn.model_selection import train_test_split

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "webapp"))
from map.forecast import CALENDAR_FEATURES, FORECAST_DIR, calendar_features  # noqa: E402

CALLS_PATH = REPO / "data" / "ems_calls_resampled_v2.zip"
WEATHER_PATH = REPO / "data" / "wx_data" / "agg_wx_data.csv"
POPULATION_PATH = REPO / "data" / "population_and_demo" / "agg_pop_demo_data.csv"

WEATHER_FEATURES = ["TMAX", "TMIN", "PRCP", "AWND"]
POPULATION_FEATURES = ["population", "pct_65_plus"]
PROFILE_YEARS = 2


def load_calls(start):
    df = pd.read_csv(
        CALLS_PATH,
        usecols=["zcta_first", "Received_DtTm_min", "Call_Number"],
        parse_dates=["Received_DtTm_min"],
    )
    df = df.rename(columns={"zcta_first": "zcta", "Received_DtTm_min": "timestamp", "Call_Number": "calls"})
    df["zcta"] = df["zcta"].astype(str)
    return df[df["timestamp"] >= start].reset_index(drop=True)


def load_weather():
    weather = pd.read_csv(WEATHER_PATH, parse_dates=["DATE"])
    return weather.rename(columns={"DATE": "date"})[["date"] + WEATHER_FEATURES]


def load_population():
    raw = pd.read_csv(POPULATION_PATH, low_memory=False)
    pop = pd.DataFrame(
        {
            "zcta": raw["Id2"].astype(str),
            "year": raw["Year"].astype(int),
            "population": pd.to_numeric(raw["Estimate; SEX AND AGE - Total population"], errors="coerce"),
            "pct_65_plus": pd.to_numeric(raw["Percent; SEX AND AGE - 65 years and over"], errors="coerce"),
        }
    )
    return pop[pop["zcta"].str.startswith("941")]


def build_features(calls, zctas, weather, population):
    X = calendar_features(calls, zctas)
    dates = calls["timestamp"].dt.normalize()
    X[WEATHER_FEATURES] = dates.to_frame("date").merge(weather, on="date", how="left")[WEATHER_FEATURES].to_numpy()
    # ACS estimates only cover 2011-2015, so clamp other years to the nearest survey.
    years = calls["timestamp"].dt.year.clip(population["year"].min(), population["year"].max())
    keys = pd.DataFrame({"zcta": calls["zcta"].to_numpy(), "year": years.to_numpy()})
    X[POPULATION_FEATURES] = keys.merge(population, on=["zcta", "year"], how="left")[POPULATION_FEATURES].to_numpy()
    return X


def gbm(features):
    return HistGradientBoostingRegressor(
        loss="poisson",
        learning_rate=0.1,
        max_iter=300,
        max_leaf_nodes=63,
        categorical_features=[features.index("zcta_code")],
        early_stopping=False,
        random_state=0,
    )


def seasonal_profile(calls, years=PROFILE_YEARS):
    recent = calls[calls["timestamp"] > calls["timestamp"].max() - pd.DateOffset(years=years)]
    profile = (
        recent.assign(day_of_week=recent["timestamp"].dt.dayofweek, hour=recent["timestamp"].dt.hour)
        .groupby(["zcta", "day_of_week", "hour"], as_index=False)["calls"]
        .mean()
        .rename(columns={"calls": "call_counts"})
    )
    return profile


def predict_profile(profile, calls):
    keys = pd.DataFrame(
        {
            "zcta": calls["zcta"].to_numpy(),
            "day_of_week": calls["timestamp"].dt.dayofweek.to_numpy(),
            "hour": calls["timestamp"].dt.hour.to_numpy(),
        }
    )
    return keys.merge(profile, on=["zcta", "day_of_week", "hour"], how="left")["call_counts"].fillna(0).to_numpy()


def score(y_true, y_pred, timestamps):
    y_pred = np.clip(y_pred, 1e-6, None)
    citywide = pd.DataFrame({"t": timestamps.to_numpy(), "y": y_true, "p": y_pred}).groupby("t")[["y", "p"]].sum()
    return {
        "poisson_deviance": round(float(mean_poisson_deviance(y_true, y_pred)), 4),
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "citywide_hourly_mae": round(float(mean_absolute_error(citywide["y"], citywide["p"])), 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2010-01-01", help="ignore history before this date")
    parser.add_argument("--test-days", type=int, default=365, help="length of the held-out window")
    parser.add_argument("--out", type=Path, default=FORECAST_DIR)
    args = parser.parse_args()

    t0 = time.time()
    calls = load_calls(pd.Timestamp(args.start))
    weather = load_weather()
    population = load_population()
    zctas = sorted(calls["zcta"].unique())
    X = build_features(calls, zctas, weather, population)
    y = calls["calls"].to_numpy()

    # Hold out the last year that still has weather observations, so all
    # variants are scored on exactly the same hours.
    test_end = weather["date"].max() + pd.Timedelta(hours=23)
    test_start = test_end.normalize() - pd.Timedelta(days=args.test_days - 1)
    train = (calls["timestamp"] < test_start).to_numpy()
    test = ((calls["timestamp"] >= test_start) & (calls["timestamp"] <= test_end)).to_numpy()
    print(f"train {calls['timestamp'][train].min()} .. {calls['timestamp'][train].max()} ({train.sum():,} rows)")
    print(f"test  {test_start} .. {test_end} ({test.sum():,} rows)")

    results = {}
    profile = seasonal_profile(calls[train])
    results["seasonal profile (last 2 years)"] = score(y[test], predict_profile(profile, calls[test]), calls["timestamp"][test])

    variants = {
        "gradient boosting: calendar": CALENDAR_FEATURES,
        "gradient boosting: calendar + weather": CALENDAR_FEATURES + WEATHER_FEATURES,
        "gradient boosting: calendar + census": CALENDAR_FEATURES + POPULATION_FEATURES,
    }
    for name, features in variants.items():
        model = gbm(features).fit(X.loc[train, features], y[train])
        results[name] = score(y[test], model.predict(X.loc[test, features]), calls["timestamp"][test])
        print(f"  {name}: {results[name]}")

    # The notebooks' approach: a random 80/20 split over the same period.
    window = train | test
    idx_train, idx_test = train_test_split(np.flatnonzero(window), test_size=0.2, random_state=1234)
    model = gbm(CALENDAR_FEATURES).fit(X.loc[idx_train, CALENDAR_FEATURES], y[idx_train])
    random_split = score(y[idx_test], model.predict(X.loc[idx_test, CALENDAR_FEATURES]), calls["timestamp"][idx_test])

    # Refit the production model on all history. It only uses calendar
    # features, which are known for any future hour.
    final = gbm(CALENDAR_FEATURES).fit(X[CALENDAR_FEATURES], y)
    args.out.mkdir(parents=True, exist_ok=True)
    trained_through = str(calls["timestamp"].max())
    joblib.dump(
        {
            "model": final,
            "features": CALENDAR_FEATURES,
            "zctas": zctas,
            "trained_through": trained_through,
            "sklearn_version": sklearn.__version__,
        },
        args.out / "call_model.joblib",
        compress=3,
    )
    seasonal_profile(calls).to_csv(args.out / "seasonal_profile.csv", index=False, float_format="%.4f")
    metrics = {
        "train_window": [str(calls["timestamp"][train].min()), str(calls["timestamp"][train].max())],
        "test_window": [str(test_start), str(test_end)],
        "time_split": results,
        "random_split_calendar_gbm": random_split,
        "production_model": "gradient boosting: calendar",
        "trained_through": trained_through,
    }
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

    print("\n| Model (time-based split) | Poisson deviance | MAE | RMSE | City-wide hourly MAE |")
    print("|---|---|---|---|---|")
    for name, m in results.items():
        print(f"| {name} | {m['poisson_deviance']} | {m['mae']} | {m['rmse']} | {m['citywide_hourly_mae']} |")
    m = random_split
    print(f"| _random split, calendar (for comparison)_ | {m['poisson_deviance']} | {m['mae']} | {m['rmse']} | {m['citywide_hourly_mae']} |")
    print(f"\nWrote model and profile to {args.out} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
