import math
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import traceback
from datetime import datetime

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from backend.database import init_db, get_calibracao, save_calibracao, delete_calibracao, list_calibracoes as db_list_calibracoes, get_incerteza_u
from backend.instruments import INSTRUMENT_TYPES, get_instrument, aplicar_correcoes, calc_incerteza, _correcao_ponto_fixo
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
monitor_progress = {"current": 0, "total": 0}


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/ports", methods=["GET"])
def api_ports():
    show_all = request.args.get("all", "0") == "1"
    ports = find_usb_serial_ports(all_ports=show_all)

    if not ports:
        ports = [
            {"device": "sim1", "description": "Simulado #1 - virtual", "hwid": "", "manufacturer": "", "serial_number": "", "virtual": True},
            {"device": "sim2", "description": "Simulado #2 - virtual", "hwid": "", "manufacturer": "", "serial_number": "", "virtual": True},
            {"device": "sim3", "description": "Simulado #3 - virtual", "hwid": "", "manufacturer": "", "serial_number": "", "virtual": True},
            {"device": "sim4", "description": "Simulado #4 - virtual", "hwid": "", "manufacturer": "", "serial_number": "", "virtual": True},
        ]
        _seed_calibracoes_teste()

    for port in ports:
        device = port["device"]
        cfg = assignments.get(device, {})
        instr_type = cfg.get("type", "")
        port["assigned_type"] = instr_type
        port["assigned_label"] = cfg.get("label", "")
        port["assigned_url"] = cfg.get("url", "")
        port["instrument_label"] = (
            INSTRUMENT_TYPES[instr_type]["label"]
            if instr_type in INSTRUMENT_TYPES
            else ""
        )
        port["has_humidity"] = (
            INSTRUMENT_TYPES[instr_type].get("has_humidity", True)
            if instr_type in INSTRUMENT_TYPES
            else True
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
            existing = assignments.get(device, {})
            url = data.get("url", existing.get("url", ""))
            assignments[device] = {"type": instr_type, "label": label, "url": url}

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


@app.route("/api/url", methods=["POST"])
def api_url():
    data = request.get_json()
    device = data.get("device")
    url = data.get("url", "")

    if not device:
        return jsonify({"error": "device e obrigatorio"}), 400

    with lock:
        if device in assignments:
            assignments[device]["url"] = url
            return jsonify({"status": "ok", "device": device, "url": url})

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
        url = cfg.get("url", "") if instr_type == "termhigrpi" else ""
        target = url if url else (label if instr_type == "termhigrpi" else device)
        result = instrument.read(target)
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
        types[key] = {
            "label": info["label"],
            "has_humidity": info.get("has_humidity", True),
        }
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


def _csv_val(v):
    if v is None or v == "":
        return ""
    return str(v).replace(".", ",")


@app.route("/api/snapshots/csv", methods=["GET"])
def api_snapshots_csv():
    with lock:
        snaps = list(snapshots)

    if not snaps:
        return "sem dados\n", 200, {"Content-Type": "text/plain; charset=utf-8"}

    s = snaps[-1]
    instrumentos = s.get("instrumentos", {})
    labels = sorted(instrumentos.keys())
    n_med = s.get("n_medicoes", 0)

    def _row(*args):
        return ";".join(str(a) for a in args)

    lines = []
    lines.append(_row("RELATORIO DE CHECAGEM"))
    lines.append(_row("Timestamp", s.get("timestamp", "")))
    lines.append(_row("N medicoes", n_med))
    lines.append(_row("Intervalo (s)", _csv_val(s.get("intervalo", ""))))
    lines.append("")

    live_snaps = [sn for sn in snaps if sn.get("readings")]

    lines.append(_row("MEDICOES BRUTAS"))
    header = ["Timestamp"]
    for lb in labels:
        inst = instrumentos[lb]
        if "medicoes_temp" in inst:
            header.append(f"{lb} T bruta")
        if "medicoes_umid" in inst:
            header.append(f"{lb} U bruta")
    lines.append(_row(*header))

    for i in range(n_med):
        ts = live_snaps[i]["timestamp"] if i < len(live_snaps) else ""
        row = [ts]
        for lb in labels:
            inst = instrumentos[lb]
            if "medicoes_temp" in inst:
                v = inst["medicoes_temp"][i] if i < len(inst["medicoes_temp"]) else ""
                row.append(_csv_val(v))
            if "medicoes_umid" in inst:
                v = inst["medicoes_umid"][i] if i < len(inst["medicoes_umid"]) else ""
                row.append(_csv_val(v))
        lines.append(_row(*row))

    lines.append("")
    lines.append(_row("MEDICOES CORRIGIDAS (Eq. Linear)"))
    header = ["Timestamp"]
    for lb in labels:
        inst = instrumentos[lb]
        if "medicoes_temp_corr" in inst:
            header.append(f"{lb} T corr")
        if "medicoes_umid_corr" in inst:
            header.append(f"{lb} U corr")
    lines.append(_row(*header))

    for i in range(n_med):
        ts = live_snaps[i]["timestamp"] if i < len(live_snaps) else ""
        row = [ts]
        for lb in labels:
            inst = instrumentos[lb]
            if "medicoes_temp_corr" in inst:
                v = inst["medicoes_temp_corr"][i] if i < len(inst["medicoes_temp_corr"]) else ""
                row.append(_csv_val(v))
            if "medicoes_umid_corr" in inst:
                v = inst["medicoes_umid_corr"][i] if i < len(inst["medicoes_umid_corr"]) else ""
                row.append(_csv_val(v))
        lines.append(_row(*row))

    lines.append("")
    lines.append(_row("MEDICOES CORRIGIDAS (Ponto Fixo)"))
    header = ["Timestamp"]
    for lb in labels:
        inst = instrumentos[lb]
        if "medicoes_temp_corr_pf" in inst:
            header.append(f"{lb} T corr PF")
        if "medicoes_umid_corr_pf" in inst:
            header.append(f"{lb} U corr PF")
    lines.append(_row(*header))

    for i in range(n_med):
        ts = live_snaps[i]["timestamp"] if i < len(live_snaps) else ""
        row = [ts]
        for lb in labels:
            inst = instrumentos[lb]
            if "medicoes_temp_corr_pf" in inst:
                v = inst["medicoes_temp_corr_pf"][i] if i < len(inst["medicoes_temp_corr_pf"]) else ""
                row.append(_csv_val(v))
            if "medicoes_umid_corr_pf" in inst:
                v = inst["medicoes_umid_corr_pf"][i] if i < len(inst["medicoes_umid_corr_pf"]) else ""
                row.append(_csv_val(v))
        lines.append(_row(*row))

    lines.append("")
    lines.append(_row("RESUMO ESTATISTICO (Eq. Linear)"))
    lines.append(_row("Instrumento", "Grandeza", "Media Bruta", "Media Corr", "Desvio Padrao", "u_repet", "u_res", "u_corr", "u_cert", "u_combinada", "U (k=2)", "En"))

    with lock:
        ref_temp = references.get("temperatura", "")
        ref_umid = references.get("umidade", "")

    lin_keys = [("incerteza_temp", "temperatura", "Temperatura"),
                ("incerteza_umid", "umidade", "Umidade")]
    for lb in labels:
        inst = instrumentos[lb]
        inst_media_bruta_temp = inst.get("media_bruta_temp")
        inst_media_bruta_umid = inst.get("media_bruta_umid")
        for key, tipo, grand in lin_keys:
            if key in inst:
                u = inst[key]
                bruta = inst_media_bruta_temp if tipo == "temperatura" else inst_media_bruta_umid
                en_val = inst.get("en", {}).get(tipo, "")
                lines.append(_row(
                    lb, grand,
                    _csv_val(bruta),
                    _csv_val(u.get("media")),
                    _csv_val(u.get("desvio_padrao")),
                    _csv_val(u.get("u_repet")),
                    _csv_val(u.get("u_res")),
                    _csv_val(u.get("u_corr")),
                    _csv_val(u.get("u_cert")),
                    _csv_val(u.get("u_combinada")),
                    _csv_val(u.get("U_expandida")),
                    _csv_val(en_val),
                ))

    pf_keys = [("incerteza_temp_pf", "temperatura", "Temperatura"),
               ("incerteza_umid_pf", "umidade", "Umidade")]
    if any(any(k in inst for k, _, _ in pf_keys) for inst in instrumentos.values()):
        lines.append("")
        lines.append(_row("RESUMO ESTATISTICO (Ponto Fixo)"))
        lines.append(_row("Instrumento", "Grandeza", "Media Bruta", "Media Corr", "Desvio Padrao", "u_repet", "u_res", "u_corr", "u_cert", "u_combinada", "U (k=2)", "En"))
        for lb in labels:
            inst = instrumentos[lb]
            inst_media_bruta_temp = inst.get("media_bruta_temp")
            inst_media_bruta_umid = inst.get("media_bruta_umid")
            for key, tipo, grand in pf_keys:
                if key in inst:
                    u = inst[key]
                    bruta = inst_media_bruta_temp if tipo == "temperatura" else inst_media_bruta_umid
                    en_val = inst.get("en", {}).get(tipo, "")
                    lines.append(_row(
                        lb, grand,
                        _csv_val(bruta),
                        _csv_val(u.get("media")),
                        _csv_val(u.get("desvio_padrao")),
                        _csv_val(u.get("u_repet")),
                        _csv_val(u.get("u_res")),
                        _csv_val(u.get("u_corr")),
                        _csv_val(u.get("u_cert")),
                        _csv_val(u.get("u_combinada")),
                        _csv_val(u.get("U_expandida")),
                        _csv_val(en_val),
                    ))

    lines.append("")
    lines.append(_row("Referencia Temperatura", ref_temp))
    lines.append(_row("Referencia Umidade", ref_umid))

    csv_content = "\r\n".join(lines) + "\r\n"

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=relatorio_checagem.csv"},
    )


def _monitor_loop(interval: float, n_medicoes: int):
    global monitoring, monitor_progress
    items = []
    with lock:
        items = list(assignments.items())
        monitor_progress = {"current": 0, "total": n_medicoes}

    medicoes_temp = {}  # label -> list of raw temps
    medicoes_umid = {}  # label -> list of raw umids
    medicoes_temp_corr = {}
    medicoes_umid_corr = {}
    labels_tipo = {}    # label -> instr_type

    for device, cfg in items:
        label = cfg.get("label", device)
        labels_tipo[label] = cfg.get("type", "")
        medicoes_temp[label] = []
        medicoes_umid[label] = []
        medicoes_temp_corr[label] = []
        medicoes_umid_corr[label] = []

    for i in range(n_medicoes):
        if not monitoring:
            break

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        live_snapshot = {"timestamp": ts, "readings": {}}

        with ThreadPoolExecutor(max_workers=len(items)) as executor:
            futures = {
                executor.submit(_read_one_raw, device, cfg): device
                for device, cfg in items
            }
            for future in as_completed(futures):
                device = futures[future]
                cfg = assignments.get(device, {})
                label = cfg.get("label", device)
                try:
                    label, raw_temp, raw_umid = future.result()
                    calibracao = get_calibracao(label) if label else None
                    corr = aplicar_correcoes(raw_temp, raw_umid, calibracao)

                    t_corr = corr.get("temperature", raw_temp or "")
                    u_corr = corr.get("humidity", raw_umid or "")

                    if raw_temp:
                        medicoes_temp[label].append(raw_temp)
                        medicoes_temp_corr[label].append(t_corr)
                    if raw_umid:
                        medicoes_umid[label].append(raw_umid)
                        medicoes_umid_corr[label].append(u_corr)

                    live_snapshot["readings"][label] = {
                        "temperature": t_corr,
                        "humidity": u_corr,
                        "temperature_raw": raw_temp,
                        "humidity_raw": raw_umid,
                    }

                    with lock:
                        readings[device] = {
                            "device": device,
                            "label": label,
                            "temperature": t_corr,
                            "humidity": u_corr,
                            "temperature_raw": raw_temp,
                            "humidity_raw": raw_umid,
                            "instrument_type": cfg.get("type", ""),
                            "instrument_label": INSTRUMENT_TYPES.get(cfg.get("type", ""), {}).get("label", ""),
                            "status": "ok",
                            "timestamp": ts,
                            "certificado": calibracao.get("certificado", "") if calibracao else "",
                            "has_calibracao": bool(calibracao),
                            **corr,
                        }
                except Exception:
                    pass

        with lock:
            monitor_progress["current"] = i + 1
            if live_snapshot["readings"]:
                snapshots.append(live_snapshot)
                if len(snapshots) > 100:
                    snapshots.pop(0)

        if i < n_medicoes - 1:
            time.sleep(interval)

    try:
        snapshot = _build_snapshot(n_medicoes, interval, medicoes_temp, medicoes_umid,
                                   medicoes_temp_corr, medicoes_umid_corr,
                                   labels_tipo)
    except Exception as e:
        snapshot = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "instrumentos": {}, "erro": str(e), "n_medicoes": n_medicoes,
                    "intervalo": interval}
        print(f"ERRO _build_snapshot: {e}", flush=True)

    with lock:
        snapshots.append(snapshot)
        if len(snapshots) > 100:
            snapshots[:] = snapshots[-100:]

    monitoring = False
    with lock:
        monitor_progress["finalizado"] = True


def _read_one_raw(device: str, cfg: dict):
    instr_type = cfg.get("type", "")
    label = cfg.get("label", device)
    instrument = get_instrument(instr_type)
    url = cfg.get("url", "")
    target = url if url else (label if instr_type == "termhigrpi" else device)
    result = instrument.read(target)
    return label, result.get("temperature"), result.get("humidity")


def _build_snapshot(n_medicoes, intervalo, medicoes_temp, medicoes_umid,
                    medicoes_temp_corr, medicoes_umid_corr,
                    labels_tipo):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snapshot = {
        "timestamp": ts,
        "n_medicoes": n_medicoes,
        "intervalo": intervalo,
        "instrumentos": {},
    }

    with lock:
        ref_temp = references.get("temperatura", "")
        ref_umid = references.get("umidade", "")

    for label in labels_tipo:
        instr_type = labels_tipo[label]
        calibracao = get_calibracao(label) if label else None

        inst_data = {"tipo": instr_type}
        info = INSTRUMENT_TYPES.get(instr_type, {})
        inst_data["res_temp"] = info.get("res_temp", 0.1)
        inst_data["res_umid"] = info.get("res_umid", 0.1)

        temps_raw = medicoes_temp.get(label, [])
        temps = medicoes_temp_corr.get(label, [])
        umids_raw = medicoes_umid.get(label, [])
        umids = medicoes_umid_corr.get(label, [])

        temps_corr = []
        umids_corr = []
        incerteza_temp = {}
        incerteza_umid = {}

        if temps_raw:
            inst_data["medicoes_temp"] = temps_raw
            inst_data["medicoes_temp_corr"] = temps_corr = _to_floats(temps)
            incerteza_temp = calc_incerteza(temps_corr, instr_type, "temperatura", calibracao)
            inst_data["incerteza_temp"] = incerteza_temp
            raw_floats = _to_floats(temps_raw)
            if raw_floats:
                inst_data["media_bruta_temp"] = round(sum(raw_floats) / len(raw_floats), 6)
            if calibracao:
                pf = _correcao_ponto_fixo(calibracao.get("temperatura", []), 23.0)
                if pf:
                    c = pf["correcao"]
                    nd = len(str(info.get("res_temp", 0.1)).split(".")[1])
                    inst_data["medicoes_temp_corr_pf"] = [f"{float(r) + c:.{nd}f}" for r in temps_raw]
                    inst_data["incerteza_temp_pf"] = calc_incerteza(
                        _to_floats(inst_data["medicoes_temp_corr_pf"]),
                        instr_type, "temperatura", calibracao, modo="ponto_fixo")
                    inst_data["temp_coeff_pf"] = pf

        if umids_raw:
            inst_data["medicoes_umid"] = umids_raw
            inst_data["medicoes_umid_corr"] = umids_corr = _to_floats(umids)
            incerteza_umid = calc_incerteza(umids_corr, instr_type, "umidade", calibracao)
            inst_data["incerteza_umid"] = incerteza_umid
            raw_floats = _to_floats(umids_raw)
            if raw_floats:
                inst_data["media_bruta_umid"] = round(sum(raw_floats) / len(raw_floats), 6)
            if calibracao:
                pf = _correcao_ponto_fixo(calibracao.get("umidade", []), 50.0)
                if pf:
                    c = pf["correcao"]
                    nd = len(str(info.get("res_umid", 0.1)).split(".")[1])
                    inst_data["medicoes_umid_corr_pf"] = [f"{float(r) + c:.{nd}f}" for r in umids_raw]
                    inst_data["incerteza_umid_pf"] = calc_incerteza(
                        _to_floats(inst_data["medicoes_umid_corr_pf"]),
                        instr_type, "umidade", calibracao, modo="ponto_fixo")
                    inst_data["umid_coeff_pf"] = pf

        en = {}
        if ref_temp and label != ref_temp and temps_corr:
            ref_data = snapshot["instrumentos"].get(ref_temp, {})
            ref_temps = ref_data.get("medicoes_temp_corr", [])
            if ref_temps:
                ref_media = sum(ref_temps) / len(ref_temps)
                my_media = sum(temps_corr) / len(temps_corr)
                u_my = incerteza_temp.get("u_combinada")
                u_ref = ref_data.get("incerteza_temp", {}).get("u_combinada")
                if u_my and u_ref:
                    diff = abs(my_media - ref_media)
                    denom = math.sqrt(u_my**2 + u_ref**2)
                    en["temperatura"] = round(diff / denom, 2) if denom > 0 else None

        if ref_umid and label != ref_umid and umids_corr:
            ref_data = snapshot["instrumentos"].get(ref_umid, {})
            ref_umids = ref_data.get("medicoes_umid_corr", [])
            if ref_umids:
                ref_media = sum(ref_umids) / len(ref_umids)
                my_media = sum(umids_corr) / len(umids_corr)
                u_my = incerteza_umid.get("u_combinada")
                u_ref = ref_data.get("incerteza_umid", {}).get("u_combinada")
                if u_my and u_ref:
                    diff = abs(my_media - ref_media)
                    denom = math.sqrt(u_my**2 + u_ref**2)
                    en["umidade"] = round(diff / denom, 2) if denom > 0 else None

        if en:
            inst_data["en"] = en

        snapshot["instrumentos"][label] = inst_data

    return snapshot


def _to_floats(values: list[str]) -> list[float]:
    return [float(v) for v in values if v is not None and v != ""]


@app.route("/api/monitor/start", methods=["POST"])
def api_monitor_start():
    global monitoring, monitor_thread
    data = request.get_json() or {}
    intervalo = float(data.get("intervalo", 30))
    n_medicoes = int(data.get("n_medicoes", 10))

    if monitoring:
        return jsonify({"status": "ja em execucao"})

    with lock:
        snapshots.clear()

    monitoring = True
    monitor_thread = threading.Thread(target=_monitor_loop, args=(intervalo, n_medicoes), daemon=True)
    monitor_thread.start()
    return jsonify({"status": "iniciado", "intervalo": intervalo, "n_medicoes": n_medicoes})


@app.route("/api/monitor/stop", methods=["POST"])
def api_monitor_stop():
    global monitoring
    monitoring = False
    return jsonify({"status": "parado"})


@app.route("/api/monitor/status", methods=["GET"])
def api_monitor_status():
    last = None
    with lock:
        if snapshots:
            last = snapshots[-1]
    return jsonify({
        "running": monitoring,
        "progress": dict(monitor_progress),
        "finalizado": monitor_progress.get("finalizado", False),
        "last_snapshot": last,
    })


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


def _seed_calibracoes_teste():
    dados = {
        "CA 101": ("DIMCI 0001/2026", "2026-01-10",
            [{"indicacao": "20,0", "correcao": "0,0", "incerteza_u": "0,2"},
             {"indicacao": "23,0", "correcao": "-0,1", "incerteza_u": "0,2"},
             {"indicacao": "30,0", "correcao": "0,1", "incerteza_u": "0,3"}],
            [{"indicacao": "30,0", "correcao": "0,5", "incerteza_u": "1,0"},
             {"indicacao": "50,0", "correcao": "-0,3", "incerteza_u": "1,0"},
             {"indicacao": "70,0", "correcao": "0,2", "incerteza_u": "1,2"}]),
        "CA 102": ("DIMCI 0002/2026", "2026-02-15",
            [{"indicacao": "20,0", "correcao": "0,1", "incerteza_u": "0,2"},
             {"indicacao": "23,0", "correcao": "0,0", "incerteza_u": "0,2"},
             {"indicacao": "30,0", "correcao": "-0,1", "incerteza_u": "0,2"}],
            [{"indicacao": "30,0", "correcao": "-0,5", "incerteza_u": "1,0"},
             {"indicacao": "50,0", "correcao": "0,2", "incerteza_u": "1,2"},
             {"indicacao": "70,0", "correcao": "-0,2", "incerteza_u": "1,0"}]),
        "CA 103": ("DIMCI 0003/2026", "2026-03-20",
            [{"indicacao": "23,0", "correcao": "0,0", "incerteza_u": "0,1"}],
            []),
        "CA 104": ("DIMCI 0004/2026", "2026-04-25",
            [{"indicacao": "23,0", "correcao": "0,1", "incerteza_u": "0,2"}],
            [{"indicacao": "50,0", "correcao": "0,0", "incerteza_u": "1,0"}]),
    }
    for label, (cert, data_cal, temp, umid) in dados.items():
        if not get_calibracao(label):
            save_calibracao(label, cert, data_cal, temp, umid)
