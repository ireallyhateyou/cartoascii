import json
import requests

country_borders = "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_110m_admin_0_countries.geojson"

def download_world_borders():
    data = requests.get(country_borders).json()
    countries = {}

    # load all borders into dict
    for feature in data["features"]:
        props = feature["properties"]
        name = props["name"]
        geometry = feature["geometry"]
        parts = []

        if geometry["type"] == "Polygon":
            for i, ring in enumerate(geometry["coordinates"]):
                parts.append([(lat, lon) for lon, lat in ring])
        elif geometry["type"] == "MultiPolygon":
            for poly in geometry["coordinates"]:
                for i, ring in enumerate(poly):
                    parts.append([(lat, lon) for lon, lat in ring])

        countries[name] = parts
        
    # im trying not to go to jail
    if "W. Sahara" in countries and "Morocco" in countries:
        if len(countries["Morocco"]) > 1:
            countries["Morocco"] = [countries["Morocco"][0]]
        countries["Morocco"].extend(countries["W. Sahara"])
        del countries["W. Sahara"]
        
    return countries