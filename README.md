# Smarter-Emergency-Dispatch

###### Our Mission
Fire and ambulance services across the country depend on technology to help save lives. That technology is sorely outdated, has caused dangerous delays and even cost people their lives. SmartDispatch aides emergency care dispatchers in distributing ambulances according to emergency service (EMS) distributions to improve response times, reduce cost, and reduce human error.

Smart Dispatch addresses three key obstacles dispatchers face.

###### How many calls will happen and where?
Most dispatching systems in use today do not have any predictive components. However, many municipalities maintain records of emergency calls and response times that stretch back years. SmartDispatch leverages this historical data to predict the number of calls in a given area on an hourly basis, so dispatchers have a clearer understanding of what to expect.

###### Who should respond to each call?
Dispatchers often rely on institutional and geographic knowledge of their regions to assign emergency units to calls. This means critical choices in sometimes life-threatening situations are vulnerable to human error and bias. SmartDispatch automates these choices and accounts for existing traffic conditions. Response times are minimized, and dispatchers can focus on other critical tasks.

###### Where should ambulances wait while not in service?
Unlike brick and mortar firehouses, ambulances and emergency vehicles don’t have fixed stations at which to wait while not responding to a call. Instead, planners and dispatchers must choose post locations for their ambulances. Currently there is no standardized process for selecting these post locations, nor is there an agreed upon system for updating these locations. SmartDispatch addresses these inconsistencies by assigning post locations that position ambulances nearest the areas with the highest concentration of predicted calls. Additionally, these post locations can be updated at any desired frequency.

###### Benefits
By bringing predictive analytics and automation to emergency call centers, SmartDispatch equips dispatchers with the tools they need to get their jobs done efficiently and effectively and to deliver the best care possible to people in need.

## How it works

| Step | Implementation |
|---|---|
| Forecast calls per ZIP code for the current hour | Gradient-boosted Poisson model trained on SF Fire Department calls, 2010–2017 (`webapp/map/forecast.py`, trained by `models/train_forecast.py`). Forecasts are generated on demand for any date and cached in the `Predictions` table. |
| Dispatch the best ambulance | Google Distance Matrix drive times in current traffic; falls back to straight-line distance when no API key is set or Google returns no route (`webapp/map/dispatch.py`). |
| Choose waiting posts | Demand-weighted k-means over a 250 m grid inside each ZIP. Posts are snapped to land, ambulances are matched to posts with the Hungarian algorithm, and units within 400 m of their post stay put (`webapp/map/placement.py`). |

The dispatcher console (`/map/`) records a call, sends an ambulance, repositions the remaining units, and shows everything on a folium map with a live event feed.

## Repository layout

```
webapp/                 Django 5.2 app
  smartdispatch/        project settings, URLs, Celery config
  map/                  dispatcher console, forecasting, dispatch and placement logic, tests
  django_sb_admin/      site theme (landing page, Tableau charts, about)
models/                 forecast training script and the original 2017 notebooks
data/                   historical calls, weather, census and ZIP shapes
archive/                earlier experiments, kept for reference
```

## Running locally

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd webapp
export DJANGO_DEBUG=1                # local development only
python manage.py migrate
python manage.py load_data           # loads the 10 sample ambulances
python manage.py runserver
```

Open <http://127.0.0.1:8000/map/>. Without a Google Maps key, enter calls as coordinates, e.g. `37.7793, -122.4193`.

Run the tests with `DJANGO_DEBUG=1 python manage.py test` from `webapp/`.

### Configuration

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Required unless `DJANGO_DEBUG=1`. |
| `DJANGO_DEBUG` | `1` for local development; off by default. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated host names (default `localhost,127.0.0.1`). |
| `DJANGO_DB_PATH` | SQLite file location (default `webapp/db.sqlite3`). |
| `GGL_API_KEY` | Google Maps key with the Geocoding and Distance Matrix APIs enabled. Optional. |
| `CELERY_BROKER_URL` | Broker for the optional hourly forecast refresh (`celery -A smartdispatch worker --beat`). Default `amqp://guest@localhost//`. |

To show precomputed forecasts instead of the model's, run `python manage.py load_data --predictions ../data/ems_calls_predict_mod2.csv`. Hours covered by the file take precedence.

## Model results

Scored on a held-out year (2016-09 to 2017-09). Full details are in [`models/README.md`](models/README.md).

| Model | Poisson deviance | City-wide hourly MAE (calls) |
|---|---|---|
| Seasonal profile baseline | 0.829 | 3.02 |
| Gradient boosting, calendar features (production) | 0.820 | 2.94 |
| Same model, random split (as in the 2017 notebooks) | 0.744 | 1.09 |

The random split overstates accuracy roughly threefold on city-wide error. Weather and census features improved deviance by less than 0.5%, so production doesn't use them.

## Known limitations

- Waiting posts use straight-line distance, not drive time or road access.
- The training data ends in October 2017, so forecasts reflect 2017 demand levels until the model is retrained on newer data.
- The SQLite database serializes dispatches. A multi-dispatcher deployment should move to PostgreSQL, where the existing `select_for_update` locks take effect.

###### Contact Us
Melanie Costello: melanie.costello@berkeley.edu

Priya Gupta: priyagupta@berkeley.edu

Jason Harville: jlharville@berkeley.edu

James Peng: james.y.peng@berkeley.edu
