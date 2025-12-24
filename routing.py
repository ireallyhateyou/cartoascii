import requests
import json

apikey = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImUyMWU4MDUxYzQwYTQ5N2E4MmEzYmU4ZmRjYzdlYjliIiwiaCI6Im11cm11cjY0In0="

def geocode_address(address_str):
    url = "https://nominatim.openstreetmap.org/search"
    headers = {
        'User-Agent': 'cartoascii/1.0 (test@nasa.gov)' 
    }
    
    params = {
        'q': address_str,
        'format': 'json',
        'limit': 1
    }
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()
        if data:
            lat = float(data[0]['lat'])
            lon = float(data[0]['lon'])
            return (lon, lat)
    except Exception as e:
        print(f"geocode error: {e}")
        
    return None

def reverse_geocode(lon, lat, view_zoom=1.0):
    osm_zoom = 3
    if view_zoom > 1500: osm_zoom = 18
    elif view_zoom > 500: osm_zoom = 16
    elif view_zoom > 50: osm_zoom = 12
    elif view_zoom > 5: osm_zoom = 10
    
    url = "https://nominatim.openstreetmap.org/reverse"
    headers = {
        'User-Agent': 'cartoascii/1.0 (test@nasa.gov)' 
    }
    
    params = {
        'lat': lat,
        'lon': lon,
        'format': 'json',
        'zoom': osm_zoom,
        'addressdetails': 1
    }
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()
        
        if 'address' in data:
            a = data['address']
            parts = []
                        
            # based on zoom depth
            if osm_zoom >= 16:
                if 'house_number' in a: parts.append(a['house_number'])
                if 'road' in a: parts.append(a['road'])
                elif 'pedestrian' in a: parts.append(a['pedestrian'])
            
            if osm_zoom >= 10:
                if 'suburb' in a: parts.append(a['suburb'])
                elif 'city_district' in a: parts.append(a['city_district'])
                elif 'neighbourhood' in a: parts.append(a['neighbourhood'])
                
                if 'city' in a: parts.append(a['city'])
                elif 'town' in a: parts.append(a['town'])
                
            if osm_zoom < 10:
                if 'state' in a: parts.append(a['state'])
                if 'country' in a: parts.append(a['country'])
            
            if not parts and 'display_name' in data:
                return data['display_name'].split(',')[0]
            
            # dedup and join
            clean = []
            seen = set()
            for p in parts:
                if p not in seen:
                    clean.append(p)
                    seen.add(p)
                    
            return ", ".join(clean)
            
    except Exception as e:
        pass
        
    return None

def get_route(start_lon, start_lat, end_lon, end_lat, profile="driving-car"):
    # profiles: driving-car, foot-walking, cycling-regular
    url = f"https://api.openrouteservice.org/v2/directions/{profile}/geojson"
    headers = {
        'Authorization': apikey,
        'Content-Type': 'application/json; charset=utf-8'
    }
    body = {
        "coordinates": [[start_lon, start_lat], [end_lon, end_lat]]
    }
    
    try:
        r = requests.post(url, json=body, headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()
        
        geometry = []
        instructions = []

        if 'features' in data and data['features']:
            geometry = data['features'][0]['geometry']['coordinates']
            try:
                # openrouteservice structure features -> props -> segments -> steps
                segments = data['features'][0]['properties']['segments']
                for seg in segments:
                    for step in seg['steps']:
                        instructions.append(step.get('instruction', ''))
            except:
                pass

            return geometry, instructions

    except Exception as e:
        print(f"route error {e}")
        
    return [], []