import json
import requests
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

country_borders = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_110m_admin_0_countries.geojson"

def process_ring(ring):
        return [(lat, lon) for lon, lat in list(ring.coords)]

def extract_coords(geom):
    coords_list = []
    if geom.geom_type == "Polygon":
        coords_list.append(process_ring(geom.exterior))
        for interior in geom.interiors:
            coords_list.append(process_ring(interior))
    elif geom.geom_type == "MultiPolygon":
        for poly in geom.geoms:
            coords_list.append(process_ring(poly.exterior))
            for interior in poly.interiors:
                coords_list.append(process_ring(interior))
    return coords_list

def download_world_borders():
    data = requests.get(country_borders).json()
    countries = {}

    for feature in data["features"]:
        name = feature["properties"]["name"]
        geom = shape(feature["geometry"])
        countries[name] = geom

    # trying not to go to jail :c
    if "W. Sahara" in countries and "Morocco" in countries:
        morocco_geom = countries["Morocco"]
        ws_geom = countries["W. Sahara"]
        merged_geom = morocco_geom.union(ws_geom) 
        countries["Morocco"] = merged_geom
        del countries["W. Sahara"]

    countries_coords = {name: extract_coords(geom) for name, geom in countries.items()}
    return countries_coords
