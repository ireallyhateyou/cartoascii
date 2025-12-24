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
    curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE) # Debug/Header
    curses.init_pair(8, curses.COLOR_MAGENTA, -1)
    curses.init_pair(9, curses.COLOR_WHITE, curses.COLOR_BLACK) # Instruction bg

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
    show_instructions = False  # <--- Added toggle state
    label_manager = None
    
    # render loop state
    last_tile_check = 0
    fps = 0
    frame_count = 0
    last_fps_time = time.time()
    
    while running:
        loop_start = time.time()
        
        height, width = stdscr.getmaxyx()
        cx, cy = width // 2, height // 2
        
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
        
        # inverse for mouse
        def from_screen(sx, sy):
            mx = cam_x + (sx - cx) / (zoom * aspect_ratio)
            my = cam_y - (sy - cy) / zoom # remember y is flipped
            return mx, my

        # viewport calc
        view_w = (width / aspect_ratio) / zoom
        view_h = height / zoom
        min_cam_x, max_cam_x = cam_x - view_w/2, cam_x + view_w/2
        min_cam_y, max_cam_y = cam_y - view_h/2, cam_y + view_h/2

        try:
            # --- draw global borders ---
            for item in map_data.projected_map_full:
                bx1, by1, bx2, by2 = item['bbox']
                if (bx2 < min_cam_x or bx1 > max_cam_x or
                    by2 < min_cam_y or by1 > max_cam_y): continue
                draw_projected_polyline_braille(buffer, item['geom'], cam_x, cam_y, zoom, aspect_ratio, 
                    buffer.width, buffer.height, 1) 
                        
            # --- draw global roads ---
            if map_data.roads_data and 5.0 < zoom < 30.0:
                for road in map_data.roads_data:
                    bx1, by1, bx2, by2 = road['bbox']
                    if (bx2 < min_cam_x or bx1 > max_cam_x or
                        by2 < min_cam_y or by1 > max_cam_y): continue
                    
                    draw_projected_polyline_braille(buffer, road['geom'], cam_x, cam_y, zoom, aspect_ratio, 
                        buffer.width, buffer.height, 5)

            # route post-routing
            if map_data.route_poly:
                draw_projected_polyline_braille(buffer, map_data.route_poly, cam_x, cam_y, zoom, aspect_ratio,
                                              buffer.width, buffer.height, 8) 

            # start marker
            if map_data.start_marker:
                sx, sy = to_screen(*map_data.start_marker)
                if 0 <= sx < width and 0 <= sy < height:
                    try: stdscr.addstr(sy, sx, "O", curses.color_pair(1) | curses.A_BOLD)
                    except: pass

            # end marker
            if map_data.end_marker:
                sx, sy = to_screen(*map_data.end_marker)
                if 0 <= sx < width and 0 <= sy < height:
                    try: stdscr.addstr(sy, sx, "X", curses.color_pair(4) | curses.A_BOLD)
                    except: pass

            # --- tile management ---
            labels_to_draw = []
            
            if zoom > 20.0:
                tile_z = 14 if zoom > 1500 else 12
                # Lower Z for earlier levels
                if zoom < 100: tile_z = 8
                
                lat_min = mercator_unproject(min_cam_y)
                lat_max = mercator_unproject(max_cam_y)
                pad_x = (max_cam_x - min_cam_x) * 0.2
                
                visible_tiles = tiles_for_bbox(min_cam_x - pad_x, lat_min, max_cam_x + pad_x, lat_max, tile_z)
                missing_tiles = []
                
                # draw visible
                for z, x, y in visible_tiles:
                    tile_features = map_data.tile_manager.get_tile(z, x, y)
                    
                    if tile_features is None:
                        if not map_data.tile_manager.is_fetching(z, x, y):
                            missing_tiles.append((z, x, y))
                            map_data.tile_manager.mark_fetching(z, x, y)
                    else:
                        for f in tile_features:
                            # more culling
                            fb = f['bbox']
                            if (fb[2] < min_cam_x or fb[0] > max_cam_x or
                                fb[3] < min_cam_y or fb[1] > max_cam_y):
                                continue

                            if f['type'] == 'building' and zoom > 800:
                                fill_poly_braille(buffer, f['coords'], cam_x, cam_y, zoom, aspect_ratio, 
                                                buffer.width, buffer.height, 2)
                            elif f['type'] == 'road':
                                draw_projected_polyline_braille(buffer, f['coords'], cam_x, cam_y, zoom, aspect_ratio, 
                                                              buffer.width, buffer.height, 1)
                                if zoom > 1500 and f.get('name'):
                                    labels_to_draw.append(f)
                            elif f['type'] == 'label':
                                labels_to_draw.append(f)

                # trigger fetch (debounced)
                now = time.time()
                # only fetch if we aren't lagging (frame time < 100ms)
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

        if map_data.countries_coords:
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
                        # Collision check for Cities
                        name_len = len(city['name'])
                        if label_manager.can_draw(sx, sy, name_len + 2):
                            stdscr.addstr(sy, sx, marker, marker_attr)
                            if sx + 2 + name_len < width:
                                stdscr.addstr(sy, sx+2, city['name'], curses.color_pair(3)|curses.A_DIM)
                            label_manager.register(sx, sy, name_len + 2)
                    except: pass

        # tile labels + colliusion
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
            
            # calculate paging
            total_items = len(map_data.route_instructions)
            max_lines = max(1, height - 6) 
            total_pages = (total_items + max_lines - 1) // max_lines
            
            # safety reset if data changed significantly
            if instruction_page >= total_pages: instruction_page = 0
            
            # header
            try:
                title = "INSTRUCTIONS"
                if total_pages > 1:
                    title = f"ROUTE ({instruction_page + 1}/{total_pages})"
                
                stdscr.addstr(1, sb_x + 2, title, curses.color_pair(6) | curses.A_BOLD)
                stdscr.addstr(2, sb_x + 2, "-" * (sb_width - 4), curses.color_pair(3))
            except: pass
            
            # text steps (sliced)
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
            
            # footer hint
            try: stdscr.addstr(height - 2, sb_x + 2, "[ p ] page [ x ] hide", curses.color_pair(5)|curses.A_DIM)
            except: pass

        # hud
        frame_count += 1
        if time.time() - last_fps_time > 1.0:
            fps = frame_count
            frame_count = 0
            last_fps_time = time.time()

        hud = f"POS: {cam_x:.4f}, {cam_y:.4f} | ZOOM: {zoom:.1f}x | FPS: {fps} | [f] Route | [j] Jump | [c] Clear"
        stdscr.addstr(0, 0, hud, curses.color_pair(7))
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
        
        # mouse handling
        elif k == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                if bstate & curses.BUTTON1_PRESSED:
                    w_mx, w_my = from_screen(mx, my)
                    cam_x, cam_y = w_mx, w_my
            except: pass

        # paging controls with cycling
        elif k == ord('p') or k == ord('P'): 
            if total_pages > 1:
                # loop back
                instruction_page = (instruction_page + 1) % total_pages
                
        elif k == ord('x') or k == ord('X'):
            show_instructions = False
        
        # jump to address
        elif k == ord('j'):
            stdscr.timeout(-1)
            target = text_input(stdscr, height-4, 2, "Jump to: ")
            
            if target:
                stdscr.addstr(height-2, 2, "Geocoding...", curses.color_pair(5))
                stdscr.refresh()
                
                coord = routing.geocode_address(target)
                if coord:
                    mx, my = mercator_project(coord[1], coord[0])
                    cam_x, cam_y = mx, my
                    if zoom < 500: zoom = 2000.0
                    stdscr.addstr(height-2, 2, f"Moved to {target}", curses.color_pair(2))
                else:
                    stdscr.addstr(height-2, 2, "Address not found!", curses.color_pair(4))
                stdscr.getch() 
            
            stdscr.timeout(33)

        #### routing menu
        elif k == ord('f'): 
            stdscr.timeout(-1) 
            
            start_addr = text_input(stdscr, height-4, 2, "Start Addr: ")
            end_addr = text_input(stdscr, height-3, 2, "End Addr:   ")
            
            stdscr.addstr(height-2, 2, "Geocoding...", curses.color_pair(5))
            stdscr.refresh()
            
            s_coord = routing.geocode_address(start_addr)
            e_coord = routing.geocode_address(end_addr)
            
            if s_coord and e_coord:
                stdscr.addstr(height-2, 2, "Routing...  ", curses.color_pair(5))
                stdscr.refresh()
                
                route_pts, instructions = routing.get_route(s_coord[0], s_coord[1], e_coord[0], e_coord[1])
                
                if route_pts:
                    map_data.start_marker = mercator_project(s_coord[1], s_coord[0])
                    map_data.end_marker = mercator_project(e_coord[1], e_coord[0])
                    
                    projected_route = []
                    for lon, lat in route_pts:
                        projected_route.append(mercator_project(lat, lon))
                    
                    map_data.route_poly = projected_route
                    map_data.route_instructions = instructions
                    
                    # reset UI for new route
                    instruction_page = 0
                    show_instructions = True 
                    
                    # autozoom
                    xs = [p[0] for p in projected_route]
                    ys = [p[1] for p in projected_route]
                    
                    min_x, max_x = min(xs), max(xs)
                    min_y, max_y = min(ys), max(ys)
                    cam_x = (min_x + max_x) / 2
                    cam_y = (min_y + max_y) / 2
                    route_w = max_x - min_x
                    route_h = max_y - min_y
                    if route_w == 0: route_w = 0.01
                    if route_h == 0: route_h = 0.01

                    zoom_w = (width / aspect_ratio) / (route_w * 1.5)
                    zoom_h = height / (route_h * 1.5)
                    zoom = min(zoom_w, zoom_h)

                else:
                    stdscr.addstr(height-2, 2, "Route Failed!", curses.color_pair(4))
                    stdscr.getch()
            else:
                stdscr.addstr(height-2, 2, "Address not found!", curses.color_pair(4))
                stdscr.getch()
                
            stdscr.timeout(33)
            
        elif k == ord('c'):
            # complete clear
            map_data.route_poly = []
            map_data.route_instructions = []
            show_instructions = False
            instruction_page = 0
            map_data.start_marker = None
            map_data.end_marker = None

    map_data.shutdown()
    curses.endwin()

if __name__ == "__main__":
    curses.wrapper(main)