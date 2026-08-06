import random
import traceback
import time
import serial
from abc import ABC, abstractmethod


class Instrument(ABC):
    @abstractmethod
    def read(self, port: str, timeout: int = 2) -> dict:
        ...

    @abstractmethod
    def init(self, ser: serial.Serial) -> None:
        ...

    def debug_raw(self, port: str, timeout: int = 3) -> dict:
        ser = serial.Serial(
            port=port,
            baudrate=self.BAUD,
            bytesize=self.BYTESIZE,
            parity=self.PARITY,
            stopbits=self.STOPBITS,
            timeout=timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            self.init(ser)
            return self._do_debug(ser)
        finally:
            ser.close()

    @abstractmethod
    def _do_debug(self, ser: serial.Serial) -> dict:
        ...


class Fluke1502A(Instrument):
    BAUD = 2400
    BYTESIZE = serial.EIGHTBITS
    PARITY = serial.PARITY_NONE
    STOPBITS = serial.STOPBITS_ONE

    def init(self, ser: serial.Serial) -> None:
        ser.write(b"SA=0\r\n")
        time.sleep(0.1)
        ser.write(b"DU=H\r\n")
        time.sleep(0.1)

    def _do_debug(self, ser: serial.Serial) -> dict:
        ser.write(b"F\r\n")
        rcv = ser.read(256)
        return {
            "command": "F\\r\\n",
            "raw_hex": rcv.hex(" "),
            "raw_bytes": len(rcv),
            "decoded": repr(rcv.decode("utf-8", errors="replace")),
        }

    def read(self, port: str, timeout: int = 2) -> dict:
        ser = serial.Serial(
            port=port,
            baudrate=self.BAUD,
            bytesize=self.BYTESIZE,
            parity=self.PARITY,
            stopbits=self.STOPBITS,
            timeout=timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            self.init(ser)
            ser.write(b"F\r\n")
            rcv = ser.read(50)
            temperature = rcv.decode("utf-8").strip()
            if not temperature:
                raise ValueError(
                    f"Resposta vazia do Fluke 1502A. Verifique:\n"
                    f"  - Cabo serial conectado e instrumento ligado\n"
                    f"  - Baud rate: {self.BAUD}\n"
                    f"  - Porta correta: {port}"
                )
            return {"temperature": temperature, "unit": "°C"}
        finally:
            ser.close()


class SatoOld(Instrument):
    BAUD = 9600
    BYTESIZE = serial.EIGHTBITS
    PARITY = serial.PARITY_NONE
    STOPBITS = serial.STOPBITS_ONE

    def init(self, ser: serial.Serial) -> None:
        pass

    def _do_debug(self, ser: serial.Serial) -> dict:
        lines = []
        for i in range(5):
            line = ser.readline()
            if line:
                lines.append({
                    "n": i + 1,
                    "raw_hex": line.hex(" "),
                    "decoded": repr(line.decode("utf-8", errors="replace")),
                })
        return {"lines_read": lines}

    def read(self, port: str, timeout: int = 2) -> dict:
        ser = serial.Serial(
            port=port,
            baudrate=self.BAUD,
            bytesize=self.BYTESIZE,
            parity=self.PARITY,
            stopbits=self.STOPBITS,
            timeout=timeout,
        )
        try:
            ser.reset_input_buffer()
            ser.readline()
            rcv = ser.readline()
            dec_str = rcv.decode("utf-8")
            if not dec_str.strip():
                raise ValueError(
                    f"Resposta vazia do Sato Antigo. Verifique:\n"
                    f"  - Cabo serial conectado e instrumento ligado\n"
                    f"  - Baud rate: {self.BAUD}\n"
                    f"  - Porta correta: {port}\n"
                    f"  - O instrumento envia dados continuamente?\n"
                    f"  - Timeout atual: {timeout}s"
                )
            data = dec_str.split()
            if len(data) < 3:
                raise ValueError(
                    f"Formato inesperado do Sato Antigo.\n"
                    f"Dados recebidos: {repr(dec_str)}\n"
                    f"Esperado: campos separados por espaco com temp e umidade"
                )
            temperature = float(data[1].replace(",", "")) / 10
            humidity = float(data[2]) / 10
            return {"temperature": f"{temperature:.1f}", "humidity": f"{humidity:.1f}", "unit_temp": "°C", "unit_umid": "%"}
        finally:
            ser.close()


class Sato(Instrument):
    BAUD = 19200
    BYTESIZE = serial.SEVENBITS
    PARITY = serial.PARITY_EVEN
    STOPBITS = serial.STOPBITS_ONE

    def init(self, ser: serial.Serial) -> None:
        pass

    def _do_debug(self, ser: serial.Serial) -> dict:
        lines = []
        for i in range(5):
            line = ser.readline()
            if line:
                lines.append({
                    "n": i + 1,
                    "raw_hex": line.hex(" "),
                    "decoded": repr(line.decode("utf-8", errors="replace")),
                })
        return {"lines_read": lines}

    def read(self, port: str, timeout: int = 2) -> dict:
        ser = serial.Serial(
            port=port,
            baudrate=self.BAUD,
            bytesize=self.BYTESIZE,
            parity=self.PARITY,
            stopbits=self.STOPBITS,
            timeout=timeout,
        )
        try:
            ser.reset_input_buffer()
            ser.readline()
            rcv = ser.readline()
            dec_str = rcv.decode("utf-8")
            if not dec_str.strip():
                raise ValueError(
                    f"Resposta vazia do Sato Novo. Verifique:\n"
                    f"  - Cabo serial conectado e instrumento ligado\n"
                    f"  - Baud rate: {self.BAUD} (7E1)\n"
                    f"  - Porta correta: {port}\n"
                    f"  - O instrumento envia dados continuamente?\n"
                    f"  - Timeout atual: {timeout}s"
                )
            data = dec_str.split()
            if len(data) < 3:
                raise ValueError(
                    f"Formato inesperado do Sato Novo.\n"
                    f"Dados recebidos: {repr(dec_str)}\n"
                    f"Esperado: campos separados por espaco com temp e umidade"
                )
            temperature = float(data[1].replace(",", "")) / 10
            humidity = float(data[2]) / 10
            return {"temperature": f"{temperature:.1f}", "humidity": f"{humidity:.1f}", "unit_temp": "°C", "unit_umid": "%"}
        finally:
            ser.close()


class HygroPalm(Instrument):
    BAUD = 19200
    BYTESIZE = serial.SEVENBITS
    PARITY = serial.PARITY_EVEN
    STOPBITS = serial.STOPBITS_ONE
    _query_string = "{u00RDD}"

    def init(self, ser: serial.Serial) -> None:
        pass

    def _do_debug(self, ser: serial.Serial) -> dict:
        ser.write((self._query_string + "\r").encode())
        rcv = ser.read(256)
        return {
            "command": self._query_string + "\\r",
            "raw_hex": rcv.hex(" "),
            "raw_bytes": len(rcv),
            "decoded": repr(rcv.decode("utf-8", errors="replace")),
        }

    def read(self, port: str, timeout: int = 2) -> dict:
        ser = serial.Serial(
            port=port,
            baudrate=self.BAUD,
            bytesize=self.BYTESIZE,
            parity=self.PARITY,
            stopbits=self.STOPBITS,
            timeout=timeout,
        )
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write((self._query_string + "\r").encode())
            rcv = ser.read(256)
            dec_str = rcv.decode("utf-8").strip()
            if not dec_str:
                raise ValueError(
                    f"Resposta vazia do HygroPalm. Verifique:\n"
                    f"  - Cabo serial conectado e instrumento ligado\n"
                    f"  - Baud rate: {self.BAUD} (7E1)\n"
                    f"  - Porta correta: {port}\n"
                    f"  - Comando enviado: {self._query_string}"
                )
            data_array = dec_str.replace(self._query_string.replace("}", " "), "").split(";")
            if len(data_array) < 2:
                raise ValueError(
                    f"Formato inesperado do HygroPalm.\n"
                    f"Dados recebidos: {repr(dec_str)}\n"
                    f"Esperado: {self._query_string} umid;temp;..."
                )
            humidity = float(data_array[0])
            temperature = float(data_array[1])
            return {
                "temperature": f"{temperature:.1f}",
                "humidity": f"{humidity:.1f}",
                "unit_temp": "°C",
                "unit_umid": "%",
            }
        finally:
            ser.close()


class Simulado(Instrument):
    BAUD = 0
    BYTESIZE = 0
    PARITY = "N"
    STOPBITS = 0

    def __init__(self):
        self._temp_base = 23.0 + random.uniform(-0.5, 0.5)
        self._umid_base = 50.0 + random.uniform(-2.0, 2.0)

    def init(self, ser):
        pass

    def _do_debug(self, ser):
        return {"simulado": True, "temp_base": self._temp_base, "umid_base": self._umid_base}

    def read(self, port: str = "", timeout: int = 2) -> dict:
        temp = self._temp_base + random.gauss(0, 0.02)
        umid = self._umid_base + random.gauss(0, 0.1)
        return {
            "temperature": f"{temp:.1f}",
            "humidity": f"{umid:.1f}",
            "unit_temp": "°C",
            "unit_umid": "%",
        }


INSTRUMENT_TYPES = {
    "simulado": {"label": "Simulado", "class": Simulado, "has_humidity": True, "res_temp": 0.1, "res_umid": 0.1},
    "fluke_1502a": {"label": "Fluke 1502A", "class": Fluke1502A, "has_humidity": False, "res_temp": 0.001},
    "sato": {"label": "Sato Novo", "class": Sato, "has_humidity": True, "res_temp": 0.1, "res_umid": 0.1},
    "sato_old": {"label": "Sato Antigo", "class": SatoOld, "has_humidity": True, "res_temp": 0.1, "res_umid": 0.1},
    "hygropalm": {"label": "HygroPalm", "class": HygroPalm, "has_humidity": True, "res_temp": 0.1, "res_umid": 0.1},
}


def get_instrument(instrument_type: str) -> Instrument:
    if instrument_type not in INSTRUMENT_TYPES:
        raise ValueError(f"Tipo de instrumento desconhecido: {instrument_type}")
    return INSTRUMENT_TYPES[instrument_type]["class"]()


def parse_decimal(value: str) -> float:
    return float(value.replace(",", "."))


def _least_squares(pontos: list[dict]) -> tuple[float, float] | None:
    if not pontos:
        return None
    xs = [parse_decimal(p["indicacao"]) for p in pontos]
    cs = [parse_decimal(p["correcao"]) for p in pontos]
    ys = [x + c for x, c in zip(xs, cs)]
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return None
    a = (n * sum_xy - sum_x * sum_y) / denom
    b = (sum_y - a * sum_x) / n
    return a, b


def _decimal_places(value: str) -> int:
    if "." in value:
        return len(value.split(".")[1])
    if "," in value:
        return len(value.split(",")[1])
    return 0


def _correcao_ponto_fixo(pontos: list[dict], valor_referencia: float) -> dict | None:
    if not pontos:
        return None
    best = None
    best_dist = float("inf")
    for p in pontos:
        ind = parse_decimal(p["indicacao"])
        dist = abs(ind - valor_referencia)
        if dist < best_dist:
            best_dist = dist
            best = p
    if best is None:
        return None
    return {
        "indicacao": best["indicacao"],
        "correcao": float(parse_decimal(best["correcao"])),
    }


def aplicar_correcoes(raw_temperature: str | None, raw_humidity: str | None,
                       calibracao: dict | None, modo: str = "ponto_fixo") -> dict:
    result = {}
    if raw_temperature is not None and raw_temperature != "":
        raw_t = float(raw_temperature)
        ndigits = _decimal_places(raw_temperature)
        result["temperature_raw"] = raw_temperature
        result["temperature"] = raw_temperature
        result["temperature_corrected"] = None
        if calibracao and calibracao.get("temperatura"):
            if modo == "ponto_fixo":
                pf = _correcao_ponto_fixo(calibracao["temperatura"], 23.0)
                if pf:
                    corrected = raw_t + pf["correcao"]
                    result["temperature"] = f"{corrected:.{ndigits}f}"
                    result["temperature_corrected"] = f"{corrected:.{ndigits}f}"
                    result["temperature_ponto_fixo"] = pf["indicacao"]
            else:
                coeff = _least_squares(calibracao["temperatura"])
                if coeff:
                    a, b = coeff
                    corrected = a * raw_t + b
                    result["temperature"] = f"{corrected:.{ndigits}f}"
                    result["temperature_corrected"] = f"{corrected:.{ndigits}f}"
                    result["temperature_coeff_a"] = round(a, 6)
                    result["temperature_coeff_b"] = round(b, 6)

    if raw_humidity is not None and raw_humidity != "":
        raw_u = float(raw_humidity)
        ndigits = _decimal_places(raw_humidity)
        result["humidity_raw"] = raw_humidity
        result["humidity"] = raw_humidity
        result["humidity_corrected"] = None
        if calibracao and calibracao.get("umidade"):
            if modo == "ponto_fixo":
                pf = _correcao_ponto_fixo(calibracao["umidade"], 50.0)
                if pf:
                    corrected = raw_u + pf["correcao"]
                    result["humidity"] = f"{corrected:.{ndigits}f}"
                    result["humidity_corrected"] = f"{corrected:.{ndigits}f}"
                    result["humidity_ponto_fixo"] = pf["indicacao"]
            else:
                coeff = _least_squares(calibracao["umidade"])
                if coeff:
                    a, b = coeff
                    corrected = a * raw_u + b
                    result["humidity"] = f"{corrected:.{ndigits}f}"
                    result["humidity_corrected"] = f"{corrected:.{ndigits}f}"
                    result["humidity_coeff_a"] = round(a, 6)
                    result["humidity_coeff_b"] = round(b, 6)

    return result


def calc_incerteza(medicoes: list[float], instr_type: str, tipo: str,
                   calibracao: dict | None, k: float = 2.0) -> dict:
    n = len(medicoes)
    if n < 2:
        return {}

    mean = sum(medicoes) / n
    variance = sum((x - mean) ** 2 for x in medicoes) / (n - 1)
    desvio = variance ** 0.5
    u_repet = desvio / (n ** 0.5)

    info = INSTRUMENT_TYPES.get(instr_type, {})
    if tipo == "temperatura":
        resolucao = info.get("res_temp", 0.1)
    else:
        resolucao = info.get("res_umid", 0.1)
    u_res = resolucao / (12 ** 0.5)

    u_cert = None
    if calibracao:
        pontos = calibracao.get(tipo, [])
        if pontos:
            u_cert = parse_decimal(pontos[0]["incerteza_u"]) / k

    componentes = {"u_repet": round(u_repet, 8), "u_res": round(u_res, 8)}
    sum_sq = u_repet**2 + u_res**2
    if u_cert is not None:
        componentes["u_cert"] = round(u_cert, 8)
        sum_sq += u_cert**2

    u_combinada = sum_sq ** 0.5
    return {
        "media": round(mean, 6),
        "desvio_padrao": round(desvio, 6),
        **componentes,
        "u_combinada": round(u_combinada, 6),
        "U_expandida": round(k * u_combinada, 6),
        "k": k,
    }
