#!/usr/bin/python3

## Log termometro Fluke 1502A
## Data: 12/01/2026
## baseado no projeto https://github.com/gmgeronymo/TermHigrPi.git


def ceil_dt(dt, delta):
    return dt + (datetime.datetime.min - dt) % delta

def data_hora():
    date = datetime.datetime.now()
    timestamp = datetime.datetime.strftime(date, '%Y-%m-%d %H:%M:%S')
    data = datetime.datetime.strftime(date, '%d/%m/%Y')
    hora = datetime.datetime.strftime(date, '%H:%M:%S')
    ano = datetime.datetime.strftime(date, '%Y')
    return {'timestamp':timestamp, 'data':data, 'hora':hora, 'ano':ano}

def corr_temp(cal):
    # calcula correcoes para temperatura
    x_temperature = cal['Temperatura']['indicacoes'].split(',')
    x_temperature = array([float(a) for a in x_temperature])
    temperature_correcoes = cal['Temperatura']['correcoes'].split(',')
    temperature_correcoes = array([float(a) for a in temperature_correcoes])
    y_temperature = x_temperature + temperature_correcoes
    # minimos quadrados
    A = vstack([x_temperature, ones(len(x_temperature))]).T
    a, b = linalg.lstsq(A, y_temperature)[0]
    # temperature = a1*x + b1
    return {'a':a, 'b':b}

def log_txt(ano,data,hora,temperature):
    with open("logs/log_"+ano+".txt","a",encoding="iso-8859-1",newline="\r\n") as text_file:
        print("{}\t{}\t{} ºC".format(data,hora,temperature), file=text_file)
        text_file.close()
    return


def dberror_log(timestamp):
    import traceback
    with open("logs/dberror.log","a") as text_file:
        print("{}   Erro ao conectar com o banco de dados \n".format(timestamp), file=text_file)
        traceback.print_exc(file=text_file)
        text_file.close()
    return

def write_buffer(timestamp,temperature,certificado,data_certificado):
    with open("write_buffer.txt","a") as csvfile:
        write_buffer = csv.writer(csvfile, delimiter=',',lineterminator='\n')
        write_buffer.writerow([timestamp,str(temperature),certificado,data_certificado])
        csvfile.close()
    return

def open_buffer():
    with open("write_buffer.txt") as csvfile:
        reader = csv.DictReader(csvfile,delimiter=',',fieldnames=['date','temperature','certificado','data_certificado'])
        d = list(reader)
        csvfile.close()
    return d

def salvar_sqlite(date,temperature):
    
    if not (os.path.isfile('logs/log.db')): # se o db nao existir, criar
        conn = sqlite3.connect('logs/log.db')
        c = conn.cursor()
        c.execute("""DROP TABLE IF EXISTS condicoes_ambientais""")
        c.execute("""CREATE TABLE condicoes_ambientais (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	date TEXT,
	temperature TEXT
        );
        """)
        conn.close()
    
    conn = sqlite3.connect('logs/log.db')
    cur = conn.cursor()
    
    cur.execute("""INSERT INTO condicoes_ambientais (date, temperature) VALUES (?, ?)""", (date, temperature))

    conn.commit()
    conn.close()

    return

def salvar_http(date, temperature, humidity, pressure, cal, url, api_key):

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    if (cal) :
        # dados do certificado de calibracao do termohigrometro
        certificado = cal['Certificado']['certificado']
        data_certificado = cal['Certificado']['data']
    else :
        certificado = '' 
        data_certificado = '' 

    # escreve no buffer de saida
    write_buffer(date,temperature,certificado,data_certificado)
   
    try:
        d = open_buffer()
        for leitura in d:
            # campos obrigatorios
            post_fields = {
                'temperature' : leitura['temperature'],
                'date' : leitura['date'],
            }
            # campos opcionais
            if (leitura['certificado'] != '') :
                post_fields['certificado'] = leitura['certificado']

            if (leitura['data_certificado'] != '') :
                post_fields['data_certificado'] = leitura['data_certificado']
            
            request = Request(url, urlencode(post_fields).encode())
            request.add_header('X-API-KEY', api_key)
            # tenta enviar os dados via http 
            json = urlopen(request, context=ctx).read().decode()
            # apaga o buffer
            open('write_buffer.txt','w').close()
    except:
        dberror_log(date)
    return

## Fluke 1502A - inicializacao (serial)
def f1502a_init_serial(ser) :
    # configurar f1502A
    # desabilitar envio automatico via serial
    ser.write(("SA=0\r\n").encode())
    time.sleep(0.1)
    # configurar modo half duplex
    ser.write(("DU=H\r\n").encode())
    time.sleep(0.1)

    return True

def f1502a_init_gpib(inst) :
    # configurar f1502A
    # desabilitar envio automatico via serial
    inst.write("SA=0")
    time.sleep(0.1)
    inst.write("DU=H")
    time.sleep(0.1)

    return True

# Fluke 1502A - leituras
def query_1502a(serialConfig) :
    ser = serial.Serial(
        port=serialConfig['port'],          # Nome da porta (COMx no Windows, /dev/ttyUSBx no Linux)
        baudrate=2400,       # Taxa de transmissão
        bytesize=serial.EIGHTBITS,    # 8 bits de dados
        parity=serial.PARITY_NONE,    # Sem paridade
        stopbits=serial.STOPBITS_ONE, # 1 bit de parada
        timeout=1,           # Timeout de leitura (1 segundo)
        xonxoff=False,       # Controle de fluxo software
        rtscts=False,        # Controle de fluxo hardware RTS/CTS
        dsrdtr=False         # Controle de fluxo hardware DSR/DTR
    )
    ser.write(("F\r\n").encode())
    rcv_str = ser.read(50)

    ser.close()

    # transformar o byte object recebido em uma string
    temperature = rcv_str.decode('utf-8').strip()
    
    return temperature

def load_config(config_path):
    if not os.path.exists(config_path):
        print(f"Erro: Arquivo não encontrado: {config_path}")
        return

    config = configparser.ConfigParser()
    config.read(config_path)

    print("--- Configuração Geral ---")
    if 'LogConfig' in config:
        print(f"Intervalo de Leitura: {config['LogConfig'].get('interval')} minutos")
        interval = config['LogConfig'].get('interval')
        print(f"URL da API REST: {config['LogConfig'].get('url')}")
        url = config['LogConfig'].get('url')
        
        # Le a lista de instrumentos
        # Assume formato separado por virgula: "inst1, inst2, inst3"
        instruments_str = config['LogConfig'].get('instruments', '')
        instrument_names = [name.strip() for name in instruments_str.split(',') if name.strip()]
        
        print(f"Instrumentos detectados: {instrument_names}")
    else:
        print("Seção [LogConfig] não encontrada.")
        return

    print("\n--- Descoberta de Instrumentos ---")
    devices = []

    for name in instrument_names:
        if name not in config:
            print(f"[AVISO] Seção [{name}] definida em 'instruments' mas não encontrada no arquivo.")
            continue
        
        section = config[name]
        dev_type = section.get('type')
        
        print(f"-> Configurando '{name}' (Tipo: {dev_type})")
        
        device_data = {'name': name, 'type': dev_type, 'params': {}}
        
        if dev_type == 'serial':
            device_data['params']['port'] = section.get('port')
            device_data['params']['timeout'] = section.get('timeout')
            device_data['params']['key'] = section.get('key')
            device_data['params']['cal'] = section.get('cal')

        elif dev_type == 'gpib':
            device_data['params']['address'] = section.get('address')
            device_data['params']['key'] = section.get('key')
            device_data['params']['cal'] = section.get('cal')

        else:
            print(f"   [ERRO] Tipo desconhecido: {dev_type}")
            
        devices.append(device_data)

    return [interval, url, devices]


if __name__ == "__main__":

    import time
    import datetime
    import configparser 	# ler arquivo de configuracao
    import csv          	# salvar dados antes de enviar ao DB
    import sqlite3      	# banco de dados local
    import os
    import ssl
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen  # requests http

    # Serial
    import serial
    # GPIB
    import pyvisa as visa 

    # inicializa VISA
    rm = visa.ResourceManager('@py') 

    # o arquivo config.ini reune as configuracoes que podem ser alteradas
    #config = configparser.ConfigParser()    # iniciar o objeto config
    #config.read('/boot/datalogger.ini')             # ler o arquivo de configuracao     

    print(f"Lendo configuração de termometros.ini\n")
    [interval, url, devices] = load_config('./termometros.ini')
    
    print("\n--- Resumo dos Dispositivos Carregados ---")
    inst = {} 
    ser = {} 
    for index, dev in enumerate(devices):
        print(dev)
        # inicia conexoes GPIB
        if (dev['type'] == 'gpib') :
            devices[index]['inst'] = rm.open_resource('GPIB0::'+dev['params']['address']+'::INSTR')
            f1502a_init_gpib(devices[index]['inst'])

        # inicia conexoes serial
        if (dev['type'] == 'serial') :
            devices[index]['ser'] = serial.Serial(
                port=dev['params']['port'],          # Nome da porta (COMx no Windows, /dev/ttyUSBx no Linux)
                baudrate=2400,       # Taxa de transmissão
                bytesize=serial.EIGHTBITS,    # 8 bits de dados
                parity=serial.PARITY_NONE,    # Sem paridade
                stopbits=serial.STOPBITS_ONE, # 1 bit de parada
                timeout=1,           # Timeout de leitura (1 segundo)
                xonxoff=False,       # Controle de fluxo software
                rtscts=False,        # Controle de fluxo hardware RTS/CTS
                dsrdtr=False         # Controle de fluxo hardware DSR/DTR
            )
            f1502a_init_serial(devices[index]['ser'])


        #key_serial = config['SerialConfig']['key']
        #key_gpib = config['GPIBConfig']['key']
      
    delta = datetime.timedelta(minutes=int(interval))
    INTERVAL = delta.total_seconds() # intervalo entre as leituras salvas (segundos)

    now = datetime.datetime.now()
    start = ceil_dt(now, delta) # inicia em horarios 'redondos'
   
    # aguarda o proximo horario inteiro do intervalo para comecar     
    time.sleep((start-now).total_seconds()) # Overall INTERVAL second polling.

    next_reading = time.time()
   
    while True:
        data_atual = data_hora()
        
        for dev in devices :
            # buscar leitura do sensor
            if (dev['type'] == 'gpib') :
                temperature = dev['inst'].query("F").strip()
                salvar_http(data_atual['timestamp'],temperature, None, None, None, url, dev['params']['key'])

            if (dev['type'] == 'serial') :
                dev['ser'].write(("F\r\n").encode())
                rcv_str = dev['ser'].read(50)
                temperature = rcv_str.decode('utf-8').strip()
                salvar_http(data_atual['timestamp'],temperature, None, None, None, url, dev['params']['key'])
               


        next_reading += INTERVAL
        time.sleep(next_reading-time.time()) # Overall INTERVAL second polling.

