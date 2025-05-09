import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from folium import Map, Marker, PolyLine
from math import radians, sin, cos, sqrt, atan2
import datetime

def haversine(lat1, lon1, lat2, lon2):
    """Returns distance between two lat/lon in meters."""
    R = 6371  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a)) * 1000

def create_distance_matrix(locations):
    """Builds a symmetric distance matrix (in meters)."""
    return [
        [int(haversine(flat, flon, tlat, tlon))
         for (tlat, tlon) in locations]
        for (flat, flon) in locations
    ]

def time_to_minutes(t):
    """Converts 'HH:MM', datetime.time, or pandas.Timestamp to minutes since midnight."""
    if isinstance(t, pd.Timestamp):
        t = t.strftime("%H:%M")
    if isinstance(t, datetime.time):
        t = t.strftime("%H:%M")
    s = str(t)
    if ":" in s:
        h, m = map(int, s.split(":"))
        return h * 60 + m
    return int(float(s))

def optimize_routes(df, vehicles_df, drivers_df, speed_factor, search_strategy):
    # 1) Extract depot and destinations
    depot_df = df[df["Warehouse Name"] == "CW8"]
    if depot_df.empty:
        raise ValueError("Depot 'CW8' not found in warehouse data.")
    depot = depot_df.iloc[0]
    
    dest_df = df[df["Warehouse Name"] != "CW8"].reset_index(drop=True)

    # 2) Build list of (lat, lon)
    locations = [(depot.latitude, depot.longitude)] + list(
        zip(dest_df.latitude, dest_df.longitude)
    )

    # 3) Prepare parameters
    demands       = [0] + dest_df.demand.fillna(0).astype(int).tolist()
    service_times = [0] + dest_df.service_time.fillna(0).astype(int).tolist()
    starts        = [0] + dest_df.start_time.fillna("00:00").apply(time_to_minutes).tolist()
    ends          = [24*60] + dest_df.end_time.fillna("23:59").apply(time_to_minutes).tolist()
    priorities    = [0] + dest_df.priority.fillna(0).astype(int).tolist()

    num_locations = len(locations)
    num_vehicles  = len(vehicles_df)

    # 4) Create OR-Tools manager & model
    manager = pywrapcp.RoutingIndexManager(num_locations, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    # 5) Distance callback
    distance_matrix = create_distance_matrix(locations)
    def dist_cb(from_idx, to_idx):
        fn = manager.IndexToNode(from_idx)
        tn = manager.IndexToNode(to_idx)
        return distance_matrix[fn][tn]
    dist_idx = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(dist_idx)

    # 6) Capacity dimension
    def demand_cb(idx):
        return demands[manager.IndexToNode(idx)]
    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    vehicle_caps = vehicles_df.capacity.fillna(0).astype(int).tolist()
    routing.AddDimensionWithVehicleCapacity(
        demand_idx, 0, vehicle_caps, True, "Capacity"
    )

    # 7) Time dimension
    def time_cb(from_idx, to_idx):
        fn = manager.IndexToNode(from_idx)
        tn = manager.IndexToNode(to_idx)
        dist_m = distance_matrix[fn][tn]
        drive_time = (dist_m / 1000) / speed_factor * 60  # in minutes
        return int(drive_time + service_times[fn])
    time_idx = routing.RegisterTransitCallback(time_cb)
    routing.AddDimension(
        time_idx,
        30,         # allow up to 30min waiting slack
        24*60,      # horizon = 24h
        False,
        "Time"
    )
    time_dim = routing.GetDimensionOrDie("Time")

    # 8) Apply time windows to all nodes
    for loc in range(num_locations):
        idx = manager.NodeToIndex(loc)
        time_dim.CumulVar(idx).SetRange(starts[loc], ends[loc])

    # 9) Driver working hours as time windows on vehicle start nodes
    for vid in range(num_vehicles):
        start = time_to_minutes(drivers_df.start_time.iloc[vid])
        end   = time_to_minutes(drivers_df.end_time.iloc[vid])
        start_idx = routing.Start(vid)
        time_dim.CumulVar(start_idx).SetRange(start, end)

    # 10) Priority-based soft penalty
    def priority_cb(from_idx, to_idx):
        fn = manager.IndexToNode(from_idx)
        tn = manager.IndexToNode(to_idx)
        # Penalize if lower-priority delivered before higher-priority
        return 500 if priorities[fn] < priorities[tn] else 0
    pri_idx = routing.RegisterTransitCallback(priority_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(pri_idx)

    # 11) Search parameters
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = getattr(
        routing_enums_pb2.FirstSolutionStrategy, search_strategy
    )
    params.time_limit.seconds = 30

    sol = routing.SolveWithParameters(params)
    if not sol:
        raise ValueError("No solution found.")

    # 12) Extract routes and build Folium map
    routes = []
    m = Map(location=(depot.latitude, depot.longitude), zoom_start=10)

    for vid in range(num_vehicles):
        idx = routing.Start(vid)
        coords = [(depot.latitude, depot.longitude)]
        names  = [f"{depot['Warehouse Name']} (Start)"]

        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node > 0:
                lat, lon = locations[node]
                arr = sol.Value(time_dim.CumulVar(idx))
                names.append(
                    f"{dest_df['Warehouse Name'].iloc[node-1]} "
                    f"(Arr {arr//60:02d}:{arr%60:02d})"
                )
                coords.append((lat, lon))
                Marker((lat, lon), popup=names[-1]).add_to(m)
            idx = sol.Value(routing.NextVar(idx))

        # Return to depot
        end_idx = routing.End(vid)
        arr = sol.Value(time_dim.CumulVar(end_idx))
        names.append(f"{depot['Warehouse Name']} (Return {arr//60:02d}:{arr%60:02d})")
        coords.append((depot.latitude, depot.longitude))

        PolyLine(coords, color=f"#{vid*16777215//num_vehicles:06x}", weight=4).add_to(m)
        routes.append(names)

    map_file = "route_map.html"
    m.save(map_file)
    return routes, map_file