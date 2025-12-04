import json
import requests

country_borders = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_110m_admin_0_countries.geojson"

def download_world_borders():
    print("Downloading world borders...")
    data = requests.get(country_borders).json()
    countries = {}
    for feature in data["features"]:
        props = feature["properties"]
        name = props["name"]
        geometry = feature["geometry"]
        parts = []

        if geometry["type"] == "Polygon":
            for ring in geometry["coordinates"]:
                parts.append([(lat, lon) for lon, lat in ring])

        elif geometry["type"] == "MultiPolygon":
            for poly in geometry["coordinates"]:
                for ring in poly:
                    parts.append([(lat, lon) for lon, lat in ring])
                    
        # I'm trying not to get arrested shhh
        if "Western Sahara" in countries and "Morocco" in countries:
            countries["Morocco"].extend(countries["Western Sahara"])
            del countries["Western Sahara"]

        countries[name] = parts

    print("Loaded:", len(countries), "countries")
    return countries