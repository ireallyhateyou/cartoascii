import curses
import time
import threading
import routing
from drawing_utils import *
from braille import *
from map_data import *
from tiles import *

def main(stdscr):
    # setup curses
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(33) 
    curses.start_color()
    curses.use_default_colors()

    # Enable Mouse
    curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    print('\033[?1003h') # Xterm mouse tracking

    # colours
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1) 
    curses.init_pair(3, curses.COLOR_WHITE, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_YELLOW, -1)
    curses.init_pair(6, curses.COLOR_BLUE, -1)
    curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(8, curses.COLOR_MAGENTA, -1)
    curses.init_pair(9, curses.COLOR_WHITE, curses.COLOR_BLACK)

    # init data
    map_data = mapData()
    loader = threading.Thread(target=load_initial_data, args=(map_data,))
    loader.daemon = True
    loader.start()

    # camera state
    cam_x, cam_y = 0.0, 0.0
    zoom = 1.0
    running = True
    buffer = None
    
    # ui state
    instruction_page = 0
    show_instructions = False
    label_manager = None
    
    # routing profiles
    routing_profiles = ["driving-car", "foot-walking", "cycling-regular"]
    routing_names = ["Car (Driving)", "Walk (Foot)", "Bike (Cycling)"]
    
    # address fetching state
    last_cam_pos = (0, 0)
    last_move_time = time.time()
    
    # background address fetcher
    def address_worker():
        while running:
            time.sleep(1.0) # check every second
            
            # only fetch if user stopped moving for 1s
            now = time.time()
            if (cam_x, cam_y) == last_cam_pos:
                if now - last_move_time > 1.0:
                    # fetch
                    try:
                        # better precision unproject
                        r_lon, r_lat = tile_coords_to_lonlat(0, 0, 0, cam_x, cam_y, extent=1.0)
                        
                        addr = routing.reverse_geocode(r_lon, r_lat)
                        if addr:
                            with map_data.address_lock:
                                map_data.current_address = addr
                    except: pass
            else:
                pass
                
    addr_thread = threading.Thread(target=address_worker)
    addr_thread.daemon = True
    addr_thread.start()

    # render loop state
    last_tile_check = 0
    
    while running:
        loop_start = time.time()
        height, width = stdscr.getmaxyx()
        cx, cy = width // 2, height // 2
        
        # track movement for address fetcher
        if (cam_x, cam_y) != last_cam_pos:
            last_cam_pos = (cam_x, cam_y)
            last_move_time = time.time()
            with map_data.address_lock:
                map_data.current_address = "..." # clear old address while moving
        
        total_pages = 0
        label_manager = LabelManager(width, height)

        # resize buffer if needed
        if not buffer or buffer.cols != width or buffer.rows != height:
             buffer = BrailleBuffer(width * 2, height * 4)
        buffer.clear()
        
        # 1. loading screen
        if not map_data.data_loaded:
            stdscr.erase()
            msg = f"{map_data.status} {int(map_data.progress)}%"
            draw_progress_bar(stdscr, height//2, max(0, width//2 - 20), 40, map_data.progress, msg)
            stdscr.refresh()
            time.sleep(0.05)
            continue
            
        # initial zoom jump
        if zoom == 1.0 and map_data.countries_coords:
            zoom = 1.5

        stdscr.erase()
        aspect_ratio = 2.0
        
        # --- coordinate helpers ---
        def to_screen(mx, my):
            sx = ((mx - cam_x) * zoom * aspect_ratio) + cx
            sy = (-(my - cam_y) * zoom) + cy
            return int(sx), int(sy)
        
        def from_screen(sx, sy):
            mx = cam_x + (sx - cx) / (zoom * aspect_ratio)
            my = cam_y - (sy - cy) / zoom 
            return mx, my

        # viewport calc
        view_w = (width / aspect_ratio) / zoom
        view_h = height / zoom
        min_cam_x, max_cam_x = cam_x - view_w/2, cam_x + view_w/2
        min_cam_y, max_cam_y = cam_y - view_h/2, cam_y + view_h/2

        try:
            # --- draw global borders ---
            if zoom < 80.0:
                for item in map_data.projected_map_full:
                    bx1, by1, bx2, by2 = item['bbox']
                    if (bx2 < min_cam_x or bx1 > max_cam_x or
                        by2 < min_cam_y or by1 > max_cam_y): continue
                    draw_projected_polyline_braille(buffer, item['geom'], cam_x, cam_y, zoom, aspect_ratio, 
                        buffer.width, buffer.height, 1, z_index=1) 
                        
            # --- draw global roads ---
            if map_data.roads_data and 5.0 < zoom < 50.0:
                for road in map_data.roads_data:
                    bx1, by1, bx2, by2 = road['bbox']
                    if (bx2 < min_cam_x or bx1 > max_cam_x or
                        by2 < min_cam_y or by1 > max_cam_y): continue
                    
                    # Global Highways = High Priority (4)
                    draw_projected_polyline_braille(buffer, road['geom'], cam_x, cam_y, zoom, aspect_ratio, 
                        buffer.width, buffer.height, 5, z_index=4)

            # route post-routing
            if map_data.route_poly:
                # Route Line = Max Priority (8)
                draw_projected_polyline_braille(buffer, map_data.route_poly, cam_x, cam_y, zoom, aspect_ratio,
                                              buffer.width, buffer.height, 8, z_index=8) 

            # markers
            if map_data.start_marker:
                sx, sy = to_screen(*map_data.start_marker)
                if 0 <= sx < width and 0 <= sy < height:
                    try: stdscr.addstr(sy, sx, "O", curses.color_pair(1) | curses.A_BOLD)
                    except: pass

            if map_data.end_marker:
                sx, sy = to_screen(*map_data.end_marker)
                if 0 <= sx < width and 0 <= sy < height:
                    try: stdscr.addstr(sy, sx, "X", curses.color_pair(4) | curses.A_BOLD)
                    except: pass

            # --- tile management ---
            labels_to_draw = []
            
            if zoom > 20.0:
                tile_z = 14 if zoom > 1500 else 12
                if zoom < 100: tile_z = 8
                
                lat_min = mercator_unproject(min_cam_y)
                lat_max = mercator_unproject(max_cam_y)
                pad_x = (max_cam_x - min_cam_x) * 0.2
                
                visible_tiles = tiles_for_bbox(min_cam_x - pad_x, lat_min, max_cam_x + pad_x, lat_max, tile_z)
                missing_tiles = []
                
                for z, x, y in visible_tiles:
                    tile_features = map_data.tile_manager.get_tile(z, x, y)
                    
                    if tile_features is None:
                        if not map_data.tile_manager.is_fetching(z, x, y):
                            missing_tiles.append((z, x, y))
                            map_data.tile_manager.mark_fetching(z, x, y)
                    else:
                        for f in tile_features:
                            fb = f['bbox']
                            if (fb[2] < min_cam_x or fb[0] > max_cam_x or
                                fb[3] < min_cam_y or fb[1] > max_cam_y):
                                continue

                            if f['type'] == 'building' and zoom > 800:
                                coords = f['coords']
                                if coords[0] != coords[-1]:
                                    coords = coords + [coords[0]]
                                # Buildings = Z-index 2
                                draw_projected_polyline_braille(buffer, coords, cam_x, cam_y, zoom, aspect_ratio, 
                                    buffer.width, buffer.height, 2, z_index=2)
                                    
                            elif f['type'] == 'road':
                                # Roads use stored Z-index (2, 3 or 4)
                                c_idx = f.get('color_idx', 2)
                                z_idx = f.get('z_index', 2)
                                
                                draw_projected_polyline_braille(buffer, f['coords'], cam_x, cam_y, zoom, aspect_ratio, 
                                                              buffer.width, buffer.height, c_idx, z_index=z_idx)
                                
                                if zoom > 1500 and f.get('name'):
                                    labels_to_draw.append(f)
                                    
                            elif f['type'] == 'label':
                                labels_to_draw.append(f)

                # trigger fetch
                now = time.time()
                if missing_tiles and (now - last_tile_check > 0.2) and (now - loop_start < 0.1):
                    last_tile_check = now
                    map_data.fetch_executor.submit(fetch_tiles_background, map_data, missing_tiles)

        except Exception:
            pass 

        # --- render to screen ---
        frame_lines = buffer.frame()
        for y, line_data in enumerate(frame_lines):
            try:
                current_x = 0
                while current_x < len(line_data):
                    char, color_idx = line_data[current_x]
                    chunk = char
                    next_x = current_x + 1
                    # run length encoding
                    while next_x < len(line_data) and line_data[next_x][1] == color_idx:
                        chunk += line_data[next_x][0]
                        next_x += 1
                    
                    attr = curses.color_pair(color_idx) if color_idx else curses.color_pair(3)
                    stdscr.addstr(y, current_x, chunk, attr)
                    current_x = next_x
            except curses.error:
                pass

        # draw cities (Natural Earth)
        pop_cutoff = 0
        if zoom < 8.0: pop_cutoff = 1_000_000
        elif zoom < 30.0: pop_cutoff = 100_000
        elif zoom < 100.0: pop_cutoff = 10_000

        if map_data.countries_coords and zoom < 150.0:
            for city in map_data.countries_coords:
                if city['pop'] < pop_cutoff: break 
                sx, sy = to_screen(*city['coords'])
                if 0 <= sy < height and 0 <= sx < width:
                    marker = '·'
                    marker_attr = curses.color_pair(3) | curses.A_DIM
                    if city['pop'] >= 1_000_000:
                        marker = '◆' 
                        marker_attr = curses.color_pair(4) | curses.A_BOLD 
                    elif city['pop'] >= 100_000:
                        marker = '●'
                        marker_attr = curses.color_pair(4) 
                    try:
                        name_len = len(city['name'])
                        if label_manager.can_draw(sx, sy, name_len + 2):
                            stdscr.addstr(sy, sx, marker, marker_attr)
                            if sx + 2 + name_len < width:
                                stdscr.addstr(sy, sx+2, city['name'], curses.color_pair(3)|curses.A_DIM)
                            label_manager.register(sx, sy, name_len + 2)
                    except: pass

        # tile labels
        if zoom > 20:
            labels_to_draw.sort(key=lambda x: x.get('rank', 99))
            
            for f in labels_to_draw:
                name = f['name']
                if f['type'] == 'road' and zoom > 1500:
                     pts = [to_screen(*pt) for pt in f['coords']]
                     if len(pts) > 1:
                         mid = pts[len(pts)//2]
                         sx, sy = mid
                         if 0 <= sy < height and 0 <= sx < width - len(name):
                             if label_manager.can_draw(sx, sy, len(name)):
                                 try: 
                                     stdscr.addstr(sy, sx, name, curses.color_pair(5)|curses.A_DIM)
                                     label_manager.register(sx, sy, len(name))
                                 except: pass
                
                elif f['type'] == 'label':
                    sx, sy = to_screen(*f['coords'])
                    if 0 <= sy < height and 0 <= sx < width:
                        if label_manager.can_draw(sx, sy, len(name)):
                            try: 
                                stdscr.addstr(sy, sx, name, curses.color_pair(2)|curses.A_BOLD)
                                label_manager.register(sx, sy, len(name))
                            except: pass
        
        # --- instructions sidebar ---
        if map_data.route_instructions and show_instructions:
            sb_width = 35
            sb_x = width - sb_width
            
            for row in range(height-1):
                try: 
                    stdscr.addstr(row, sb_x, " " * sb_width, curses.color_pair(9))
                    stdscr.addch(row, sb_x, '|', curses.color_pair(3))
                except: pass
            
            total_items = len(map_data.route_instructions)
            max_lines = max(1, height - 6) 
            total_pages = (total_items + max_lines - 1) // max_lines
            
            if instruction_page >= total_pages: instruction_page = 0
            
            try:
                title = "INSTRUCTIONS"
                if total_pages > 1:
                    title = f"ROUTE ({instruction_page + 1}/{total_pages})"
                
                stdscr.addstr(1, sb_x + 2, title, curses.color_pair(6) | curses.A_BOLD)
                stdscr.addstr(2, sb_x + 2, "-" * (sb_width - 4), curses.color_pair(3))
            except: pass
            
            start_idx = instruction_page * max_lines
            end_idx = start_idx + max_lines
            current_slice = map_data.route_instructions[start_idx:end_idx]

            for i, step in enumerate(current_slice):
                text_space = sb_width - 5
                txt = step
                if len(txt) > text_space:
                    txt = txt[:text_space-2] + ".."
                
                try:
                    stdscr.addstr(3 + i, sb_x + 2, f"{start_idx + i + 1}. {txt}", curses.color_pair(3))
                except: pass
            
            try: stdscr.addstr(height - 2, sb_x + 2, "[ p ] page [ x ] hide", curses.color_pair(5)|curses.A_DIM)
            except: pass

        # --- hud & status bar ---
        status_text = f" [f] route  [j] jump  [c] clear  [q] quit "
        if map_data.route_poly:
            status_text += f"| mode: {map_data.active_mode.lower()}" 
        
        try:
            stdscr.attron(curses.color_pair(7))
            stdscr.addstr(height - 1, 0, status_text)
            
            fill_len = width - len(status_text) - 1
            if fill_len > 0:
                stdscr.addstr(height - 1, len(status_text), " " * fill_len)
            stdscr.attroff(curses.color_pair(7))
        except curses.error:
            pass
        
        # location display
        with map_data.address_lock:
            if map_data.current_address:
                addr_txt = f" {map_data.current_address} "
                if len(addr_txt) < width - len(status_text) - 2:
                    try:
                        # draw at bottom right
                        x_pos = width - len(addr_txt) - 1
                        stdscr.addstr(height - 1, x_pos, addr_txt, curses.color_pair(7))
                    except curses.error:
                        pass
        
        # crosshair
        try:
            stdscr.addstr(height//2, width//2, "+", curses.color_pair(4) | curses.A_BOLD)
        except: pass

        stdscr.refresh()

        # input handling
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
        
        elif k == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                if bstate & curses.BUTTON1_PRESSED:
                    w_mx, w_my = from_screen(mx, my)
                    cam_x, cam_y = w_mx, w_my
            except: pass

        elif k == ord('p') or k == ord('P'): 
            if total_pages > 1:
                instruction_page = (instruction_page + 1) % total_pages
                
        elif k == ord('x') or k == ord('X'):
            show_instructions = not show_instructions

        # jump to address
        elif k == ord('j'):
            stdscr.timeout(-1)
            target = text_input(stdscr, height//2 - 2, width//2 - 15, "Jump to: ")
            
            if target:
                stdscr.addstr(height//2, width//2 - 15, "Geocoding...", curses.color_pair(5))
                stdscr.refresh()
                
                coord = routing.geocode_address(target)
                if coord:
                    mx, my = mercator_project(coord[1], coord[0])
                    cam_x, cam_y = mx, my
                    if zoom < 500: zoom = 2000.0
                else:
                    stdscr.addstr(height//2, width//2 - 15, "Not found!", curses.color_pair(4))
                    stdscr.getch() 
            
            stdscr.timeout(33)

        #### improved routing menu
        elif k == ord('f'): 
            stdscr.timeout(-1) 
            
            start_addr = text_input(stdscr, height//2 - 2, width//2 - 15, "Start: ")
            if not start_addr: 
                stdscr.timeout(33)
                continue
                
            end_addr = text_input(stdscr, height//2, width//2 - 15, "End:   ")
            if not end_addr:
                stdscr.timeout(33)
                continue
            
            # popout menu
            sel_idx = draw_menu(stdscr, "Transport Mode", routing_names)
            
            if sel_idx is not None:
                selected_profile = routing_profiles[sel_idx]
                
                stdscr.addstr(height-2, 2, "Routing...", curses.color_pair(5))
                stdscr.refresh()
                
                s_coord = routing.geocode_address(start_addr)
                e_coord = routing.geocode_address(end_addr)
                
                if s_coord and e_coord:
                    route_pts, instructions = routing.get_route(
                        s_coord[0], s_coord[1], 
                        e_coord[0], e_coord[1],
                        selected_profile
                    )
                    
                    if route_pts:
                        map_data.start_marker = mercator_project(s_coord[1], s_coord[0])
                        map_data.end_marker = mercator_project(e_coord[1], e_coord[0])
                        
                        projected_route = []
                        for lon, lat in route_pts:
                            projected_route.append(mercator_project(lat, lon))
                        
                        map_data.route_poly = projected_route
                        map_data.route_instructions = instructions
                        map_data.active_mode = routing_names[sel_idx].upper()
                        
                        instruction_page = 0
                        show_instructions = True 
                        
                        # fit view
                        xs = [p[0] for p in projected_route]
                        ys = [p[1] for p in projected_route]
                        cam_x = (min(xs) + max(xs)) / 2
                        cam_y = (min(ys) + max(ys)) / 2
                        
                        route_w = max(0.01, max(xs) - min(xs))
                        route_h = max(0.01, max(ys) - min(ys))
                        zoom = min((width / aspect_ratio) / (route_w * 1.5), height / (route_h * 1.5))
                    else:
                        stdscr.addstr(height-2, 2, "No route found!", curses.color_pair(4))
                        stdscr.getch()
                else:
                    stdscr.addstr(height-2, 2, "Address failed!", curses.color_pair(4))
                    stdscr.getch()
                
            stdscr.timeout(33)
            
        elif k == ord('c'):
            map_data.route_poly = []
            map_data.route_instructions = []
            show_instructions = False
            instruction_page = 0
            map_data.start_marker = None
            map_data.end_marker = None
            map_data.active_mode = "VIEW"

    map_data.shutdown()
    curses.endwin()

if __name__ == "__main__":
    curses.wrapper(main)