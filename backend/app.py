from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import time
import random
import threading
import copy

app = Flask(__name__, static_folder='.')
CORS(app)

# Default configuration
DEFAULT_CONFIG = {
    "packetTime": 1000,
    "ackTime": 500,
    "sendWindow": 4,
    "recvWindow": 8,
    "protocol": "reno",
    "packetLoss": 5,
    "ackLoss": 2,
    "timeout": 3000,
    "bandwidth": 10
}

VALID_PROTOCOLS = ["classic", "tahoe", "reno", "cubic", "bbr"]

current_config = copy.deepcopy(DEFAULT_CONFIG)

# Simulation state
simulation_running = False
simulation_stats = {
    "sent": 0,
    "received": 0,
    "ackSent": 0,
    "ackReceived": 0,
    "lost": 0,
    "ackLost": 0,
    "windowHistory": [],
    "ssthreshHistory": []
}

simulation_lock = threading.Lock()


@app.route('/')
def index():
    return send_from_directory('.', 'tcp_simulator.html')


@app.route('/parameters', methods=['GET'])
def get_parameters():
    """Return current simulation parameters"""
    return jsonify({
        "success": True,
        "data": current_config
    })


@app.route('/set', methods=['POST'])
def set_parameters():
    """Set simulation parameters"""
    global current_config

    data = request.get_json() or {}

    # Validate protocol
    if "protocol" in data and data["protocol"] not in VALID_PROTOCOLS:
        return jsonify({
            "success": False,
            "error": "Invalid protocol",
            "validValues": VALID_PROTOCOLS
        }), 400

    # Validate numeric parameters
    validations = [
        ("packetTime", 100, 10000),
        ("ackTime", 50, 5000),
        ("sendWindow", 1, 64),
        ("recvWindow", 1, 64),
        ("packetLoss", 0, 50),
        ("ackLoss", 0, 50),
        ("timeout", 500, 20000),
        ("bandwidth", 1, 100)
    ]

    for param, min_val, max_val in validations:
        if param in data:
            val = data[param]
            if not isinstance(val, (int, float)) or val < min_val or val > max_val:
                return jsonify({
                    "success": False,
                    "error": f"Invalid value for {param}. Must be between {min_val} and {max_val}"
                }), 400

    # Update configuration
    for key in current_config:
        if key in data:
            current_config[key] = data[key]

    return jsonify({
        "success": True,
        "data": current_config
    })


@app.route('/play', methods=['POST'])
def play_simulation():
    """Run simulation for specified duration and return statistics"""
    global simulation_stats, simulation_running

    data = request.get_json() or {}
    duration = data.get('duration', 30)

    if not isinstance(duration, (int, float)) or duration < 1 or duration > 300:
        return jsonify({
            "success": False,
            "error": "Duration must be between 1 and 300 seconds"
        }), 400

    with simulation_lock:
        # Reset stats
        simulation_stats = {
            "sent": 0,
            "received": 0,
            "ackSent": 0,
            "ackReceived": 0,
            "lost": 0,
            "ackLost": 0,
            "windowHistory": [],
            "ssthreshHistory": []
        }
        simulation_running = True

    # Run simulation logic
    run_backend_simulation(duration)

    with simulation_lock:
        simulation_running = False

        # Calculate statistics
        total_packets = simulation_stats["sent"]
        total_acks = simulation_stats["ackSent"]

        result = {
            "success": True,
            "duration": duration,
            "statistics": {
                "packetsSent": simulation_stats["sent"],
                "packetsReceived": simulation_stats["received"],
                "acksSent": simulation_stats["ackSent"],
                "acksReceived": simulation_stats["ackReceived"],
                "packetLossPercent": round((simulation_stats["lost"] / total_packets * 100), 2) if total_packets > 0 else 0.0,
                "ackLossPercent": round((simulation_stats["ackLost"] / total_acks * 100), 2) if total_acks > 0 else 0.0,
                "windowHistory": simulation_stats["windowHistory"],
                "ssthreshHistory": simulation_stats["ssthreshHistory"]
            }
        }

    return jsonify(result)


def run_backend_simulation(duration):
    """Simulate TCP transmission in backend"""
    global simulation_stats

    cfg = current_config
    protocol = cfg["protocol"]

    # TCP state
    cwnd = cfg["sendWindow"]
    ssthresh = max(cfg["sendWindow"] * 4, 64)
    phase = "slow-start"
    next_seq = 0
    sent_packets = set()
    acked_packets = set()
    dup_ack_count = 0
    last_ack = -1

    window_history = [{"timestamp": int(time.time() * 1000), "value": round(cwnd, 2)}]
    ssthresh_history = [{"timestamp": int(time.time() * 1000), "value": round(ssthresh, 2)}]

    start_time = time.time()
    packet_interval = 1.0 / cfg["bandwidth"]
    elapsed = 0

    while elapsed < duration:
        elapsed = time.time() - start_time

        # Simulate packet sending
        in_flight = len(sent_packets) - len(acked_packets)
        if in_flight < cwnd:
            seq_num = next_seq
            next_seq += 1
            sent_packets.add(seq_num)

            with simulation_lock:
                simulation_stats["sent"] += 1

            # Check packet loss
            if random.random() * 100 < cfg["packetLoss"]:
                with simulation_lock:
                    simulation_stats["lost"] += 1

                # Handle loss based on protocol
                old_ssthresh = ssthresh
                if protocol == "tahoe":
                    ssthresh = max(cwnd / 2, 2)
                    cwnd = 1
                    phase = "slow-start"
                elif protocol == "reno":
                    ssthresh = max(cwnd / 2, 2)
                    cwnd = ssthresh
                    phase = "congestion-avoidance"
                elif protocol == "cubic":
                    ssthresh = max(cwnd / 2, 2)
                    cwnd = ssthresh
                    phase = "congestion-avoidance"
                elif protocol == "bbr":
                    ssthresh = max(cwnd / 2, 2)
                    cwnd = ssthresh

                if old_ssthresh != ssthresh:
                    ssthresh_history.append({
                        "timestamp": int(time.time() * 1000),
                        "value": round(ssthresh, 2)
                    })
            else:
                # Packet received
                with simulation_lock:
                    simulation_stats["received"] += 1

                # Send ACK
                with simulation_lock:
                    simulation_stats["ackSent"] += 1

                # Check ACK loss
                if random.random() * 100 < cfg["ackLoss"]:
                    with simulation_lock:
                        simulation_stats["ackLost"] += 1
                else:
                    # ACK received
                    with simulation_lock:
                        simulation_stats["ackReceived"] += 1

                    acked_packets.add(seq_num)

                    # Update window
                    old_cwnd = cwnd
                    if protocol == "classic":
                        pass  # Fixed window
                    elif protocol == "tahoe":
                        if phase == "slow-start":
                            cwnd += 1
                            if cwnd >= ssthresh:
                                phase = "congestion-avoidance"
                        else:
                            cwnd += 1 / cwnd
                    elif protocol == "reno":
                        if phase == "slow-start":
                            cwnd += 1
                            if cwnd >= ssthresh:
                                phase = "congestion-avoidance"
                        elif phase == "congestion-avoidance":
                            cwnd += 1 / cwnd
                    elif protocol == "cubic":
                        if phase == "slow-start":
                            cwnd += 1
                            if cwnd >= ssthresh:
                                phase = "congestion-avoidance"
                        else:
                            # Simplified CUBIC
                            cwnd += 0.5
                    elif protocol == "bbr":
                        rtt = (cfg["packetTime"] + cfg["ackTime"]) / 1000.0
                        bdp = cfg["bandwidth"] * rtt
                        cwnd = min(bdp * 2, cwnd + 0.5)

                    if int(old_cwnd) != int(cwnd):
                        window_history.append({
                            "timestamp": int(time.time() * 1000),
                            "value": round(cwnd, 2)
                        })

        time.sleep(packet_interval)

    with simulation_lock:
        simulation_stats["windowHistory"] = window_history
        simulation_stats["ssthreshHistory"] = ssthresh_history


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
