# Dynamic-BGP-Topology-Visualizer-for-VyOS-ODL
A BGP topology visualizer. This project's FastAPI backend polls an ODL controller for BGP RIB data, builds a topology with NetworkX, and serves it to a web UI via WebSockets. The reference network uses VyOS routers in a GNS3 full-mesh lab environment.

## Key Features

    Real-Time Visualization: Uses WebSockets to push topology updates to the frontend as they are detected.

    Dynamic Discovery: Infers network topology directly from BGP routing information.

    Decoupled Architecture: A Python/FastAPI backend handles all the logic, serving a clean static frontend.

    SDN Integration: Polls an OpenDaylight (ODL) controller's RESTCONF API as the central source of BGP data.

    Reproducible Lab: Includes full configurations for a 4-router VyOS full-mesh lab in GNS3.

## Technology Stack

    Backend: Python, FastAPI, Uvicorn, NetworkX, aiohttp

    Frontend: HTML, CSS, JavaScript (Vis.js for rendering)

    Network: VyOS, GNS3, OpenDaylight (ODL)

    Protocols: BGP, OSPF, RESTCONF

## How It Works

The system operates on a polling mechanism where the backend acts as the central orchestrator, fetching raw data and serving a processed graph to any connected client.

    GNS3/VyOS Lab: A 4-node full-mesh of VyOS routers establish iBGP sessions and exchange routes. One router is peered with OpenDaylight.

    OpenDaylight: Acts as a BGP route-collector, receiving all prefixes from the VyOS lab and exposing them via its RESTCONF API.

    FastAPI Backend: Periodically polls the ODL controller's API to fetch the latest BGP RIB data. It then uses a custom parser to build a graph of nodes (192.168.7.X/32) and edges (10.85.XY.0/30).

    WebSocket Broadcast: If the newly generated topology differs from the last known state, the backend broadcasts the updated graph data to all connected frontend clients.

    Frontend: A simple web page listens for WebSocket messages and uses the Vis.js library to render the network graph.

## Setup and Installation

Follow these steps to get the project running.

### 1. GNS3 Lab & OpenDaylight

    GNS3: Set up a 4-node full-mesh topology in GNS3 using the VyOS router appliance.

    VyOS: Apply the configurations located in the gns3_lab/vyos_configs/ directory to each corresponding router.

    OpenDaylight: Ensure your ODL instance is running and accessible from the machine that will host the backend. vyos1 must be configured to peer with ODL.

### 2. Backend Server

The backend requires Python 3.8+.
Bash

# Navigate to the backend directory
cd backend/

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`

# Install the required dependencies
pip install -r requirements.txt

# Run the FastAPI server
uvicorn main:app --reload

The backend will now be running on http://127.0.0.1:8000.

### 3. Frontend

The frontend is a simple static site. No build process is needed.

    Navigate to the frontend/ directory.

    Open the index.html file in a modern web browser.

The page will automatically connect to the backend's WebSocket and display the topology as soon as data is available.

## Configuration

The primary configuration is located at the top of the backend/main.py file.
Python

# --- CONTROLLER CONFIG ---
CONTROLLER_URL = "http://192.168.56.102:8181/rests/data/bgp-rib:bgp-rib/rib=bgp-to-r1?content=nonconfig"
AUTH = ("admin", "admin")
POLL_INTERVAL = 5.0 # Seconds

    CONTROLLER_URL: The RESTCONF API endpoint of your ODL instance. The rib=bgp-to-r1 part corresponds to the RIB ID configured in ODL, which may need to be adjusted.

    AUTH: The username and password for your ODL controller.

    POLL_INTERVAL: The frequency in seconds at which the backend polls ODL for updates.
