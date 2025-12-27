import json
import requests
import os
import threading
import time
import math
from shapely.geometry import shape
from shapely.ops import unary_union
import geopandas as gpd
import pandas as pd
import tempfile
import zipfile
import shutil
import concurrent.futures
from drawing_utils import *
from tiles import *

# download urls
country_borders = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_50m_admin_0_countries.geojson"
populated_places = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_10m_populated_places_simple.geojson"
roads_zip = "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_roads.zip"

# cache files
borders_cache = "cache_borders.json"
cities_cache = "cache_cities.json"
roads_cache = "cache_roads.pkl"

class TileManager:
    def __init__(self, max_cache_size=200):
        self.tiles = {}  # {(z, x, y): [features]}
        self.lock = threading.Lock()
        self.max_cache_size = max_cache_size
        self.requested_tiles = set() 

    def get_tile(self, z, x, y):
        return self.tiles.get((z, x, y))

    def add_tile(self, z, x, y, features):
        with self.lock:
            # simple eviction
            if len(self.tiles) > self.max_cache_size:
                try:
                    for _ in range(5):
                        self.tiles.pop(next(iter(self.tiles)))
                except KeyError:
                    pass
            self.tiles[(z, x, y)] = features
            if (z, x, y) in self.requested_tiles:
                self.requested_tiles.remove((z, x, y))

    def is_fetching(self, z, x, y):
        with self.lock:
            return (z, x, y) in self.requested_tiles

    def mark_fetching(self, z, x, y):
        with self.lock:
            self.requested_tiles.add((z, x, y))

    def has_pending_downloads(self):
        with self.lock:
            return len(self.requested_tiles) > 0

class mapData:
    def __init__(self):
        self.projected_map_full = []
        self.roads_data = []
        self.countries_coords = []
        self.data_loaded = False
        self.status = "Initializing..."
        self.progress = 0.0
        
        # routing stuff
        self.start_marker = None 
        self.end_marker = None   
        self.route_poly = []     
        self.route_instructions = [] 
        self.active_mode = "VIEW" 

        # reverse geo
        self.current_address = ""
        self.address_lock = threading.Lock()

        self.tile_manager = TileManager()
        self.fetch_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def shutdown(self):
        self.fetch_executor.shutdown(wait=False)

class FastCoordinateTransformer:
    def __init__(self, z, x, y, extent=4096):
        self.n = 2.0 ** z
        self.x_offset = x
        self.y_offset = y
        self.extent = extent
        self.pi = math.pi
        self.mercator_const = 85.051129

    def tile_to_mercator(self, px, py):
        lon_deg = (self.x_offset + px / self.extent) / self.n * 360.0 - 180.0
        
        val = self.pi * (1 - 2 * (self.y_offset + py / self.extent) / self.n)
        lat_rad = math.atan(math.sinh(val))
        lat_deg = math.degrees(lat_rad)

        if lat_deg > self.mercator_const: lat_deg = self.mercator_const
        if lat_deg < -self.mercator_const: lat_deg = -self.mercator_const
        
        mx = lon_deg
        lat_rad = math.radians(lat_deg)
        my = math.log(math.tan((self.pi / 4) + (lat_rad / 2)))
        my = math.degrees(my)
        
        return mx, my

def process_ring(ring):
    if ring.is_empty: return []
    coords = []
    for lon, lat in ring.coords:
        mx, my = mercator_project(lat, lon)
        coords.append((mx, my))
    return coords

def geom_to_poly_list(geom):
    polys = []
    if geom.geom_type == "Polygon":
        polys.append(process_ring(geom.exterior))
    elif geom.geom_type == "MultiPolygon":
        for poly in geom.geoms:
            polys.append(process_ring(poly.exterior))
    return polys

def download_borders(data_obj):
    data_obj.status = "Fetching Borders..."
    if os.path.exists(borders_cache):
        try:
            with open(borders_cache, 'r') as f: geojson = json.load(f)
        except: geojson = {}
    else:
        try:
            geojson = requests.get(country_borders).json()
            with open(borders_cache, 'w') as f: json.dump(geojson, f)
        except: return []

    countries = {}
    if 'features' in geojson:
        for feat in geojson['features']:
            name = feat['properties'].get('name', 'Unknown')
            countries[name] = shape(feat['geometry'])

    if "W. Sahara" in countries and "Morocco" in countries:
        morocco_geom = countries["Morocco"]
        ws_geom = countries["W. Sahara"]
        merged_geom = unary_union([morocco_geom, ws_geom])
        countries["Morocco"] = merged_geom.buffer(0)
        del countries["W. Sahara"]

    projected_map = []
    for geom in countries.values():
        polys = geom_to_poly_list(geom)
        for poly in polys:
            if not poly: continue
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            bbox = (min(xs), min(ys), max(xs), max(ys))
            projected_map.append({'bbox': bbox, 'geom': poly})

    return projected_map

def download_global_roads(data_obj):
    data_obj.status = "Fetching Global Roads..."
    if os.path.exists(roads_cache):
        try: return pd.read_pickle(roads_cache)
        except: pass

    try:
        resp = requests.get(roads_zip, stream=True)
        total = int(resp.headers.get('content-length', 0))
        tmp_zip = tempfile.mktemp()
        dl = 0
        
        with open(tmp_zip, 'wb') as f:
            for chunk in resp.iter_content(4096):
                dl += len(chunk)
                f.write(chunk)
                if total: data_obj.progress = 20 + int((dl/total)*30)
        
        tmp_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(tmp_zip, 'r') as z: z.extractall(tmp_dir)
        
        shp = [x for x in os.listdir(tmp_dir) if x.endswith('.shp')][0]
        gdf = gpd.read_file(os.path.join(tmp_dir, shp))
        
        if 'scalerank' in gdf.columns:
            gdf = gdf[gdf['scalerank'] <= 8]

        processed_roads = []
        for _, row in gdf.iterrows():
            geom = row['geometry']
            parts = geom.geoms if geom.geom_type == 'MultiLineString' else [geom]
            for part in parts:
                coords = []
                for lon, lat in part.coords:
                    mx, my = mercator_project(lat, lon)
                    coords.append((mx, my))
                if coords:
                    xs, ys = zip(*coords)
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    processed_roads.append({'bbox': bbox, 'geom': coords})

        pd.to_pickle(processed_roads, roads_cache)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if os.path.exists(tmp_zip): os.remove(tmp_zip)
        return processed_roads
    except:
        return []

def load_initial_data(data_obj):
    try:
        data_obj.projected_map_full = download_borders(data_obj)
        data_obj.progress = 50.0
        data_obj.roads_data = download_global_roads(data_obj)
        data_obj.progress = 80.0

        data_obj.status = "Fetching Cities..."
        if os.path.exists(cities_cache):
            with open(cities_cache, 'r') as f: c_data = json.load(f)
        else:
            c_data = requests.get(populated_places).json()
            with open(cities_cache, 'w') as f: json.dump(c_data, f)

        cities = []
        if 'features' in c_data:
            for feat in c_data['features']:
                props = feat['properties']
                pop = props.get('pop_max', props.get('POP_MAX', 0))
                
                if pop > 1000:
                    lon, lat = feat['geometry']['coordinates']
                    mx, my = mercator_project(lat, lon)
                    cities.append({
                        'name': props.get('name', 'Unknown'),
                        'pop': pop,
                        'coords': (mx, my)
                    })
        
        data_obj.countries_coords = sorted(cities, key=lambda x: x['pop'], reverse=True)
        data_obj.progress = 100.0
        data_obj.status = "Ready"
        data_obj.data_loaded = True

    except Exception as e:
        data_obj.status = f"Error: {str(e)}"
        data_obj.data_loaded = True

def sanitize_label(props):
    name = props.get('name:en', props.get('name', ''))
    return "".join([c for c in str(name) if ord(c) < 128]).strip()

def process_single_tile(z, x, y):
    # downloads and processes a single tile
    raw = fetch_and_decode_tile(z, x, y)
    if not raw: return []

    new_features = []
    transformer = FastCoordinateTransformer(z, x, y)
    
    # tolerance for simplification
    SIMPLIFY_TOL = 0.00005 

    # roads
    if 'transportation' in raw:
        for f in raw['transportation']['features']:
            props = f['properties']
            r_class = props.get('class', 'street')
            name = props.get('name', '') 
            
            if r_class in ['path', 'track']: continue
            
            # color based on type of road
            road_color = 2
            road_priority = 2

            if r_class in ['primary', 'secondary']:
                road_color = 3
                road_priority = 3
            
            elif r_class in ['motorway', 'trunk']:
                road_color = 5
                road_priority = 4
            
            geoms = f['geometry']['coordinates']
            if f['geometry']['type'] == 'LineString': geoms = [geoms]
            elif f['geometry']['type'] != 'MultiLineString': continue
            
            for line in geoms:
                coords = []
                for px, py in line:
                    mx, my = transformer.tile_to_mercator(px, py)
                    coords.append((mx, my))
                
                # simplification
                if len(coords) > 2:
                    coords = simplify_polyline(coords, SIMPLIFY_TOL)

                if len(coords) > 1:
                    xs = [p[0] for p in coords]
                    ys = [p[1] for p in coords]
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    
                    new_features.append({
                        'type': 'road', 
                        'class': r_class,
                        'color_idx': road_color,
                        'z_index': road_priority,
                        'name': name, 
                        'coords': coords,
                        'bbox': bbox
                    })

    # buildings
    if 'building' in raw:
        for f in raw['building']['features']:
            geoms = f['geometry']['coordinates']
            if f['geometry']['type'] == 'Polygon': geoms = [geoms]
            elif f['geometry']['type'] != 'MultiPolygon': continue

            for poly in geoms:
                for ring in poly:
                    coords = []
                    for px, py in ring:
                        mx, my = transformer.tile_to_mercator(px, py)
                        coords.append((mx, my))
                    
                    # simplification stuff 
                    if len(coords) > 4:
                        coords = simplify_polyline(coords, SIMPLIFY_TOL)
                        
                    if len(coords) > 2:
                        # Pre-calculate BBox
                        xs = [p[0] for p in coords]
                        ys = [p[1] for p in coords]
                        bbox = (min(xs), min(ys), max(xs), max(ys))

                        new_features.append({
                            'type': 'building', 
                            'coords': coords,
                            'bbox': bbox
                        })
    
    # cities, towns, settlements
    if 'place' in raw:
        for f in raw['place']['features']:
            if f['geometry']['type'] == 'Point':
                props = f['properties']
                cls = props.get('class', '')
                
                # filter out suburbs/neighborhoods unless zoomed in deep
                if cls in ['neighbourhood', 'suburb', 'block']: continue
                
                name = sanitize_label(props)
                if name:
                    px, py = f['geometry']['coordinates']
                    mx, my = transformer.tile_to_mercator(px, py)
                    bbox = (mx, my, mx, my)
                    new_features.append({
                        'type': 'label', 
                        'name': name,
                        'rank': 1, # High priority
                        'coords': (mx, my),
                        'bbox': bbox
                    })

    # places of interests
    if 'poi' in raw:
        ALLOWED_POI = ['hospital', 'university', 'college', 'school', 'park', 'stadium', 'town_hall', 'attraction', 'museum']
        
        for f in raw['poi']['features']:
            props = f['properties']
            cls = props.get('class', '')
            sub = props.get('subclass', '')
            rank = props.get('rank', 100) 
            
            if rank <= 10 or cls in ALLOWED_POI or sub in ALLOWED_POI:
                name = sanitize_label(props)
                if name:
                    px, py = f['geometry']['coordinates']
                    mx, my = transformer.tile_to_mercator(px, py)
                    bbox = (mx, my, mx, my)
                    new_features.append({
                        'type': 'label',
                        'name': name,
                        'rank': 10, 
                        'coords': (mx, my),
                        'bbox': bbox
                    })

    return new_features

def fetch_tiles_background(data_obj, tiles_to_fetch):
    # worker function for tiles
    for i, (z, x, y) in enumerate(tiles_to_fetch):
        try:
            features = process_single_tile(z, x, y)
            data_obj.tile_manager.add_tile(z, x, y, features)
            time.sleep(0.005)
        except Exception as e:
            data_obj.tile_manager.add_tile(z, x, y, [])