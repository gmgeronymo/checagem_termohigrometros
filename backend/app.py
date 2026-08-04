import json
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.instruments import INSTRUMENT_TYPES, get_instrument
from backend.serial_utils import find_usb_serial_ports

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

assignments: dict[str, str] = {}
readings: dict[str, dict] = {}
lock = threading.Lock()
monitoring = False
monitor_thread = None


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/ports", methods=["GET"])
def api_ports():
    show_all = request.args.get("all", "0") == "1"
    ports = find_usb_serial_ports(all_ports=show_all)
    for port in ports:
        device = port["device"]
        port["assigned_type"] = assignments.get(device, "")
        port["instrument_label"] = (
            INSTRUMENT_TYPES[port["assigned_type"]]["label"]
            if port["assigned_type"] in INSTRUMENT_TYPES
            else ""
        )
        port["last_reading"] = readings.get(device)
    return jsonify(ports)


@app.route("/api/assign", methods=["POST"])
def api_assign():
    data = request.get_json()
    device = data.get("device")
    instr_type = data.get("type")

    if not device or not instr_type:
        return jsonify({"error": "device e type sao obrigatorios"}), 400

    if instr_type not in INSTRUMENT_TYPES and instr_type != "":
        return jsonify({"error": f"tipo invalido: {instr_type}"}), 400

    with lock:
        if instr_type == "":
            assignments.pop(device, None)
            readings.pop(device, None)
        else:
            assignments[device] = instr_type

    return jsonify({"status": "ok", "device": device, "type": instr_type})


@app.route("/api/read", methods=["POST"])
def api_read():
    data = request.get_json()
    device = data.get("device")

    if not device:
        return jsonify({"error": "device e obrigatorio"}), 400

    with lock:
        instr_type = assignments.get(device)

    if not instr_type:
        return jsonify({"error": "dispositivo nao configurado"}), 400

    try:
        instrument = get_instrument(instr_type)
        result = instrument.read(device)
        result["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result["device"] = device
        result["instrument_type"] = instr_type
        result["instrument_label"] = INSTRUMENT_TYPES[instr_type]["label"]
        result["status"] = "ok"

        with lock:
            readings[device] = result

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "status": "error", "device": device}), 500


@app.route("/api/instrument_types", methods=["GET"])
def api_instrument_types():
    types = {}
    for key, info in INSTRUMENT_TYPES.items():
        types[key] = info["label"]
    return jsonify(types)


@app.route("/api/config", methods=["GET"])
def api_config():
    with lock:
        config = []
        for device, instr_type in assignments.items():
            label = INSTRUMENT_TYPES.get(instr_type, {}).get("label", instr_type)
            config.append({
                "device": device,
                "type": instr_type,
                "label": label,
            })
    return jsonify(config)


def _monitor_loop(interval: float):
    global monitoring
    while monitoring:
        with lock:
            items = list(assignments.items())
        for device, instr_type in items:
            try:
                instrument = get_instrument(instr_type)
                result = instrument.read(device)
                result["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                result["device"] = device
                result["instrument_type"] = instr_type
                result["instrument_label"] = INSTRUMENT_TYPES[instr_type]["label"]
                result["status"] = "ok"
                with lock:
                    readings[device] = result
            except Exception as e:
                with lock:
                    readings[device] = {
                        "device": device,
                        "instrument_type": instr_type,
                        "status": "error",
                        "error": str(e),
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
        time.sleep(interval)


@app.route("/api/monitor/start", methods=["POST"])
def api_monitor_start():
    global monitoring, monitor_thread
    data = request.get_json() or {}
    interval = float(data.get("interval", 5))

    if monitoring:
        return jsonify({"status": "ja em execucao", "interval": interval})

    monitoring = True
    monitor_thread = threading.Thread(target=_monitor_loop, args=(interval,), daemon=True)
    monitor_thread.start()
    return jsonify({"status": "iniciado", "interval": interval})


@app.route("/api/monitor/stop", methods=["POST"])
def api_monitor_stop():
    global monitoring
    monitoring = False
    return jsonify({"status": "parado"})


@app.route("/api/monitor/status", methods=["GET"])
def api_monitor_status():
    return jsonify({"running": monitoring})
