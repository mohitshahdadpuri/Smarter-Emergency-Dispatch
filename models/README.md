# Call-volume models

The web app forecasts the number of EMS calls in each San Francisco ZIP code
(ZCTA) for the current hour. Those forecasts drive the heat map and the
choice of ambulance waiting locations.

## Production model: `train_forecast.py`

```bash
pip install -r requirements.txt
python models/train_forecast.py
```

The script reads `data/ems_calls_resampled_v2.zip` (hourly call counts per ZIP,
April 2000 to October 2017). It then:

1. trains on 2010-01-01 to 2016-09-17 and scores every variant on the
   following 12 months (2016-09-18 to 2017-09-17);
2. refits the chosen model on all history from 2010 onward;
3. writes three files to `webapp/map/data/forecast/`:
   - `call_model.joblib`: the model;
   - `seasonal_profile.csv`: the fallback the app uses if the model can't
     be loaded;
   - `metrics.json`: the scores below.

The model is a `HistGradientBoostingRegressor` with a Poisson loss. It uses
the ZIP code, hour, weekday, month, day of year, US federal holidays and a
time trend. All of these are known in advance, so the app can forecast any
future hour without a live call feed.

### Results (held-out year, 236,520 ZIP-hours)

| Model | Poisson deviance | MAE | RMSE | City-wide hourly MAE |
|---|---|---|---|---|
| Seasonal profile (mean of last 2 years per ZIP × weekday × hour) | 0.8288 | 0.4655 | 0.6932 | 3.015 |
| **Gradient boosting, calendar features (production)** | **0.8200** | 0.4724 | 0.6920 | 2.941 |
| Gradient boosting + observed daily weather | 0.8168 | 0.4716 | 0.6911 | 2.926 |
| Gradient boosting + ACS population / age | 0.8179 | 0.4729 | 0.6907 | 2.915 |
| _Same model scored on a random 80/20 split_ | _0.7441_ | _0.4158_ | _0.6200_ | _1.091_ |

What the results show:

- **A random split looks far better than it is.** On the same model it
  reports a city-wide hourly error of 1.09 calls, against 2.94 when
  forecasting a year it has never seen. The notebooks in this folder use a
  random split, so their scores are optimistic.
- **Weather and census data help very little.** Even with *observed*
  weather, which the app wouldn't have at forecast time, deviance improves
  by only about 0.4%. Census data improves it by about 0.25%. Neither is
  worth an extra runtime dependency, so production uses calendar features
  only.
- **Gradient boosting beats the seasonal profile** on Poisson deviance and
  on city-wide error, the measures that matter for placing ambulances.
  The profile has a slightly lower per-ZIP MAE because MAE rewards
  predicting the median, which is 0 for most ZIP-hours.

### Limitations

- The data stops in October 2017, and average hourly call volume rose
  about 30% between 2010 and 2016. Tree models don't extrapolate trends, so
  forecasts for later years assume 2017 demand levels. To refresh the model, export newer calls
  from [Fire Department Calls for Service](https://data.sfgov.org/Public-Safety/Fire-Department-Calls-for-Service/nuek-vuh3)
  in the same hourly-per-ZIP format and rerun the script.
- `call_model.joblib` is a pickle tied to the pinned scikit-learn version.
  After upgrading scikit-learn, rerun the script. Until then the app logs a
  warning and uses the seasonal profile.

## Exploratory notebooks

`0 - Baseline Model.ipynb` (Poisson / negative-binomial GLMs),
`1 - NN model.ipynb`, `2 - LSTM model.ipynb` and `3 - XGB Model.ipynb` are
the original 2017 experiments. They are kept as written. As noted at the
top of each, their scores come from a random split.
