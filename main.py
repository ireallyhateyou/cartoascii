import curses
import math
import time
import threading
import pandas as pd

# internal modules
from drawing_utils import *
from map_data import *

def main(stdscr):
    # set cursors up
    curses.curs_set(0) 
    stdscr.nodelay(True) 
    stdscr.timeout(100)
    curses.start_color()

    ## colours
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK) 
    curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLACK) 
    curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(6, curses.COLOR_BLUE, curses.COLOR_BLACK)
    
    # load datas
    stdscr.addstr(0, 0, "Loading dataset... (this requires internet!!)")
    stdscr.refresh()
    
    # multithreaded
    projected_map = []
    roads_data = []
    map_data = mapData()
    stop_event = threading.Event()
    loading_thread = threading.Thread(target=load_and_project_map, args=(map_data,))
    loading_thread.daemon = True
    loading_thread.start()
    
    def update_tiles_task():
        nonlocal cam_x, cam_y, zoom, width, height, aspect_ratio
        while not stop_event.is_set():
            if zoom >= 0.001:
                # Calculate current bounding box in Mercator
                view_half_w = (width / (2 * zoom * aspect_ratio))
                view_half_h = (height / (2 * zoom))
                
                # Convert Mercator bounds back to Lat/Lon for the API
                s = mercator_unproject(cam_y - view_half_h)
                n = mercator_unproject(cam_y + view_half_h)
                w = math.degrees((cam_x - view_half_w) / R)
                e = math.degrees((cam_x + view_half_w) / R)
                
                # Ensure values are passed in (South, West, North, East)
                map_data.update_local_features((min(s, n), w, max(s, n), e), zoom)
            time.sleep(1.0)

    tile_thread = threading.Thread(target=update_tiles_task, daemon=True)

    # camera and aspect ratio
    cam_x = 0.0
    cam_y = 0.0
    zoom = 0.00002
    aspect_ratio = 2.0 
    # threads & cache
    city_cache = {'bbox': None, 'cities': []}
    fetch_cities_thread = None
    fetch_local_thread = None
    # movement detection for lazy loading
    last_cam_x, last_cam_y = cam_x, cam_y
    last_move_time = time.time()
    running = True
    while running:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        cx, cy = width // 2, height // 2
       
        # update movement timer
        if cam_x != last_cam_x or cam_y != last_cam_y:
            last_move_time = time.time()
            last_cam_x, last_cam_y = cam_x, cam_y
        
        if map_data.data_loaded and not projected_map:
            projected_map = map_data.projected_map_full
            roads_data = map_data.roads_data

        # draw status bar if the data is not ready
        if not map_data.data_loaded:
            stdscr.addstr(1, 0, "processing country borders...", curses.color_pair(3))
            if map_data.error:
                stdscr.addstr(2, 0, map_data.error, curses.color_pair(4))
            
            # keep the hud
            info = f"Loading... | Pos: {cam_x:.1f}, {cam_y:.1f} | Zoom: {zoom:.1f} | Arr: Move | +/-: Zoom | q: Quit"
            stdscr.addstr(0, 0, info, curses.color_pair(3))

        if map_data.data_loaded:
            lon_span = width / (zoom * aspect_ratio)
            proj_lat_span = height / zoom

            # projected bounds of the screen/view
            view_mx_min = cam_x - lon_span / 2
            view_mx_max = cam_x + lon_span / 2
            view_my_min = cam_y - proj_lat_span / 2
            view_my_max = cam_y + proj_lat_span / 2

            if zoom >= 0.00005 and not tile_thread.is_alive():
                tile_thread.start()

            # fetch cities at zoom level
            if zoom >= 0.00005:
                try:
                    # figure out the bounds in lat/long
                    lon_span = width / (zoom * aspect_ratio)
                    proj_lat_span = height / zoom
                    lon_min = cam_x - lon_span / 2
                    lon_max = cam_x + lon_span / 2
                    proj_lat_min = cam_y - proj_lat_span / 2
                    proj_lat_max = cam_y + proj_lat_span / 2
                    
                    lat_min = mercator_unproject(proj_lat_min)
                    lat_max = mercator_unproject(proj_lat_max)

                    # create a bounding box from this
                    bbox = (lat_min, lon_min, lat_max, lon_max)
                    last_bbox = city_cache['bbox']
                    
                    should_fetch = False
                    if not last_bbox:
                        should_fetch = True
                    # check for movement between previous and current bbox
                    elif any(abs(bbox[i] - last_bbox[i]) > 0.05 for i in range(4)): 
                        should_fetch = True
                    
                    # launch thread if we should fetch a city
                    if should_fetch and (fetch_cities_thread is None or not fetch_cities_thread.is_alive()):
                        if fetch_cities_thread and fetch_cities_thread.is_alive():
                            # pass if already alive
                            pass
                        else:
                            fetch_cities_thread = threading.Thread(target=fetch_city_cache, args=(bbox, city_cache))
                            fetch_cities_thread.daemon = True
                            fetch_cities_thread.start()
                except Exception:
                    pass # ignore errors #thuglife

        # draw hud
        info = f"Pos: {cam_x:.1f}, {cam_y:.1f} | Zoom: {zoom:.1f} | Arr: Move | +/-: Zoom | q: Quit"
        stdscr.addstr(0, 0, info, curses.color_pair(3))

        simplify_tolerance_mx_my = 10000.0 if zoom < 0.0001 else 0.0

        # draw map
        for name, polys, cx_map, cy_map, bbox_mx_min, bbox_my_min, bbox_mx_max, bbox_my_max in projected_map:
            # culling check
            if (bbox_mx_max < view_mx_min or 
                bbox_mx_min > view_mx_max or 
                bbox_my_max < view_my_min or 
                bbox_my_min > view_my_max):
                continue # skip
            
            # draw labels if zoomed
            if zoom >= 1.5:
                if view_mx_min <= cx_map <= view_mx_max and view_my_min <= cy_map <= view_my_max:
                    # centroid to screenspace
                    tx_center = cx_map - cam_x
                    ty_center = cy_map - cam_y 
                    sx_center = (tx_center * zoom * aspect_ratio) + cx
                    sy_center = (-ty_center * zoom) + cy
                    
                    # draw name within bounds
                    if 0 <= sx_center < width - len(name) and 0 <= sy_center < height:
                        try:
                            stdscr.addstr(int(sy_center), int(sx_center), name, curses.color_pair(2))
                        except curses.error:
                            pass 

            for poly in polys:
                draw_country_poly(stdscr, poly, cam_x, cam_y, 
                        zoom, aspect_ratio, width, height, 
                        curses.color_pair(1), 
                        simplify_tolerance_mx_my)
                
        # draw roads     
        if zoom >= 0.00005 and roads_data:
            road_color = curses.color_pair(6)
            for road in roads_data:
                # get bbox
                min_mx, min_my, max_mx, max_my = road['bbox'] 
                
                # skip if it doesnt match our bbox
                if max_mx < view_mx_min or min_mx > view_mx_max or \
                   max_my < view_my_min or min_my > view_my_max:
                    continue
                
                # highlight important roads
                char = ord('.')
                if road['type'] in ['Major Highway', 'Secondary Highway']:
                    char = ord('#')
                
                draw_projected_polyline(stdscr, road['coords'], cam_x, cam_y, zoom, aspect_ratio, width, height, char, road_color)
            
        # draw features
        if zoom >= 0.001:
            is_moving = (time.time() - last_move_time < 0.2)
            margin_x = (view_mx_max - view_mx_min) * 0.2
            margin_y = (view_my_max - view_my_min) * 0.2
            cull_min_x, cull_max_x = view_mx_min - margin_x, view_mx_max + margin_x
            cull_min_y, cull_max_y = view_my_min - margin_y, view_my_max + margin_y
            for feat in map_data.local_features:
                # ignore if not in bounds
                xs = [p[0] for p in feat['coords']]
                ys = [p[1] for p in feat['coords']]
                if max(xs) < cull_min_x or min(xs) > cull_max_x or max(ys) < cull_min_y or min(ys) > cull_max_y:
                    continue
                if feat['type'] == 'building':
                    # draw buildings 
                    color = curses.color_pair(3) 
                    if not is_moving:
                        fill_poly_scanline(stdscr, feat['coords'], cam_x, cam_y, zoom, aspect_ratio, width, height, ord('/') | color)
                    # draw outline
                    draw_projected_polyline(stdscr, feat['coords'] + [feat['coords'][0]], cam_x, cam_y, zoom, aspect_ratio, width, height, ord('#') | color)
                elif feat['type'] == 'park':
                    # green fill
                    color = curses.color_pair(1)
                    fill_poly_scanline(stdscr, feat['coords'], cam_x, cam_y, zoom, aspect_ratio, width, height, ord('.') | color)
                elif feat['type'] == 'poi':
                    # draw POI
                    mx, my = feat['coords'][0]
                    tx = mx - cam_x
                    ty = my - cam_y
                    sx = int((tx * zoom * aspect_ratio) + cx)
                    sy = int((-ty * zoom) + cy)
                    
                    if 0 <= sx < width and 0 <= sy < height:
                        subtype = feat['subtype']
                        symbol = '?'
                        if subtype in ['cafe', 'restaurant', 'bar', 'pub', 'fast_food']: symbol = 'C'
                        elif subtype in ['bank', 'atm', 'bureau_de_change']: symbol = '$'
                        elif subtype in ['school', 'university']: symbol = 'S'
                        elif subtype == 'parking': symbol = 'P'
                        elif subtype == 'cinema': symbol = 'M'
                        elif subtype == 'pharmacy': symbol = '+'
                        
                        try:
                            stdscr.addch(sy, sx, ord(symbol) | curses.color_pair(5) | curses.A_BOLD)
                            # show name if there is space
                            # THIS IS BUGGY ASF
                            #if feat['name'] and zoom > 150:
                            #    stdscr.addstr(sy, sx+2, feat['name'][:15], curses.color_pair(5))
                        except: pass

        # draw cities when there are cities to draw
        cities_to_draw = city_cache['cities'] if zoom >= 0.00005 else []
        occupied_cells = set()
        if cities_to_draw:
            city_point_color = curses.color_pair(4) if curses.COLORS >= 5 else curses.color_pair(1)
            city_name_color = curses.color_pair(5) if curses.COLORS >= 5 else curses.color_pair(2)
            for city in cities_to_draw:
                lat, lon = city['lat'], city['lon']
                name = city['name']
                
                # project coords to lat, long
                tx, ty = mercator_project(lat, lon)
                
                # convert to screen coordinates
                sx = ((tx - cam_x) * zoom * aspect_ratio) + cx
                sy = (-(ty - cam_y) * zoom) + cy
                
                # print cities
                iy, ix = int(sy), int(sx)
                if 0 <= iy < height and 0 <= ix < width:
                    # Check if space is occupied
                    label_range = range(ix, min(width, ix + len(name) + 2))
                    if any((iy, x) in occupied_cells for x in label_range):
                        continue
                   
                    if name != "Bir Lehlou":
                        stdscr.addch(iy, ix, ord('*') | city_point_color)
                        stdscr.addstr(iy, min(width - 1, ix + 1), name, city_name_color)
                        # Mark as occupied
                        for x in label_range: occupied_cells.add((iy, x))

        # handle input
        try:
            key = stdscr.getch()
        except:
            key = -1

        move_speed = (width / zoom) * 0.05
        ## process input
        if key == ord('q'):
            running = False
            stop_event.set()
        elif key == curses.KEY_RIGHT:
            cam_x += move_speed
        elif key == curses.KEY_LEFT:
            cam_x -= move_speed
        elif key == curses.KEY_UP:
            cam_y += move_speed
        elif key == curses.KEY_DOWN:
            cam_y -= move_speed
        elif key == ord('=') or key == ord('+'):
            zoom *= 1.1
        elif key == ord('-') or key == ord('_'):
            zoom /= 1.1

if __name__ == "__main__":
    curses.wrapper(main)