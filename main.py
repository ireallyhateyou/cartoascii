import curses
import math
import load_data
import time

mercator_const = 85.051129

def mercator_project(lat, lon):
    # clip
    if lat > mercator_const: lat = mercator_const
    if lat < -mercator_const: lat = -mercator_const

    x = lon
    
    # mercator formula
    lat_rad = math.radians(lat)
    y = math.log(math.tan((math.pi / 4) + (lat_rad / 2)))
    y = math.degrees(y)
    
    return x, y

def mercator_unproject(y_proj):
    # reverse of : y = math.log(math.tan((math.pi / 4) + (lat_rad / 2)))
    y_proj_norm = math.radians(y_proj)
    lat_rad = 2 * (math.atan(math.exp(y_proj_norm)) - (math.pi / 4))
    return math.degrees(lat_rad)

def draw_line(stdscr, x0, y0, x1, y1, char):
    # Bresenham's line algorithm
    # https://www.cs.drexel.edu/~popyack/Courses/CSP/Fa18/notes/08.3_MoreGraphics/Bresenham.html?CurrentSlide=2
    height, width = stdscr.getmaxyx()

    # dont go off boundaries
    if (x0 < 0 and x1 < 0) or (x0 >= width and x1 >= width): return
    if (y0 < 0 and y1 < 0) or (y0 >= height and y1 >= height): return

    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    while True:
        if 0 <= x0 < width and 0 <= y0 < height:
            try:
                stdscr.addch(int(y0), int(x0), char)
            except curses.error:
                pass
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy

def main(stdscr):
    # set cursors up
    curses.curs_set(0) 
    stdscr.nodelay(True) 
    stdscr.timeout(100)
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK) 
    curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLACK) 
    curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    
    # load datas
    stdscr.addstr(0, 0, "Loading dataset... (this requires internet!!)")
    stdscr.refresh()
    
    try:
        countries = load_data.download_world_borders()
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

    running = True
    while running:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        cx, cy = width // 2, height // 2

        # draw hud and map
        info = f"Pos: {cam_x:.1f}, {cam_y:.1f} | Zoom: {zoom:.1f} | Arr: Move | +/-: Zoom | q: Quit"
        stdscr.addstr(0, 0, info, curses.color_pair(3))
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
                    draw_line(stdscr, p1[0], p1[1], p2[0], p2[1], ord('#') | curses.color_pair(1))
                
                # close loop
                if screen_points:
                    p1 = screen_points[-1]
                    p2 = screen_points[0]
                    draw_line(stdscr, p1[0], p1[1], p2[0], p2[1], ord('#') | curses.color_pair(1))

        # handle input
        try:
            key = stdscr.getch()
        except:
            key = -1

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