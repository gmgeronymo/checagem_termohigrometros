import math
import csv
import io
import json
import threading
import time
import traceback
from datetime import datetime

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.database import init_db, get_calibracao, save_calibracao, delete_calibracao, list_calibracoes as db_list_calibracoes, get_incerteza_u
from backend.instruments import INSTRUMENT_TYPES, get_instrument, aplicar_correcoes
from backend.serial_utils import find_usb_serial_ports

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

init_db()

assignments: dict[str, dict] = {}
readings: dict[str, dict] = {}
snapshots: list[dict] = []
references: dict[str, str] = {"temperatura": "", "umidade": ""}
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
        cfg = assignments.get(device, {})
        instr_type = cfg.get("type", "")
        port["assigned_type"] = instr_type
        port["assigned_label"] = cfg.get("label", "")
        port["instrument_label"] = (
            INSTRUMENT_TYPES[instr_type]["label"]
            if instr_type in INSTRUMENT_TYPES
            else ""
        )
        port["last_reading"] = readings.get(device)
    return jsonify(ports)


@app.route("/api/assign", methods=["POST"])
def api_assign():
    data = request.get_json()
    device = data.get("device")
    instr_type = data.get("type", "")
    label = data.get("label", "")

    if not device:
        return jsonify({"error": "device e obrigatorio"}), 400

    if instr_type not in INSTRUMENT_TYPES and instr_type != "":
        return jsonify({"error": f"tipo invalido: {instr_type}"}), 400

    with lock:
        if instr_type == "":
            assignments.pop(device, None)
            readings.pop(device, None)
        else:
            assignments[device] = {"type": instr_type, "label": label}

    return jsonify({"status": "ok", "device": device, "type": instr_type, "label": label})


@app.route("/api/label", methods=["POST"])
def api_label():
    data = request.get_json()
    device = data.get("device")
    label = data.get("label", "")

    if not device:
        return jsonify({"error": "device e obrigatorio"}), 400

    with lock:
        if device in assignments:
            assignments[device]["label"] = label
            return jsonify({"status": "ok", "device": device, "label": label})

    return jsonify({"error": "dispositivo nao configurado"}), 400


@app.route("/api/read", methods=["POST"])
def api_read():
    data = request.get_json()
    device = data.get("device")

    if not device:
        return jsonify({"error": "device e obrigatorio"}), 400

    with lock:
        cfg = assignments.get(device, {})

    instr_type = cfg.get("type", "")
    label = cfg.get("label", "")
    if not instr_type:
        return jsonify({"error": "dispositivo nao configurado"}), 400

    try:
        instrument = get_instrument(instr_type)
        result = instrument.read(device)
    except Exception as e:
        tb = traceback.format_exc()
        error_result = {
            "status": "error",
            "device": device,
            "instrument_type": instr_type,
            "instrument_label": INSTRUMENT_TYPES.get(instr_type, {}).get("label", instr_type),
            "error": str(e),
            "traceback": tb,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with lock:
            readings[device] = error_result
        return jsonify(error_result), 500

    raw_temp = result.get("temperature")
    raw_umid = result.get("humidity")

    calibracao = None
    if label:
        calibracao = get_calibracao(label)

    correcoes = aplicar_correcoes(raw_temp, raw_umid, calibracao)
    result.update(correcoes)

    if calibracao:
        result["certificado"] = calibracao.get("certificado", "")
        result["data_calibracao"] = calibracao.get("data_calibracao", "")
        result["has_calibracao"] = True
    else:
        result["has_calibracao"] = False

    result["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result["device"] = device
    result["instrument_type"] = instr_type
    result["instrument_label"] = INSTRUMENT_TYPES[instr_type]["label"]
    result["label"] = label
    result["status"] = "ok"

    with lock:
        readings[device] = result

    return jsonify(result)


@app.route("/api/debug", methods=["POST"])
def api_debug():
    data = request.get_json()
    device = data.get("device")
    instr_type = data.get("type")

    if not device:
        return jsonify({"error": "device e obrigatorio"}), 400

    if not instr_type or instr_type not in INSTRUMENT_TYPES:
        return jsonify({"error": "tipo de instrumento nao informado ou invalido"}), 400

    try:
        instrument = get_instrument(instr_type)
        raw = instrument.debug_raw(device, timeout=data.get("timeout", 3))
        result = {
            "status": "ok",
            "device": device,
            "instrument_type": instr_type,
            "instrument_label": INSTRUMENT_TYPES[instr_type]["label"],
            "debug": raw,
            "baud": instrument.BAUD,
            "bytesize": instrument.BYTESIZE,
            "parity": instrument.PARITY,
            "stopbits": instrument.STOPBITS,
        }
        return jsonify(result)
    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({
            "status": "error",
            "device": device,
            "error": str(e),
            "traceback": tb,
        }), 500


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
        for device, cfg in assignments.items():
            instr_type = cfg.get("type", "")
            label = cfg.get("label", "")
            config.append({
                "device": device,
                "type": instr_type,
                "label": label,
                "instrument_label": INSTRUMENT_TYPES.get(instr_type, {}).get("label", instr_type),
            })
        refs = dict(references)
    return jsonify({"instruments": config, "references": refs})


@app.route("/api/references", methods=["GET"])
def api_references():
    with lock:
        return jsonify(dict(references))


@app.route("/api/references", methods=["POST"])
def api_set_references():
    data = request.get_json()
    with lock:
        if "temperatura" in data:
            references["temperatura"] = data["temperatura"]
        if "umidade" in data:
            references["umidade"] = data["umidade"]
    return jsonify({"status": "ok", "references": dict(references)})


@app.route("/api/snapshots", methods=["GET"])
def api_snapshots():
    with lock:
        return jsonify(list(snapshots))


@app.route("/api/snapshots/csv", methods=["GET"])
def api_snapshots_csv():
    with lock:
        snaps = list(snapshots)

    if not snaps:
        return "sem dados\n", 200, {"Content-Type": "text/plain; charset=utf-8"}

    labels = set()
    for s in snaps:
        labels.update(s["readings"].keys())
    labels = sorted(labels)

    header = ["Timestamp"]
    for lb in labels:
        header.append(f"{lb}_T (°C)")
        header.append(f"{lb}_U (%)")
        header.append(f"{lb}_En_T")
        header.append(f"{lb}_En_U")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)

    for s in snaps:
        row = [s["timestamp"]]
        for lb in labels:
            r = s["readings"].get(lb, {})
            row.append(r.get("temperature", ""))
            row.append(r.get("humidity", ""))
            en = r.get("en", {})
            row.append(en.get("temperatura", ""))
            row.append(en.get("umidade", ""))
        writer.writerow(row)

    csv_content = output.getvalue()
    output.close()

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=leituras.csv"},
    )


def _monitor_loop(interval: float):
    global monitoring
    while monitoring:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        snapshot = {"timestamp": ts, "readings": {}}

        with lock:
            items = list(assignments.items())

        for device, cfg in items:
            instr_type = cfg.get("type", "")
            label = cfg.get("label", device)
            try:
                instrument = get_instrument(instr_type)
                result = instrument.read(device)

                raw_temp = result.get("temperature")
                raw_umid = result.get("humidity")
                calibracao = get_calibracao(label) if label else None
                correcoes = aplicar_correcoes(raw_temp, raw_umid, calibracao)
                result.update(correcoes)

                if calibracao:
                    result["certificado"] = calibracao.get("certificado", "")
                    result["data_calibracao"] = calibracao.get("data_calibracao", "")
                    result["has_calibracao"] = True
                else:
                    result["has_calibracao"] = False

                result["timestamp"] = ts
                result["device"] = device
                result["instrument_type"] = instr_type
                result["instrument_label"] = INSTRUMENT_TYPES[instr_type]["label"]
                result["label"] = label
                result["status"] = "ok"

                with lock:
                    readings[device] = result

                flattened = {
                    "temperature": result.get("temperature", ""),
                    "humidity": result.get("humidity", ""),
                }
                snapshot["readings"][label] = flattened
            except Exception as e:
                with lock:
                    readings[device] = {
                        "device": device,
                        "instrument_type": instr_type,
                        "label": label,
                        "status": "error",
                        "error": str(e),
                        "timestamp": ts,
                    }

        if snapshot["readings"]:
            _compute_errors_normalizados(snapshot)

            with lock:
                snapshots.append(snapshot)
                if len(snapshots) > 1000:
                    snapshots[:] = snapshots[-1000:]

        time.sleep(interval)


def _compute_errors_normalizados(snapshot: dict):
    with lock:
        ref_temp = references.get("temperatura", "")
        ref_umid = references.get("umidade", "")

    for label, reading in snapshot["readings"].items():
        en = {}

        if ref_temp and label != ref_temp and "temperature" in reading and reading["temperature"]:
            ref_reading = snapshot["readings"].get(ref_temp, {})
            ref_val = ref_reading.get("temperature")
            if ref_val and ref_val != "":
                u_instr = get_incerteza_u(label, "temperatura")
                u_ref = get_incerteza_u(ref_temp, "temperatura")
                if u_instr is not None and u_ref is not None:
                    diff = abs(float(reading["temperature"]) - float(ref_val))
                    denom = math.sqrt(u_instr**2 + u_ref**2)
                    en["temperatura"] = round(diff / denom, 2) if denom > 0 else None

        if ref_umid and label != ref_umid and "humidity" in reading and reading["humidity"]:
            ref_reading = snapshot["readings"].get(ref_umid, {})
            ref_val = ref_reading.get("humidity")
            if ref_val and ref_val != "":
                u_instr = get_incerteza_u(label, "umidade")
                u_ref = get_incerteza_u(ref_umid, "umidade")
                if u_instr is not None and u_ref is not None:
                    diff = abs(float(reading["humidity"]) - float(ref_val))
                    denom = math.sqrt(u_instr**2 + u_ref**2)
                    en["umidade"] = round(diff / denom, 2) if denom > 0 else None

        if en:
            reading["en"] = en


@app.route("/api/monitor/start", methods=["POST"])
def api_monitor_start():
    global monitoring, monitor_thread
    data = request.get_json() or {}
    interval = float(data.get("interval", 5))

    if monitoring:
        return jsonify({"status": "ja em execucao", "interval": interval})

    with lock:
        snapshots.clear()

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


@app.route("/api/calibracao/<label>", methods=["GET"])
def api_get_calibracao(label):
    cal = get_calibracao(label)
    if cal is None:
        return jsonify({"label": label, "certificado": "", "data_calibracao": "", "temperatura": [], "umidade": []})
    return jsonify(cal)


@app.route("/api/calibracao", methods=["POST"])
def api_save_calibracao():
    data = request.get_json()
    label = data.get("label", "").strip()
    certificado = data.get("certificado", "").strip()
    data_calibracao = data.get("data_calibracao", "").strip()
    temperatura = data.get("temperatura", [])
    umidade = data.get("umidade", [])

    if not label:
        return jsonify({"error": "label e obrigatorio"}), 400

    save_calibracao(label, certificado, data_calibracao, temperatura, umidade)
    return jsonify({"status": "ok", "label": label})


@app.route("/api/calibracao/<label>", methods=["DELETE"])
def api_delete_calibracao(label):
    deleted = delete_calibracao(label)
    if deleted:
        return jsonify({"status": "ok", "label": label})
    return jsonify({"error": "registro nao encontrado"}), 404


@app.route("/api/calibracoes", methods=["GET"])
def api_list_calibracoes():
    return jsonify(db_list_calibracoes())
