import curses
import math
import time
import threading
import pandas as pd

# internal modules
from utils import *
from load_data import *

# fetch city layers + cache
def fetch_city_cache(bbox, cache):
    new_cities = download_cities(bbox)
    cache['bbox'] = bbox
    cache['cities'] = new_cities

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
    
    try:
        countries = download_world_borders()
        roads_data = download_roads()
    except Exception as e:
        stdscr.addstr(2, 0, f"error loading data: {e}")
        stdscr.addstr(3, 0, "Please press q to quit :(")
        while True:
            if stdscr.getch() == ord('q'): return

    # project corods
    projected_map = []
    stdscr.addstr(1, 0, "Projecting coordinates...")
    stdscr.refresh()

    for name, parts in countries.items():
        country_polys = []
        all_mx, all_my, count = 0.0, 0.0, 0
        
        for part in parts:
            poly_points = []
            for lat, lon in part:
                mx, my = mercator_project(lat, lon)
                poly_points.append((mx, my))
                # centroid calculation
                all_mx += mx
                all_my += my
                count += 1
            country_polys.append(poly_points)
        
        centroid_x = all_mx / count if count > 0 else 0.0
        centroid_y = all_my / count if count > 0 else 0.0
        projected_map.append((name, country_polys, centroid_x, centroid_y))

    # camera and aspect ratio
    cam_x = 0.0
    cam_y = 0.0
    zoom = 1.0
    aspect_ratio = 2.0 
    city_cache = {'bbox': None, 'cities': []} 
    # threads
    fetch_cities_thread = None

    running = True
    while running:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        cx, cy = width // 2, height // 2
        
        # calculate the view's projected bounds (mx_min, my_min, etc.) ONCE
        lon_span = width / (zoom * aspect_ratio)
        proj_lat_span = height / zoom
        
        # projected bounds of the screen/view
        view_mx_min = cam_x - lon_span / 2
        view_mx_max = cam_x + lon_span / 2
        view_my_min = cam_y - proj_lat_span / 2
        view_my_max = cam_y + proj_lat_span / 2

        # fetch cities at zoom level
        if zoom >= 3.0:
            try:
                # figure out the bounding box in lat/long
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

        # draw map
        for name, polys, cx_map, cy_map in projected_map:
            # draw labels if zoomed
            if zoom >= 1.5:
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
                screen_points = []
                for mx, my in poly:
                    # transalte based on camera
                    tx = mx - cam_x
                    ty = my - cam_y
                    # to screen space
                    sx = (tx * zoom * aspect_ratio) + cx
                    sy = (-ty * zoom) + cy 
                    
                    screen_points.append((int(sx), int(sy)))

                # draw lines for borders
                for i in range(len(screen_points) - 1):
                    p1 = screen_points[i]
                    p2 = screen_points[i+1]
                    
                    # calcualte delta (destination)
                    dx = p2[0] - p1[0]
                    dy = p2[1] - p1[1]
                    
                    char = get_line_char(dx, dy) 
                    draw_line(stdscr, p1[0], p1[1], p2[0], p2[1], char | curses.color_pair(1))
                
                # close loop
                if screen_points:
                    p1 = screen_points[-1]
                    p2 = screen_points[0]
                    
                    dx = p2[0] - p1[0]
                    dy = p2[1] - p1[1]
                    char = get_line_char(dx, dy)
                    draw_line(stdscr, p1[0], p1[1], p2[0], p2[1], char | curses.color_pair(1))

        # draw roads     
        if zoom >= 5.0 and roads_data:
            road_color = curses.color_pair(6)
            for road in roads_data:
                # get bbox
                min_mx, min_my, max_mx, max_my = road['bbox'] 
                
                # skip if it doesnt match our bbox
                if max_mx < view_mx_min or min_mx > view_mx_max or \
                   max_my < view_my_min or min_my > view_my_max:
                    continue
                
                # highlight important roads
                char = ord('.') if zoom >= 10 else ord(' ')
                if road['type'] in ['Major Highway', 'Secondary Highway', 'State Highway']:
                    char = ord('#')
                    
                draw_projected_polyline(stdscr, road['coords'], cam_x, cam_y, zoom, aspect_ratio, width, height, char | road_color)
            
        # draw cities when there are cities to draw
        cities_to_draw = city_cache['cities'] if zoom >= 3.0 else []
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
                if 0 <= int(sy) < height and 0 <= int(sx) < width:
                    if name != "Bir Lehlou": # trying not to go to jail pt2
                        stdscr.addch(int(sy), int(sx), ord('*') | city_point_color)
                        stdscr.addstr(int(sy), min(width - 1, int(sx) + 1), name, city_name_color)

        # TODO: show city detail after zoom level >= 100 
        
        # handle input
        try:
            key = stdscr.getch()
        except:
            key = -1
        ## process input
        if key == ord('q'):
            running = False
        elif key == curses.KEY_RIGHT:
            cam_x += 10 / zoom
        elif key == curses.KEY_LEFT:
            cam_x -= 10 / zoom
        elif key == curses.KEY_UP:
            cam_y += 10 / zoom
        elif key == curses.KEY_DOWN:
            cam_y -= 10 / zoom
        elif key == ord('=') or key == ord('+'):
            zoom *= 1.1
        elif key == ord('-') or key == ord('_'):
            zoom /= 1.1

        # wrap around
        if cam_x > 180: cam_x -= 360
        if cam_x < -180: cam_x += 360

if __name__ == "__main__":
    curses.wrapper(main)