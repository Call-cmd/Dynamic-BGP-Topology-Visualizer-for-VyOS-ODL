import asyncio
import json
import ipaddress
from typing import Dict, Any, Set, List
import aiohttp
import networkx as nx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# --- CONTROLLER CONFIG ---
CONTROLLER_URL = "http://192.168.56.102:8181/rests/data/bgp-rib:bgp-rib/rib=bgp-to-r1?content=nonconfig"
AUTH = ("admin", "admin")
POLL_INTERVAL = 5.0

# --- FASTAPI APP ---
app = FastAPI(title="ODL Dynamic BGP Topology WS")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_latest_snapshot: Dict[str, Any] | None = None


class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active.discard(websocket)

    async def broadcast(self, message: str):
        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


# -----------------------------
# STEP 1: FETCH BGP DATA
# -----------------------------
async def fetch_bgp_data() -> Dict[str, Any]:
    async with aiohttp.ClientSession(auth=aiohttp.BasicAuth(*AUTH)) as session:
        try:
            async with session.get(CONTROLLER_URL, headers={"Accept": "application/json"}) as resp:
                if resp.status != 200:
                    print(f"[!] Failed to fetch BGP data: HTTP {resp.status}")
                    return {}
                return await resp.json()
        except aiohttp.ClientConnectorError as e:
            print(f"[!] Connection error: {e}")
            return {}


# -----------------------------
# STEP 2: PARSE BGP INTO ROUTES
# -----------------------------
def extract_routes(bgp_data: dict) -> List[Dict]:
    routes = []
    try:
        rib = bgp_data.get("bgp-rib:rib", [])
        if not rib:
            return []
        
        loc_rib_tables = rib[0].get("loc-rib", {}).get("tables", [])
        for table in loc_rib_tables:
            ipv4_routes = table.get("bgp-inet:ipv4-routes", {}).get("ipv4-route", [])
            for route in ipv4_routes:
                routes.append({"prefix": route.get("prefix", "")})

        for peer in rib[0].get("peer", []):
            rib_in = peer.get("effective-rib-in", {})
            for table in rib_in.get("tables", []):
                ipv4_routes = table.get("bgp-inet:ipv4-routes", {}).get("ipv4-route", [])
                for route in ipv4_routes:
                    routes.append({"prefix": route.get("prefix", "")})
        
        unique_routes = [dict(t) for t in {tuple(d.items()) for d in routes}]
        return unique_routes
        
    except Exception as e:
        print(f"[!] Error parsing routes: {e}")
        return []

# -----------------------------
# STEP 3: BUILD DYNAMIC TOPOLOGY (MODIFIED)
# -----------------------------
# MODIFIED: Function now accepts the full bgp_data object
def build_dynamic_topology(routes: List[Dict], bgp_data: Dict[str, Any]) -> Dict[str, Any]:
    G = nx.Graph()
    local_ip_prefix = None

    # --- Part 1a: Identify the local router's IP and format it as a prefix ---
    try:
        peer_id_str = bgp_data["bgp-rib:rib"][0]["peer"][0]["peer-id"]
        # Expected format: "bgp://192.168.7.1"
        local_ip = peer_id_str.split('//')[-1]
        # Create a consistent prefix format by adding /32
        local_ip_prefix = f"{local_ip}/32" 
        print(f"[+] Identified local router from peer-id: {local_ip}")
    except (KeyError, IndexError):
        print("[!] Could not find or parse local peer-id in BGP data.")

    # --- Part 1b: Consolidate all node prefixes (remote and local) ---
    node_prefixes = {
        r['prefix'] for r in routes 
        if r.get('prefix', '').startswith('192.168.7.') and r.get('prefix', '').endswith('/32')
    }
    
    # Add the formatted local router prefix to the set
    if local_ip_prefix:
        node_prefixes.add(local_ip_prefix)
    
    # --- Part 1c: Process all identified nodes in a single, unified loop ---
    for prefix in node_prefixes:
        try:
            ip_str = prefix.split('/')[0]
            router_num = ip_str.split('.')[-1]
            node_id = f"R{router_num}"
            G.add_node(node_id, label=ip_str)
        except (ValueError, IndexError):
            print(f"[!] Could not parse node from prefix: {prefix}")
            continue

# --- Part 2a: Recursively search the entire JSON for link prefixes ---
    def find_prefixes_recursively(data, pattern, found_set):
        """A helper function to find all strings starting with a pattern in a nested structure."""
        if isinstance(data, dict):
            for value in data.values():
                find_prefixes_recursively(value, pattern, found_set)
        elif isinstance(data, list):
            for item in data:
                find_prefixes_recursively(item, pattern, found_set)
        elif isinstance(data, str) and data.startswith(pattern):
            found_set.add(data)

    # Using a set automatically handles deduplication
    link_prefixes = set()
    find_prefixes_recursively(bgp_data, "10.85.", link_prefixes)
    
    # --- Part 2b: Process the found link prefixes ---
    for link_prefix in link_prefixes:
        try:
            network_address = link_prefix.split('/')[0]
            parts = network_address.split('.')
            third_octet = parts[2]
            
            if len(third_octet) == 2:
                x, y = third_octet[0], third_octet[1]
                node1_id = f"R{x}"
                node2_id = f"R{y}"
                
                if G.has_node(node1_id) and G.has_node(node2_id):
                    # Always format the label as X.X.X.X/30 for consistency
                    standardized_label = f"{network_address}/30"
                    G.add_edge(node1_id, node2_id, label=standardized_label)
        except (ValueError, IndexError):
            print(f"[!] Could not parse edge from prefix: {link_prefix}")
            continue
                
    # --- Part 3: Convert NetworkX graph to JSON for the frontend ---
    nodes = [{"id": n, "label": G.nodes[n].get("label", n)} for n in G.nodes()]
    edges = [{"from": u, "to": v, "label": d.get("label", "")} for u, v, d in G.edges(data=True)]
    
    return {"nodes": nodes, "edges": edges}

# -----------------------------
# STEP 4: FETCH + BUILD TOPOLOGY (MODIFIED)
# -----------------------------
async def fetch_topology() -> Dict[str, Any]:
    bgp_data = await fetch_bgp_data()
    if not bgp_data:
        return {"nodes": [], "edges": []}

    routes = extract_routes(bgp_data)
    if not routes:
        print("[-] No routes extracted from BGP data.")
        # MODIFIED: Still pass bgp_data to build the local node even if no routes are learned
        return build_dynamic_topology([], bgp_data)
        
    # MODIFIED: Pass the full bgp_data object to the builder function
    graph = build_dynamic_topology(routes, bgp_data)

    print(f"[+] Generated topology: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
    return graph


# -----------------------------
# STEP 5: BACKGROUND POLLING
# -----------------------------
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(poll_loop())


async def poll_loop():
    global _latest_snapshot
    while True:
        graph = await fetch_topology()
        if graph and graph != _latest_snapshot:
            _latest_snapshot = graph
            await manager.broadcast(json.dumps({"type": "topology", "data": graph}))
        await asyncio.sleep(POLL_INTERVAL)


# -----------------------------
# STEP 6: API ENDPOINTS
# -----------------------------
@app.get("/api/topology")
async def get_topology():
    if _latest_snapshot is None:
        initial_graph = await fetch_topology()
        if not initial_graph or not initial_graph.get("nodes"):
             return JSONResponse(status_code=204, content={"detail": "No topology data available yet."})
        return initial_graph
    return _latest_snapshot


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        if _latest_snapshot is not None:
            await websocket.send_text(json.dumps({"type": "topology", "data": _latest_snapshot}))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)