import glob
import os
import serial.tools.list_ports


def list_serial_ports() -> list[dict]:
    ports = serial.tools.list_ports.comports()
    result = []
    for port in ports:
        if not port.device:
            continue
        result.append({
            "device": port.device,
            "description": port.description or "",
            "hwid": port.hwid or "",
            "manufacturer": port.manufacturer or "",
            "serial_number": port.serial_number or "",
        })
    return result


def find_usb_serial_ports(all_ports: bool = False) -> list[dict]:
    ports = list_serial_ports()
    if all_ports:
        return ports
    usb_ports = []
    for p in ports:
        device = p["device"].lower()
        if "ttyusb" in device or "ttyacm" in device or "usb" in device:
            usb_ports.append(p)
        elif p["description"] and "usb" in p["description"].lower():
            usb_ports.append(p)
    return usb_ports
