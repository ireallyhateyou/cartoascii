import json
import requests
import os
import threading
from shapely.geometry import shape, MultiPolygon
from shapely.ops import unary_union
import geopandas as gpd
import pandas as pd
import tempfile
import zipfile
import shutil
from drawing_utils import mercator_project
from tiles import fetch_and_decode_tile, tile_coords_to_lonlat, tiles_for_bbox

# download urls
country_borders = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_50m_admin_0_countries.geojson"
populated_places = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_10m_populated_places_simple.geojson"
roads_zip = "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_roads.zip"

# cache files
borders_cache = "cache_borders.json"
cities_cache = "cache_cities.json"
roads_cache = "cache_roads.pkl"

class mapData:
    def __init__(self):
        self.countries_coords = []      # Cities
        self.projected_map_full = []    # Borders
        self.roads_data = []            # Global Roads
        self.local_features = []        # Local Tile Data
        
        self.data_loaded = False
        self.status = "Initializing..."
        self.progress = 0.0
        self.lock = threading.Lock()

def process_ring(ring):
    if ring.is_empty: return []
    coords = []
    # project mx/my immediately
    for lon, lat in ring.coords:
        mx, my = mercator_project(lat, lon)
        coords.append((mx, my))
    return coords

def geom_to_poly_list(geom):
    # flatten geometry to list of rings
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
        # load borders from cache
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

    # trying not to go to jail :c
    if "W. Sahara" in countries and "Morocco" in countries:
        morocco_geom = countries["Morocco"]
        ws_geom = countries["W. Sahara"]
        merged_geom = unary_union([morocco_geom, ws_geom])
        merged_geom = merged_geom.buffer(0)
        countries["Morocco"] = merged_geom
        del countries["W. Sahara"]

    projected_map = []
    projected_map = []
    for geom in countries.values():
        # get bbox for each country
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
        # pickle is faster than json for this much data
        try: return pd.read_pickle(roads_cache)
        except: pass

    try:
        resp = requests.get(roads_zip, stream=True)
        total = int(resp.headers.get('content-length', 0))
        tmp_zip = tempfile.mktemp()
        dl = 0
        
        # downloading chunks
        with open(tmp_zip, 'wb') as f:
            for chunk in resp.iter_content(4096):
                dl += len(chunk)
                f.write(chunk)
                if total: data_obj.progress = 20 + int((dl/total)*30)
        
        # unzip to temp dir
        tmp_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(tmp_zip, 'r') as z: z.extractall(tmp_dir)
        
        shp = [x for x in os.listdir(tmp_dir) if x.endswith('.shp')][0]
        gdf = gpd.read_file(os.path.join(tmp_dir, shp))
        
        # filter small roads for global view
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

        # save it to a cache :D
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
                # store pop so main.py can filter by it!
                pop = props.get('pop_max', props.get('POP_MAX', 0))
                
                if pop > 1000:
                    lon, lat = feat['geometry']['coordinates']
                    mx, my = mercator_project(lat, lon)
                    cities.append({
                        'name': props.get('name', 'Unknown'),
                        'pop': pop,
                        'coords': (mx, my)
                    })
        
        # sort by pop for drawing order
        data_obj.countries_coords = sorted(cities, key=lambda x: x['pop'], reverse=True)
        data_obj.progress = 100.0
        data_obj.status = "Ready"
        data_obj.data_loaded = True

    except Exception as e:
        data_obj.status = f"Error: {str(e)}"
        data_obj.data_loaded = True

def sanitize_label(props):
    # basic ascii cleanup
    name = props.get('name:en', props.get('name', ''))
    return "".join([c for c in str(name) if ord(c) < 128]).strip()

def fetch_local_details(data_obj, bbox, zoom):
    # determines tile zoom based on screen zoom
    z = 14 if zoom > 300 else 12
    l_min, b_min, l_max, b_max = bbox
    
    visible = tiles_for_bbox(l_min, b_min, l_max, b_max, z)
    
    new_features = []
    
    for tx, ty in visible:
        raw = fetch_and_decode_tile(z, tx, ty)
        if not raw: continue
        
        # roads
        if 'transportation' in raw:
            for f in raw['transportation']['features']:
                props = f['properties']
                r_class = props.get('class', 'street')
                name = props.get('name', '') 
                
                # skip walking paths usually
                if r_class in ['path', 'track']: continue

                geoms = f['geometry']['coordinates']
                if f['geometry']['type'] == 'LineString': geoms = [geoms]
                elif f['geometry']['type'] != 'MultiLineString': continue
                
                for line in geoms:
                    coords = []
                    for px, py in line:
                        lon, lat = tile_coords_to_lonlat(z, tx, ty, px, py)
                        mx, my = mercator_project(lat, lon)
                        coords.append((mx, my))
                    if len(coords) > 1:
                        new_features.append({
                            'type': 'road', 
                            'class': r_class, 
                            'name': name,
                            'coords': coords
                        })

        # buildings
        if 'building' in raw:
            for f in raw['building']['features']:
                geoms = f['geometry']['coordinates']
                if f['geometry']['type'] == 'Polygon': geoms = [geoms]
                for poly in geoms:
                    for ring in poly:
                        coords = []
                        for px, py in ring:
                            lon, lat = tile_coords_to_lonlat(z, tx, ty, px, py)
                            mx, my = mercator_project(lat, lon)
                            coords.append((mx, my))
                        if coords: new_features.append({'type': 'building', 'coords': coords})
        
        # labels
        if 'place' in raw:
            for f in raw['place']['features']:
                if f['geometry']['type'] == 'Point':
                    name = sanitize_label(f['properties'])
                    if name:
                        px, py = f['geometry']['coordinates']
                        lon, lat = tile_coords_to_lonlat(z, tx, ty, px, py)
                        mx, my = mercator_project(lat, lon)
                        new_features.append({'type': 'label', 'name': name, 'coords': (mx, my)})

    # thread safe update
    with data_obj.lock:
        data_obj.local_features = new_features