from load_data import download_world_borders

if __name__ == "__main__":
    borders = download_world_borders()
    print(borders)