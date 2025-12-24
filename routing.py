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

def reverse_geocode(lon, lat):
    # get address from coords
    url = "https://nominatim.openstreetmap.org/reverse"
    headers = {
        'User-Agent': 'cartoascii/1.0 (test@nasa.gov)' 
    }
    
    params = {
        'lat': lat,
        'lon': lon,
        'format': 'json',
        'zoom': 18
    }
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()
        if 'display_name' in data:
            # simplify the address a bit
            addr = data['display_name']
            parts = addr.split(',')
            # return first 3 parts usually enough
            return ", ".join(parts[:3])
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
            # get the line bits
            geometry = data['features'][0]['geometry']['coordinates']
            
            # try to grab the text bits
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