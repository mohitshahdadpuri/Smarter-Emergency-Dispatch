"""Choose waiting locations ("posts") for available ambulances.

Each ZIP code's predicted calls are spread over a regular grid of points
inside that ZIP, and a demand-weighted k-means picks one post per available
ambulance. Ambulances are then matched to posts so that the total distance
driven is as small as possible, and units already close to their post stay
where they are.

Distances are straight-line meters in a projected coordinate system, not
drive times.
"""
from functools import lru_cache
from pathlib import Path

import geopandas
import numpy as np
import pandas as pd
import shapely
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist
from sklearn.cluster import KMeans

SHAPE_PATH = Path(__file__).resolve().parent / "data" / "sf_zcta" / "sf_zcta.shp"
REGION_ID_COL = "ZCTA5CE10"
GEOGRAPHIC_CRS = "EPSG:4326"
PROJECTED_CRS = "EPSG:32610"  # UTM zone 10N, in meters
GRID_SPACING_M = 250
MIN_MOVE_M = 400


@lru_cache(maxsize=None)
def load_regions(shape_path=SHAPE_PATH):
    """ZIP code polygons as a GeoDataFrame with ``zcta`` and ``geometry`` columns.

    The result is cached, so callers must not modify it in place.
    """
    gdf = geopandas.read_file(shape_path)
    if gdf.crs is None:
        # The census shapefile ships without a .prj; its coordinates are lon/lat.
        gdf = gdf.set_crs(GEOGRAPHIC_CRS)
    gdf = gdf.rename(columns={REGION_ID_COL: "zcta"})
    gdf["zcta"] = gdf["zcta"].astype(str)
    return gdf[["zcta", "geometry"]].to_crs(GEOGRAPHIC_CRS)


@lru_cache(maxsize=None)
def _projected_regions():
    return load_regions().to_crs(PROJECTED_CRS)


def demand_points(predictions, spacing_m=GRID_SPACING_M):
    """Grid points inside every ZIP, weighted by that ZIP's predicted calls.

    ``predictions`` has ``zcta`` and ``call_counts`` columns. Each ZIP's point
    weights sum to its predicted calls; ZIPs with no (or missing) prediction
    get no points. If no ZIP has any predicted calls, every point gets the
    same weight so posts still spread across the city.

    Returns a DataFrame of projected ``x``/``y`` coordinates and ``weight``.
    """
    regions = _projected_regions()
    calls = (
        pd.to_numeric(predictions["call_counts"], errors="coerce")
        .groupby(predictions["zcta"].astype(str))
        .sum()
    )
    calls = calls[np.isfinite(calls) & (calls > 0) & calls.index.isin(regions["zcta"])]
    uniform = calls.empty

    frames = []
    for zcta, geom in zip(regions["zcta"], regions.geometry):
        if not uniform and zcta not in calls.index:
            continue
        x0, y0, x1, y1 = geom.bounds
        gx, gy = np.meshgrid(np.arange(x0 + spacing_m / 2, x1, spacing_m), np.arange(y0 + spacing_m / 2, y1, spacing_m))
        gx, gy = gx.ravel(), gy.ravel()
        inside = shapely.contains_xy(geom, gx, gy)
        if inside.any():
            px, py = gx[inside], gy[inside]
        else:  # ZIP smaller than one grid cell
            point = geom.representative_point()
            px, py = np.array([point.x]), np.array([point.y])
        weight = 1.0 if uniform else calls[zcta] / len(px)
        frames.append(pd.DataFrame({"zcta": zcta, "x": px, "y": py, "weight": weight}))
    return pd.concat(frames, ignore_index=True)


def choose_posts(points, count, random_state=0):
    """Pick ``count`` posts (projected x/y array) minimizing demand-weighted distance.

    Each k-means center is snapped to its nearest demand point, so posts are
    always inside a ZIP polygon (on land) rather than in the bay or ocean.
    """
    count = min(count, len(points))
    if count == 0:
        return np.empty((0, 2))
    xy = points[["x", "y"]].to_numpy()
    kmeans = KMeans(n_clusters=count, n_init=10, random_state=random_state)
    kmeans.fit(xy, sample_weight=points["weight"].to_numpy())
    nearest = cdist(kmeans.cluster_centers_, xy).argmin(axis=1)
    return xy[nearest]


def _project(lon, lat, source, target):
    points = geopandas.GeoSeries(geopandas.points_from_xy(lon, lat), crs=source).to_crs(target)
    return np.column_stack([points.x, points.y])


def update_ambulance_assignments(ambulances, predictions, min_move_m=MIN_MOVE_M):
    """Move every available ambulance to a post chosen from the current predictions.

    ``ambulances`` has ``amb_id``, ``LAT``, ``LONG`` and ``AVAILABLE`` columns;
    ``predictions`` has ``zcta`` and ``call_counts``. Returns a DataFrame
    indexed by ``amb_id`` with updated ``LAT``/``LONG`` and a boolean
    ``moved`` column. Units already within ``min_move_m`` of their assigned
    post are left in place to avoid shuffling ambulances back and forth.
    """
    result = ambulances.set_index("amb_id")[["LAT", "LONG", "AVAILABLE"]].astype(float)
    result["AVAILABLE"] = result["AVAILABLE"].astype(int)
    result["moved"] = False
    available = result[result["AVAILABLE"] == 1]
    if available.empty:
        return result

    posts = choose_posts(demand_points(predictions), len(available))
    current = _project(available["LONG"], available["LAT"], GEOGRAPHIC_CRS, PROJECTED_CRS)
    distances = cdist(current, posts)
    rows, cols = linear_sum_assignment(distances)
    posts_lonlat = _project(posts[:, 0], posts[:, 1], PROJECTED_CRS, GEOGRAPHIC_CRS)

    for row, col in zip(rows, cols):
        if distances[row, col] < min_move_m:
            continue
        amb_id = available.index[row]
        result.loc[amb_id, ["LONG", "LAT"]] = posts_lonlat[col]
        result.loc[amb_id, "moved"] = True
    return result
