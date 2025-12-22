import os
import math
import requests
from functools import lru_cache
import mapbox_vector_tile

# i dont care enough to hide my key
tile_url = "https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf?key=OOq4i3h6rwSRhzdd51Ls"

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

    # download + wrapping
    url = tile_url.format(z=z, x=x % (2**z), y=y)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.content

        # save to cache
        with open(cache_path, "wb") as f:
            f.write(data)

        return data
    except Exception as e:
        print(e)
        return None


@lru_cache(maxsize=4096)
def decode_mvt(z, x, y):
    raw = fetch_tile_raw(z, x, y)
    if not raw:
        return None

    try:
        return mapbox_vector_tile.decode(raw)
    except Exception as e:
        print("decode error:", e)
        return None

def fetch_and_decode_tile(z, x, y):
    # wrapper
    return decode_mvt(z, x, y)


def fetch_vector_tile_features(bbox_lonlat, screen_zoom):
    """
    Fetches and decodes vector tiles covering the given bounding box.
    bbox_lonlat: (lon_min, lat_min, lon_max, lat_max)
    screen_zoom: The current zoom multiplier from the main app
    """
    lon_min, lat_min, lon_max, lat_max = bbox_lonlat
    
    # 1. Calculate the span of the visible window in degrees
    lon_span = abs(lon_max - lon_min)
    
    # Safety check for invalid coordinates
    if lon_span <= 0:
        return []

    # 2. Map the visible degrees to a standard Web Mercator Zoom level (z)
    # The world is 360 degrees wide. 
    # At Z0, 1 tile = 360 degrees.
    # At Z1, 1 tile = 180 degrees.
    # Formula: z = log2(360 / degrees_visible)
    # We add 1.0 as a "buffer" to get slightly higher detail than the bare minimum.
    zoom_boost = max(0, math.log2(screen_zoom * 1e6))
    calc_z = math.log2(360.0 / lon_span) + 1.0 + zoom_boost
    
    # 3. Clamp the zoom between 0 and 14 (MapTiler Free Tier limits)
    tile_z = int(min(max(0, calc_z), 14))

    # 4. Get the list of tile coordinates (z, x, y) that cover this area
    tiles_to_get = tiles_for_bbox(lon_min, lat_min, lon_max, lat_max, tile_z)

    # 5. Fetch and decode the tiles
    features_list = []
    
    # Limit the number of tiles per fetch to prevent hanging (max 16 tiles)
    for (z, x, y) in tiles_to_get[:16]:
        decoded_data = fetch_and_decode_tile(z, x, y)
        if decoded_data:
            features_list.append((z, x, y, decoded_data))
            
    return features_list