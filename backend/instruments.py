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
        self.init(ser)
        ser.write(b"F\r\n")
        rcv = ser.read(50)
        ser.close()

        temperature = rcv.decode("utf-8").strip()
        return {"temperature": temperature, "unit": "°C"}


class SatoOld(Instrument):
    BAUD = 9600
    BYTESIZE = serial.EIGHTBITS
    PARITY = serial.PARITY_NONE
    STOPBITS = serial.STOPBITS_ONE

    def init(self, ser: serial.Serial) -> None:
        pass

    def read(self, port: str, timeout: int = 2) -> dict:
        ser = serial.Serial(
            port=port,
            baudrate=self.BAUD,
            bytesize=self.BYTESIZE,
            parity=self.PARITY,
            stopbits=self.STOPBITS,
            timeout=timeout,
        )
        ser.readline()
        rcv = ser.readline()
        ser.close()

        dec_str = rcv.decode("utf-8")
        data = dec_str.split()
        temperature = float(data[1].replace(",", "")) / 10
        humidity = float(data[2]) / 10

        return {"temperature": f"{temperature:.1f}", "humidity": f"{humidity:.1f}", "unit_temp": "°C", "unit_umid": "%"}


class Sato(Instrument):
    BAUD = 19200
    BYTESIZE = serial.SEVENBITS
    PARITY = serial.PARITY_EVEN
    STOPBITS = serial.STOPBITS_ONE

    def init(self, ser: serial.Serial) -> None:
        pass

    def read(self, port: str, timeout: int = 2) -> dict:
        ser = serial.Serial(
            port=port,
            baudrate=self.BAUD,
            bytesize=self.BYTESIZE,
            parity=self.PARITY,
            stopbits=self.STOPBITS,
            timeout=timeout,
        )
        ser.readline()
        rcv = ser.readline()
        ser.close()

        dec_str = rcv.decode("utf-8")
        data = dec_str.split()
        temperature = float(data[1].replace(",", "")) / 10
        humidity = float(data[2]) / 10

        return {"temperature": f"{temperature:.1f}", "humidity": f"{humidity:.1f}", "unit_temp": "°C", "unit_umid": "%"}


INSTRUMENT_TYPES = {
    "fluke_1502a": {"label": "Fluke 1502A", "class": Fluke1502A},
    "sato": {"label": "Sato Novo", "class": Sato},
    "sato_old": {"label": "Sato Antigo", "class": SatoOld},
}


def get_instrument(instrument_type: str) -> Instrument:
    if instrument_type not in INSTRUMENT_TYPES:
        raise ValueError(f"Tipo de instrumento desconhecido: {instrument_type}")
    return INSTRUMENT_TYPES[instrument_type]["class"]()
