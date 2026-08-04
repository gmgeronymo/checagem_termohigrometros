#!/usr/bin/python3

# Termohigrometro utilizando RaspberryPi e um sensor DHT-22
# Autor: Gean Marcos Geronymo
# Data: 10/11/2016

# Modificado em 03/04/2019 - incluido suporte a interface REST
# envia os dados via requisicoes HTTP
# compativel com redes WiFi corporativas que bloqueam todas as portas TCP exceto 80 e 443
# Removido acesso direto ao DB externo

# Nova versao 16/10/2019
# Suporte a sensor BME280 via i2c
# Suporte a display LCD via i2c

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

def corr_umid(cal):
    # calcula correcoes para a umidade
    x_humidity = cal['Umidade']['indicacoes'].split(',')
    x_humidity = array([float(a) for a in x_humidity])
    humidity_correcoes = cal['Umidade']['correcoes'].split(',')
    humidity_correcoes = array([float(a) for a in humidity_correcoes])
    y_humidity = x_humidity + humidity_correcoes
    # minimos quadrados
    A = vstack([x_humidity, ones(len(x_humidity))]).T
    a, b = linalg.lstsq(A, y_humidity)[0]
    # humidity = a2*x + b2
    return {'a':a, 'b':b}

# parametro pressure eh opcional
def log_txt(ano,data,hora,humidity,temperature,pressure=None):
    with open("logs/log_"+ano+".txt","a",encoding="iso-8859-1",newline="\r\n") as text_file:
        if (pressure) :
            print("{}\t{}\t{}%\t{} ºC\t{} hPa".format(data,hora,humidity,temperature,pressure), file=text_file)
        else :
            print("{}\t{}\t{}%\t{} ºC".format(data,hora,humidity,temperature), file=text_file)
        text_file.close()
    return

def dberror_log(timestamp):
    import traceback
    with open("logs/dberror.log","a") as text_file:
        print("{}   Erro ao conectar com o banco de dados \n".format(timestamp), file=text_file)
        traceback.print_exc(file=text_file)
        text_file.close()
    return

def write_buffer(timestamp,temperature,humidity,pressure,certificado,data_certificado):
    with open("write_buffer.txt","a") as csvfile:
        write_buffer = csv.writer(csvfile, delimiter=',',lineterminator='\n')
        write_buffer.writerow([timestamp,str(temperature),str(humidity),str(pressure),certificado,data_certificado])
        csvfile.close()
    return

def open_buffer():
    with open("write_buffer.txt") as csvfile:
        reader = csv.DictReader(csvfile,delimiter=',',fieldnames=['date','temperature','humidity','pressure','certificado','data_certificado'])
        d = list(reader)
        csvfile.close()
    return d

def salvar_sqlite(date,temperature,humidity,pressure=None):
    
    if not (os.path.isfile('logs/log.db')): # se o db nao existir, criar
        conn = sqlite3.connect('logs/log.db')
        c = conn.cursor()
        c.execute("""DROP TABLE IF EXISTS condicoes_ambientais""")
        c.execute("""CREATE TABLE condicoes_ambientais (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
	date TEXT,
	temperature TEXT,
	humidity TEXT,
	pressure TEXT
        );
        """)
        conn.close()
    
    conn = sqlite3.connect('logs/log.db')
    cur = conn.cursor()
    
    if (pressure) :
        cur.execute("""INSERT INTO condicoes_ambientais (date, temperature, humidity, pressure) VALUES (?, ?, ?, ?)""", (date, temperature, humidity, pressure))
    else :
        cur.execute("""INSERT INTO condicoes_ambientais (date, temperature, humidity) VALUES (?, ?, ?)""", (date, temperature, humidity))

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

    if not (pressure) :
        pressure = ''
        
    # escreve no buffer de saida
    write_buffer(date,temperature,humidity,pressure,certificado,data_certificado)
   
    try:
        d = open_buffer()
        for leitura in d:
            # campos obrigatorios
            post_fields = {
                'temperature' : leitura['temperature'],
                'humidity' : leitura['humidity'],
                'date' : leitura['date'],
            }
            # campos opcionais
            if (leitura['pressure'] != '') :
                post_fields['pressure'] = leitura['pressure']

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

def query_sato_old(serialconfig):
    # configuracao da conexao serial
    # adaptado para termohigrometro SATO
    ser = serial.Serial(
        port=serialconfig['port'],
        baudrate=9600,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.EIGHTBITS,
        timeout = int(serialconfig['timeout'])
    )
    # le uma linha do termohigrometro
    ser.readline()
    rcv_str = ser.readline()
    # fecha a conexao serial
    ser.close()

    # transformar o byte object recebido em uma string
    dec_str = rcv_str.decode('utf-8')
    # processa a string para extrair os valores de temperatura e umidade
    data = dec_str.split()
    temperature = float(data[1].replace(',',''))/10
    humidity = float(data[2])/10
    
    data_array = [str(humidity), str(temperature)]
    return data_array


def query_sato(serialconfig):
    # configuracao da conexao serial
    # adaptado para termohigrometro SATO
    ser = serial.Serial(
        port=serialconfig['port'],
        baudrate=19200,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.SEVENBITS,
        timeout = int(serialconfig['timeout'])
    )
    # le uma linha do termohigrometro
    ser.readline()
    rcv_str = ser.readline()
    # fecha a conexao serial
    ser.close()

    # transformar o byte object recebido em uma string
    dec_str = rcv_str.decode('utf-8')
    # processa a string para extrair os valores de temperatura e umidade
    data = dec_str.split()
    temperature = float(data[1].replace(',',''))/10
    humidity = float(data[2])/10
    
    data_array = [str(humidity), str(temperature)]
    return data_array

def query_hygropalm(serialconfig):
    # configuracao da conexao serial
    # seguindo informacoes do manual do fabricante
    ser = serial.Serial(
        port=serialconfig['port'],
        baudrate=19200,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.SEVENBITS,
        timeout = int(serialconfig['timeout'])
    )

    querystring = serialconfig['querystring']
    # envia para o termohigrometro a query string com o terminador de linha \r
    #ser.write(b'{u00RDD}\r')
    ser.write((querystring+'\r').encode())

    # le a resposta do termohigrometro
    rcv_str = ser.read(50)
    # fecha a conexao serial
    ser.close()

    # transformar o byte object recebido em uma string
    dec_str = rcv_str.decode('utf-8')
    # processa a string para extrair os valores de temperatura e umidade
    # o termohigrometro retorna uma string do tipo:
    # '{u00RDD 0071.68;0022.78;----.--;----.--;#6\r'
    # o comando abaixo remove o trecho
    # '{u00RDD '
    # Assim, e possivel separar temperatura e umidade utilizando ';'
    data_array = (dec_str.replace(querystring.replace('}',' '),'')).split(';')
    # arredonda a temperatura e umidade para uma casa decimal
    return data_array

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
    # o arquivo config.ini reune as configuracoes que podem ser alteradas
    config = configparser.ConfigParser()    # iniciar o objeto config
    config.read('/boot/datalogger.ini')             # ler o arquivo de configuracao     

    if (config['SensorConfig']['sensor'] == 'hygropalm') :
        import serial
    elif (config['SensorConfig']['sensor'] == 'sato') :
        import serial
    elif (config['SensorConfig']['sensor'] == 'sato_old') :
        import serial
    else :
        import pigpio		# acesso a interface GPIO
        # configuracao do sensor
        # inicia interface pigpio
        pi = pigpio.pi()

        if not pi.connected:
            exit(0)
      
        if (config['SensorConfig']['sensor'] == 'DHT22') :
            import DHT22
            s = DHT22.sensor(pi, 22)

        elif (config['SensorConfig']['sensor'] == 'BME280') :
            import BME280
            s = BME280.sensor(pi)

    
    # configuracao para acessar o REST Server
    if (config['HttpConfig']['enable'] == 'true') :
        url = config['HttpConfig']['url']
        api_key = config['HttpConfig']['api_key']
      
    delta = datetime.timedelta(minutes=int(config['LogConfig']['interval']))
    INTERVAL = delta.total_seconds() # intervalo entre as leituras salvas (segundos)

    now = datetime.datetime.now()
    start = ceil_dt(now, delta) # inicia em horarios 'redondos'
   
    # verifica se opcao lcd esta habilitada
    if (config['LCDConfig']['enable'] == 'true') :
        import i2c_lcd
        refresh_lcd = datetime.timedelta(seconds=int(config['LCDConfig']['refresh']))
        INTERVAL_LCD = refresh_lcd.total_seconds()
        INTERVAL_START = (start-now).total_seconds()
        REP_run = int(INTERVAL // INTERVAL_LCD)  # qtde rep ate salvar leitura
        REP_start = int(INTERVAL_START // INTERVAL_LCD) # valor inicial de REP para salvar em horarios 'redondos'
        #lcd = lcd_config()
        lcd = i2c_lcd.lcd(pi, width=16)
        counter = 0
        first_run = True
    else :
        # aguarda o proximo horario inteiro do intervalo para comecar     
        time.sleep((start-now).total_seconds()) # Overall INTERVAL second polling.

    next_reading = time.time()
   
    while True:
        data_atual = data_hora()

        # buscar leitura do sensor
        if (config['SensorConfig']['sensor'] == 'DHT22') :
            s.trigger()
            time.sleep(0.2)
            temperature = s.temperature()
            humidity = s.humidity()
            pressure = None

        elif (config['SensorConfig']['sensor'] == 'BME280') :
            temperature, pressure, humidity = s.read_data()
            # ajusta valor da pressap pra kPa
            pressure = pressure/100
        else :                  # sensors comerciais interface serial
            if (config['SensorConfig']['sensor'] == 'sato') :
                data_array = query_sato(config['SerialConfig'])
            elif (config['SensorConfig']['sensor'] == 'sato_old') :
                data_array = query_sato_old(config['SerialConfig'])
            else :
                data_array = query_hygropalm(config['SerialConfig'])
                
            temperature = float(data_array[1])
            humidity = float(data_array[0])
            pressure = None

        
        # verificar se correcoes devem ser aplicadas
        if (config['CalConfig']['enable'] == 'true') :
            # carrega numpy para calcular correcoes
            from numpy import array, linalg, arange, ones, vstack
            # o arquivo cal.ini reune as informacoes da calibracao do termohigrometro
            cal = configparser.ConfigParser()
            cal.read('/boot/cal.ini')

            # calcular correcoes temperatura
            coeff_temp = corr_temp(cal)
            # calcular correcoes umidade
            coeff_umid = corr_umid(cal)

            # aplicar correcoes
            temperature = round((coeff_temp['a'] * temperature + coeff_temp['b']),1)
            humidity = round((coeff_umid['a'] * humidity + coeff_umid['b']),1)
        else :
            # valores sem correcao
            temperature = round(temperature,1)
            humidity = round(humidity,1)


        # LCD ativado
        if (config['LCDConfig']['enable'] == 'true') :
            lcd.put_line(0, data_atual['hora']+" "+"{0:.1f}".format(temperature)+chr(223)+"C")
            if (config['SensorConfig']['sensor'] == 'DHT22') :
                lcd.put_line(1, "{0:.1f}".format(humidity)+"% ")
            if (config['SensorConfig']['sensor'] == 'BME280') :
                lcd.put_line(1, "{0:.1f}".format(humidity)+"% "+"{0:.1f}".format(pressure)+" hPa")

            if (first_run) :
                REP = REP_start + 1
            else:
                REP = REP_run
            
            if (counter == REP) :
                if (config['SensorConfig']['sensor'] == 'BME280') : # soh BME280 registra pressao
                    log_txt(data_atual['ano'],data_atual['data'],data_atual['hora'],"{0:.1f}".format(humidity),"{0:.1f}".format(temperature),"{0:.1f}".format(pressure))
                    salvar_sqlite(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity), "{0:.1f}".format(pressure))
                else :
                    log_txt(data_atual['ano'],data_atual['data'],data_atual['hora'],"{0:.1f}".format(humidity),"{0:.1f}".format(temperature))
                    salvar_sqlite(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity))    

                if (config['HttpConfig']['enable'] == 'true') :
                    # se correcoes forem aplicadas, salvar dados do certificado de calibracao
                    if (config['CalConfig']['enable'] == 'true') :
                        if (config['SensorConfig']['sensor'] == 'BME280') : # soh BME280 registra pressao
                            salvar_http(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity), "{0:.1f}".format(pressure), cal, url, api_key)
                        else :
                            salvar_http(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity), None, cal, url, api_key)
                    else :
                        if (config['SensorConfig']['sensor'] == 'BME280') : # soh BME280 registra pressao
                            salvar_http(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity), "{0:.1f}".format(pressure), None, url, api_key)
                        else :
                            salvar_http(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity), None, None, url, api_key)
                counter = 0
                first_run = False

            counter += 1 # incrementa contador   
            next_reading += INTERVAL_LCD
            time.sleep(next_reading-time.time())
            # sem LCD
        else :
            if (config['SensorConfig']['sensor'] == 'BME280') : # soh BME280 registra pressao
                log_txt(data_atual['ano'],data_atual['data'],data_atual['hora'],"{0:.1f}".format(humidity),"{0:.1f}".format(temperature), "{0:.1f}".format(pressure))
                salvar_sqlite(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity), "{0:.1f}".format(pressure))
            else :
                log_txt(data_atual['ano'],data_atual['data'],data_atual['hora'],"{0:.1f}".format(humidity),"{0:.1f}".format(temperature))
                salvar_sqlite(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity))
                
            if (config['HttpConfig']['enable'] == 'true') :
                if (config['CalConfig']['enable'] == 'true') :
                    if (config['SensorConfig']['sensor'] == 'BME280') : # soh BME280 registra pressao
                        salvar_http(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity), "{0:.1f}".format(pressure), cal, url, api_key)
                    else :
                        salvar_http(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity), None, cal, url, api_key)
                else :
                    if (config['SensorConfig']['sensor'] == 'BME280') : # soh BME280 registra pressao
                        salvar_http(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity), "{0:.1f}".format(pressure), None, url, api_key)
                    else :
                        salvar_http(data_atual['timestamp'],"{0:.1f}".format(temperature),"{0:.1f}".format(humidity), None, None, url, api_key)
               
            next_reading += INTERVAL
            time.sleep(next_reading-time.time()) # Overall INTERVAL second polling.
	  
    if (lcd) :
        lcd.close()
	
    s.cancel()
    pi.stop()

