import os
import math
import requests
from functools import lru_cache
import mapbox_vector_tile

# i dont care enough to hide my key
tile_url = "https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf?key=1ZYMvxU2tPyKhJIOyZDu"

# create cache
cache = os.path.join(os.path.dirname(__file__), "tile_cache")
os.makedirs(cache, exist_ok=True)

def lonlat_to_tile_xy(lon, lat, z):
    # long/lat to WebMercator tile coords
    lat = max(min(lat, 85.05112878), -85.05112878) # clamp

    # wtf
    x = (lon + 180.0) / 360.0 * (2 ** z)
    y = (1.0 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2.0 * (2 ** z)

    return int(x), int(y)


def tiles_for_bbox(lon_min, lat_min, lon_max, lat_max, z):
    # return tiles covering our bounding box
    x1, y1 = lonlat_to_tile_xy(lon_min, lat_min, z)
    x2, y2 = lonlat_to_tile_xy(lon_max, lat_max, z)

    xs = range(min(x1, x2), max(x1, x2) + 1)
    ys = range(min(y1, y2), max(y1, y2) + 1)

    return [(z, x, y) for x in xs for y in ys]

def tile_coords_to_lonlat(z, x, y, px, py, extent=4096):
    # converts vector tile internal coords to global lat/lon
    n = 2.0 ** z
    lon_deg = (x + px / extent) / n * 360.0 - 180.0
    # mercator formula reversal
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + py / extent) / n)))
    lat_deg = math.degrees(lat_rad)
    return lon_deg, lat_deg

## fecthing + caching
def tile_cache_path(z, x, y):
    return os.path.join(cache, f"tile_{z}_{x}_{y}.pbf")


@lru_cache(maxsize=4096)
def fetch_tile_raw(z, x, y):
    # download direclty or fecth from cache
    cache_path = tile_cache_path(z, x, y)

    # read cache if exists
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                return f.read()
        except:
            pass

    # download
    url = tile_url.format(z=z, x=x, y=y)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.content

        # save to cache
        with open(cache_path, "wb") as f:
            f.write(data)

        return data
    except Exception as e:
        # oopsie daisy
        return None


@lru_cache(maxsize=4096)
def decode_mvt(z, x, y):
    raw = fetch_tile_raw(z, x, y)
    if not raw:
        return None

    try:
        return mapbox_vector_tile.decode(raw)
    except Exception as e:
        # print("decode error:", e)
        return None

def fetch_and_decode_tile(z, x, y):
    # wrapper
    return decode_mvt(z, x, y)


def fetch_vector_tile_features(bbox_lonlat, screen_zoom):
    # fetch tile features
    lon_min, lat_min, lon_max, lat_max = bbox_lonlat

    # map screen zoom to tile zoom
    tile_z = int(min(max(4, round(math.log2(screen_zoom + 1) + 5)), 16))
    tiles = tiles_for_bbox(lon_min, lat_min, lon_max, lat_max, tile_z)

    out = []
    for (z, x, y) in tiles:
        decoded = fetch_and_decode_tile(z, x, y)
        if decoded:
            out.append(decoded)
    return out