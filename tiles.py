import os
import math
import requests
from functools import lru_cache
import mapbox_vector_tile

# i dont care enough to hide my key
tile_url = "https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf?key=tfWHRoE2TJX1nCjV1nkC"

# create cache
cache = os.path.join(os.path.dirname(__file__), "tile_cache")
os.makedirs(cache, exist_ok=True)

def lonlat_to_tile_xy(lon, lat, z):
    # long/lat to WebMercator tile coords
    lat = max(min(lat, 85.05112878), -85.05112878) # clamp
    x = (lon + 180.0) / 360.0 * (2 ** z)
    # wtf
    y = (1.0 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2.0 * (2 ** z)
    return int(x), int(y)

def tile_coords_to_lonlat(z, x, y, px, py, extent=4096):
    # Converts tile-relative pixel coordinates to global Lat/Lon
    n = 2.0 ** z
    lon_deg = (x + px / extent) / n * 360.0 - 180.0
    # Web Mercator latitude formula
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + py / extent) / n)))
    lat_deg = math.degrees(lat_rad)
    return lon_deg, lat_deg

def tiles_for_bbox(lon_min, lat_min, lon_max, lat_max, z):
    # return tiles covering our bounding box
    x1, y1 = lonlat_to_tile_xy(lon_min, lat_min, z)
    x2, y2 = lonlat_to_tile_xy(lon_max, lat_max, z)
    
    tiles = []
    for x in range(min(x1, x2), max(x1, x2) + 1):
        for y in range(min(y1, y2), max(y1, y2) + 1):
            tiles.append((x, y))
    return tiles

def fetch_tile_raw(z, x, y):
    # check cache first
    cache_path = os.path.join(cache, f"{z}_{x}_{y}.pbf")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f: return f.read()
        except: pass

    # download if needed
    url = tile_url.format(z=z, x=x, y=y)
    try:
        resp = requests.get(url, timeout=5) # 5s timeout to prevent hanging
        if resp.status_code == 200:
            with open(cache_path, "wb") as f: f.write(resp.content)
            return resp.content
    except:
        return None
    return None

@lru_cache(maxsize=128)
def fetch_and_decode_tile(z, x, y):
    raw = fetch_tile_raw(z, x, y)
    if not raw: return None
    try:
        return mapbox_vector_tile.decode(raw)
    except:
        return None