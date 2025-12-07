import json
import requests
import overpy
import os
from osmnx import features
from shapely.geometry import shape, box, Point, mapping, MultiPolygon
from shapely.ops import unary_union
import geopandas as gpd
import pandas as pd
import tempfile
import zipfile
import io 
from drawing_utils import mercator_project

# download urls
country_borders = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_50m_admin_0_countries.geojson"
populated_places = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_50m_populated_places.geojson"
roads_zip = "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_roads.zip"

# cache files
borders_cache = "cache_borders.json"
cities_cache = "cache_cities.json"
roads_cache = "cache_roads.json"

# async is good?
# TODO: put this in another file
class mapData:
    def __init__(self):
        self.countries_coords = None 
        self.roads_data = None
        self.projected_map_full = None
        self.data_loaded = False
        self.error = None
        # for overpass live data
        self.local_data_cache = {}
        self.local_features = []
        self.api = overpy.Overpass()

def fetch_local_details(data_obj, bbox_latlon):
    s, w, n, e = bbox_latlon
    # force max size
    lat_center = (s + n) / 2
    lon_center = (w + e) / 2
    limit = 0.015 
    
    if (n - s) > (limit * 2):
        s = lat_center - limit
        n = lat_center + limit
    if (e - w) > (limit * 2):
        w = lon_center - limit
        e = lon_center + limit

    # caching at high zoom
    grid_key = (round(s, 3), round(w, 3))
    if grid_key in data_obj.local_data_cache:
        data_obj.local_features = data_obj.local_data_cache[grid_key]
        return

    # queries
    query = f"""
        [out:json][timeout:25];
        (
          way["building"]({s},{w},{n},{e});
          way["leisure"="park"]({s},{w},{n},{e});
          node["amenity"]({s},{w},{n},{e});
        );
        (._;>;);
        out body;
    """
    
    try:
        result = data_obj.api.query(query)
        parsed_features = []

        # ways (buildings + parks)
        for way in result.ways:
            is_building = "building" in way.tags
            is_park = way.tags.get("leisure") == "park"
            
            coords = []
            for node in way.nodes:
                mx, my = mercator_project(float(node.lat), float(node.lon))
                coords.append((mx, my))
            
            if coords:
                ft_type = "building" if is_building else "park"
                parsed_features.append({
                    "type": ft_type,
                    "coords": coords,
                    "tags": way.tags
                })

        # nodes (POI)
        for node in result.nodes:
            if "amenity" in node.tags:
                mx, my = mercator_project(float(node.lat), float(node.lon))
                parsed_features.append({
                    "type": "poi",
                    "coords": [(mx, my)],
                    "name": node.tags.get("name", node.tags.get("amenity")),
                    "subtype": node.tags.get("amenity")
                })

        # update cache and data
        data_obj.local_data_cache[grid_key] = parsed_features
        data_obj.local_features = parsed_features

    except Exception as e:
        print(f"error {e}")

# data_obj is an instance of MapData
def load_and_project_map(data_obj): 
    try:
        data_obj.countries_coords = download_world_borders()
        data_obj.roads_data = download_roads()
        
        # project coordinates
        projected_map = []
        for name, parts in data_obj.countries_coords.items():
            country_polys = []
            all_mx, all_my, count = 0.0, 0.0, 0
            mx_min, my_min = float('inf'), float('inf')
            mx_max, my_max = float('-inf'), float('-inf')

            for part in parts:
                poly_points = []
                for lat, lon in part:
                    mx, my = mercator_project(lat, lon)
                    poly_points.append((mx, my))
                    
                    # centroid calculation
                    all_mx += mx
                    all_my += my
                    count += 1
                    mx_min = min(mx_min, mx)
                    my_min = min(my_min, my)
                    mx_max = max(mx_max, mx)
                    my_max = max(my_max, my)
                    
                country_polys.append(poly_points)
            
            centroid_x = all_mx / count if count > 0 else 0.0
            centroid_y = all_my / count if count > 0 else 0.0
            projected_map.append((name, country_polys, centroid_x, centroid_y, mx_min, my_min, mx_max, my_max))

        data_obj.projected_map_full = projected_map
        data_obj.data_loaded = True
    except Exception as e:
        data_obj.error = f"Error loading map data: {e}"

# fetch city layers + cache
def fetch_city_cache(bbox, cache):
    new_cities = download_cities(bbox)
    cache['bbox'] = bbox
    cache['cities'] = new_cities

def download_roads():
    # load from cache
    if os.path.exists(roads_cache):
        with open(roads_cache, 'r') as f:
            return json.load(f)

    # if not, download
    try:
        response = requests.get(roads_zip, timeout=60)
        response.raise_for_status() 
    except Exception as e:
        print(f"error {e}")
        return []

    # temporary open the zip and extract files
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_bytes = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_bytes, 'r') as zf:
            for filename in zf.namelist():
                if filename.startswith('ne_10m_roads.'):
                    zf.extract(filename, path=tmpdir)
        local_shp_path = os.path.join(tmpdir, 'ne_10m_roads.shp')
        try:
            gdf = gpd.read_file(local_shp_path) 
        except Exception as e:
            print(f"error readign file: {e}")
            return []

    roads = []
    for index, row in gdf.iterrows():
        geom = row.geometry
        road_type = row.get("type", "other") 
        coords_list_lon_lat = []

        if geom.geom_type == 'LineString':
            coords_list_lon_lat = list(geom.coords)
        elif geom.geom_type == 'MultiLineString':
            for line in geom.geoms:
                coords_list_lon_lat.extend(list(line.coords))
 
        if coords_list_lon_lat:
            # projects mx/my
            projected_coords = []
            min_mx, max_mx = float('inf'), float('-inf')
            min_my, max_my = float('inf'), float('-inf')
            
            for lon, lat in coords_list_lon_lat:
                mx, my = mercator_project(lat, lon)
                projected_coords.append((mx, my))
                min_mx = min(min_mx, mx)
                max_mx = max(max_mx, mx)
                min_my = min(min_my, my)
                max_my = max(max_my, my)

            roads.append({
                'coords': projected_coords, 
                'type': road_type,
                'bbox': (min_mx, min_my, max_mx, max_my) 
            })

    # save it to a cache :D
    with open(roads_cache, 'w') as f:
        json.dump(roads, f)
            
    return roads

def download_cities(bbox):
    south, west, north, east = bbox
    if os.path.exists(cities_cache):
        # load cities from the cache
        with open(cities_cache, 'r') as f:
            data = json.load(f)
    else: 
        data = requests.get(populated_places).json()
        with open(cities_cache, 'w') as f:
            json.dump(data, f)

    bbox_poly = box(west, south, east, north)
    cities = []

    for feature in data["features"]:
        props = feature["properties"]
        geom = shape(feature["geometry"])

        if not geom.within(bbox_poly):
            continue

        cities.append({
            "name": props.get("name") or props.get("NAME"),
            "lat": geom.y,
            "lon": geom.x,
            "pop": props.get("pop_max") or props.get("POP_MAX"),
            "rank": props.get("rank_max") or props.get("RANK_MAX"),
        })

    return cities

def process_ring(ring):
        return [(lat, lon) for lon, lat in list(ring.coords)]

def extract_coords(geom):
    # skip interior borders for now 
    coords_list = []
    if geom.geom_type == "Polygon":
        coords_list.append(process_ring(geom.exterior))
    elif geom.geom_type == "MultiPolygon":
        for poly in geom.geoms:
            coords_list.append(process_ring(poly.exterior))
    return coords_list

def download_world_borders():
    if os.path.exists(borders_cache):
        # load cities from the cache
        with open(borders_cache, 'r') as f:
            data = json.load(f)
    else: 
        data = requests.get(country_borders).json()
        with open(borders_cache, 'w') as f:
            json.dump(data, f)
    countries = {}

    for feature in data["features"]:
        name = feature["properties"]["name"]
        geom = shape(feature["geometry"])
        countries[name] = geom

    # trying not to go to jail :c
    if "W. Sahara" in countries and "Morocco" in countries:
        morocco_geom = countries["Morocco"]
        ws_geom = countries["W. Sahara"]
        merged_geom = unary_union([morocco_geom, ws_geom])
        merged_geom = merged_geom.buffer(0)
        merged_geom = merged_geom.simplify(0.01, preserve_topology=True)
        if merged_geom.geom_type == "MultiPolygon":
            merged_geom = MultiPolygon([p for p in merged_geom.geoms if p.area > 0.00001])
            if len(merged_geom.geoms) == 1:
                merged_geom = merged_geom.geoms[0]
        countries["Morocco"] = merged_geom
        del countries["W. Sahara"]

    countries_coords = {name: extract_coords(geom) for name, geom in countries.items()}
    return countries_coords