import json
import requests
import overpy
import os
from shapely.geometry import shape, box, Point, mapping, MultiPolygon
from shapely.ops import unary_union

country_borders = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_110m_admin_0_countries.geojson"
populated_places = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_50m_populated_places.geojson"
borders_cache = "cache_borders.json"
cities_cache = "cache_cities.json"

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

    data = requests.get(populated_places).json()
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