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
    loading_thread = threading.Thread(target=load_and_project_map, args=(map_data,))
    loading_thread.daemon = True
    loading_thread.start()

    # camera and aspect ratio
    cam_x = 0.0
    cam_y = 0.0
    zoom = 1.0
    aspect_ratio = 2.0 
    # threads & cache
    city_cache = {'bbox': None, 'cities': []}
    fetch_cities_thread = None

    running = True
    while running:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        cx, cy = width // 2, height // 2
        
        if map_data.data_loaded and not projected_map:
            projected_map = map_data.projected_map_full
            roads_data = map_data.roads_data

        # draw status bar if the data is not ready
        if not map_data.data_loaded:
            stdscr.addstr(1, 0, "processing high-res borders...", curses.color_pair(3))
            if map_data.error:
                stdscr.addstr(2, 0, map_data.error, curses.color_pair(4))
            
            # keep the hud
            info = f"Loading... | Pos: {cam_x:.1f}, {cam_y:.1f} | Zoom: {zoom:.1f} | Arr: Move | +/-: Zoom | q: Quit"
            stdscr.addstr(0, 0, info, curses.color_pair(3))

        if map_data.data_loaded:
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

        simplify_tolerance_mx_my = 0.0 
        if zoom < 5.0:
            simplify_tolerance_mx_my = 0.05

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