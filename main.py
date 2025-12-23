import curses
import time
import threading
from drawing_utils import *
from map_data import mapData, load_initial_data, fetch_local_details

def draw_progress_bar(stdscr, y, x, width, percent, message):
    # helper for loading screen
    bar_width = width - 4
    filled = int(bar_width * (percent / 100.0))
    bar = "[" + "#" * filled + "." * (bar_width - filled) + "]"
    
    stdscr.addstr(y, x, message, curses.color_pair(3))
    stdscr.addstr(y + 1, x, bar, curses.color_pair(6))

def main(stdscr):
    # set cursors up
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(33) 
    curses.start_color()

    ## colours
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK) 
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(6, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(8, curses.COLOR_MAGENTA, curses.COLOR_BLACK)
    curses.init_pair(9, curses.COLOR_WHITE, curses.COLOR_BLACK)

    # load datas
    map_data = mapData()
    loader = threading.Thread(target=load_initial_data, args=(map_data,))
    loader.daemon = True
    loader.start()

    # camera and aspect ratio
    cam_x, cam_y = 0.0, 0.0
    zoom = 1.0
    running = True
    
    # threads & cache
    fetch_thread = None
    last_fetch = 0
    
    while running:
        height, width = stdscr.getmaxyx()
        cx, cy = width // 2, height // 2
        
        # loading screen
        if not map_data.data_loaded:
            stdscr.erase()
            msg = f"{map_data.status} {int(map_data.progress)}%"
            draw_progress_bar(stdscr, height//2, max(0, width//2 - 20), 40, map_data.progress, msg)
            stdscr.refresh()
            ####time.sleep(0.1)
            continue
            
        # initial zoom jump
        if zoom == 1.0 and map_data.countries_coords:
            zoom = 1.5

        stdscr.erase()
        aspect_ratio = 2.0
        
        # helper to screen conversion
        def to_screen(mx, my):
            sx = ((mx - cam_x) * zoom * aspect_ratio) + cx
            sy = (-(my - cam_y) * zoom) + cy
            return int(sx), int(sy)

        # world borders
        simplify = 0.05 / zoom
        view_w = (width / aspect_ratio) / zoom
        view_h = height / zoom
        min_cam_x, max_cam_x = cam_x - view_w/2, cam_x + view_w/2
        min_cam_y, max_cam_y = cam_y - view_h/2, cam_y + view_h/2

        # culling for world borders
        for item in map_data.projected_map_full:
            bx1, by1, bx2, by2 = item['bbox']
            
            if (bx2 < min_cam_x or bx1 > max_cam_x or
                by2 < min_cam_y or by1 > max_cam_y):
                continue

            draw_country_poly(stdscr, item['geom'], cam_x, cam_y, zoom, aspect_ratio, width, height, curses.color_pair(1), simplify)
        
        # naturalearth roads
        if map_data.roads_data and zoom > 5.0 and zoom < 1000.0:
            for road in map_data.roads_data:
                bx1, by1, bx2, by2 = road['bbox']
                # culling
                if (bx2 < cam_x - width/zoom or bx1 > cam_x + width/zoom or
                    by2 < cam_y - height/zoom or by1 > cam_y + height/zoom): continue
                
                # use drawing_utils implementation
                draw_projected_polyline(stdscr, road['geom'], cam_x, cam_y, zoom, aspect_ratio, width, height, ord('.') | curses.color_pair(5))

        # fetch features 
        with map_data.lock:
            local_feats = list(map_data.local_features)

        # buildings
        if zoom > 800:
            for f in local_feats:
                if f['type'] == 'building':
                    # outline
                    draw_projected_polyline(stdscr, f['coords'] + [f['coords'][0]], cam_x, cam_y, zoom, aspect_ratio, width, height, curses.ACS_CKBOARD | curses.color_pair(9))

        # local roads
        if zoom > 300:
            for f in local_feats:
                if f['type'] == 'road':
                    pts = [to_screen(*pt) for pt in f['coords']]
                    
                    is_major = f['class'] in ['motorway', 'trunk', 'primary']
                    char = ord('#') if is_major else ord('.')
                    attr = curses.color_pair(8)|curses.A_BOLD if is_major else curses.color_pair(5)
                    
                    # draw line
                    draw_projected_polyline(stdscr, f['coords'], cam_x, cam_y, zoom, aspect_ratio, width, height, char | attr)
                    
                    # name
                    if zoom > 1500 and f.get('name') and len(pts) > 1:
                        mid = pts[len(pts)//2]
                        if 0 <= mid[1] < height and 0 <= mid[0] < width - len(f['name']):
                            try: stdscr.addstr(mid[1], mid[0], f['name'], curses.color_pair(5)|curses.A_DIM)
                            except: pass

        # draw cities, settlemnts, and the like
        pop_cutoff = 0
        if zoom < 8.0: pop_cutoff = 1_000_000
        elif zoom < 30.0: pop_cutoff = 100_000
        elif zoom < 100.0: pop_cutoff = 10_000
        else: pop_cutoff = 0 

        if map_data.countries_coords:
            for city in map_data.countries_coords:
                if city['pop'] < pop_cutoff: break 
                
                sx, sy = to_screen(*city['coords'])
                
                # bounds checko
                if 0 <= sy < height and 0 <= sx < width:
                    marker = '·'
                    marker_attr = curses.color_pair(3) | curses.A_DIM
                    label_attr = curses.color_pair(3) | curses.A_DIM
                    
                    # city marker based on population.
                    if city['pop'] >= 1_000_000:
                        marker = '◆' 
                        marker_attr = curses.color_pair(4) | curses.A_BOLD 
                        label_attr = curses.color_pair(3) | curses.A_BOLD
                    elif city['pop'] >= 100_000:
                        marker = '●'
                        marker_attr = curses.color_pair(4) 
                        label_attr = curses.color_pair(3) | curses.A_BOLD
                    elif city['pop'] >= 10_000:
                        marker = 'o'
                        marker_attr = curses.color_pair(3) | curses.A_BOLD 
                        label_attr = curses.color_pair(3)

                    try:
                        stdscr.addstr(sy, sx, marker, marker_attr)
                        # cull label if offscreen
                        if sx + 2 + len(city['name']) < width:
                            stdscr.addstr(sy, sx+2, city['name'], label_attr)
                    except: pass

        # local labels
        if zoom > 1000:
            for f in local_feats:
                if f['type'] == 'label':
                    sx, sy = to_screen(*f['coords'])
                    if 0 <= sy < height and 0 <= sx < width:
                        try: stdscr.addstr(sy, sx, f['name'], curses.color_pair(2))
                        except: pass

        # draw hud
        hud = f"POS: {cam_x:.2f}, {cam_y:.2f} | ZOOM: {zoom:.1f}x"
        stdscr.addstr(0, 0, hud, curses.color_pair(7))
        stdscr.refresh()

        # handle input and controls
        try: k = stdscr.getch()
        except: k = -1
        
        spd = 10 / zoom
        if k == ord('q'): running = False
        elif k == curses.KEY_RIGHT: cam_x += spd
        elif k == curses.KEY_LEFT: cam_x -= spd
        elif k == curses.KEY_UP: cam_y += spd
        elif k == curses.KEY_DOWN: cam_y -= spd
        elif k in [ord('='), 43]: zoom *= 1.2
        elif k in [ord('-'), 95]: zoom /= 1.2

        # fetch tiles
        if zoom > 300:
            now = time.time()
            if (fetch_thread is None or not fetch_thread.is_alive()) and (now - last_fetch > 0.5):
                last_fetch = now
                lat_min = mercator_unproject(cam_y - (height/2)/zoom)
                lat_max = mercator_unproject(cam_y + (height/2)/zoom)
                w_deg = (width/2)/(zoom*aspect_ratio)
                
                # thuglife error handling inside the thread function usually
                fetch_thread = threading.Thread(target=fetch_local_details, 
                                              args=(map_data, (cam_x-w_deg, lat_min, cam_x+w_deg, lat_max), zoom))
                fetch_thread.daemon = True
                fetch_thread.start()

    curses.endwin()

if __name__ == "__main__":
    curses.wrapper(main)