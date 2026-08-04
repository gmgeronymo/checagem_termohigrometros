# Knowledge Base - Checagem de Termohigrômetros

Base de conhecimento para continuidade do desenvolvimento.

## Visão Geral

Sistema para checagem intermediária de termohigrômetros via USB Serial em Linux. Backend Python (Flask) + frontend web (HTML/JS vanilla).

## Arquitetura

```
┌──────────────────────────────────────────────────────────┐
│ Frontend (index.html)                                    │
│  - Lista portas USB serial                               │
│  - Dropdown tipo instrumento por porta                   │
│  - Leitura manual / monitoramento contínuo               │
└───────────────────┬──────────────────────────────────────┘
                    │ HTTP REST
┌───────────────────▼──────────────────────────────────────┐
│ Backend (Flask) - backend/app.py                         │
│  - /api/ports          GET    lista portas               │
│  - /api/assign         POST   vincula porta x tipo       │
│  - /api/read           POST   leitura única              │
│  - /api/monitor/start  POST   inicia loop de leituras    │
│  - /api/monitor/stop   POST   para loop                  │
│  - /api/monitor/status GET    status do loop             │
│  - /api/instrument_types GET tipos suportados            │
│  - /api/config         GET    config atual               │
└───────────────────┬──────────────────────────────────────┘
                    │
┌───────────────────▼──────────────────────────────────────┐
│ Instruments (backend/instruments.py)                     │
│  - Fluke1502A  : temperatura (2400 8N1, comando F)      │
│  - Sato        : temp + umidade (19200 7E1, readline)   │
│  - SatoOld     : temp + umidade (9600 8N1, readline)    │
└───────────────────┬──────────────────────────────────────┘
                    │
┌───────────────────▼──────────────────────────────────────┐
│ Serial Utils (backend/serial_utils.py)                   │
│  - list_serial_ports()     pyserial list_ports           │
│  - find_usb_serial_ports() filtra USB + opção all ports  │
└──────────────────────────────────────────────────────────┘
```

## Estado Atual

### Implementado
- [x] Detecção de portas USB serial (pyserial)
- [x] Driver Fluke 1502A via serial (baseado em `examples/termometros.py`)
- [x] Driver Sato Novo via serial (baseado em `examples/TermHigrPi.py`)
- [x] Driver Sato Antigo via serial (baseado em `examples/TermHigrPi.py`)
- [x] API REST para leitura e configuração
- [x] Interface web com seleção de instrumento por porta
- [x] Monitoramento contínuo com intervalo configurável
- [x] Filtro USB vs todas as portas (checkbox "Todas")

### Pendente / Possíveis Melhorias
- [ ] Auto-detecção do tipo de instrumento (tentar protocolos e validar resposta)
- [ ] Suporte a HygroPalm (query string via serial, já existe em `examples/TermHigrPi.py`)
- [ ] Correções de calibração (cálculo de mínimos quadrados dos exemplos)
- [ ] Logging em arquivo (txt, sqlite) como nos exemplos
- [ ] Envio de dados via HTTP para servidor REST externo
- [ ] Salvar/persistir configuração de portas (json/ini)
- [ ] Interface de calibração (upload certificado, cálculo de correções)
- [ ] Tela de relatório de checagem (comparação referência vs instrumento)
- [ ] Histórico de leituras com gráficos
- [ ] Suporte a GPIB para Fluke 1502A (já nos exemplos, usando pyvisa)
- [ ] WebSocket para atualização em tempo real (substituir polling)

## Detalhes dos Protocolos

### Fluke 1502A
```
Porta serial: /dev/ttyUSBx
Baud: 2400, 8 bits, sem paridade, 1 stop bit
Init:
  SA=0\r\n     → desabilita envio automático serial
  DU=H\r\n     → modo half duplex
Leitura:
  F\r\n        → solicita leitura
  Resposta: string com valor de temperatura (ex: "23.45")
```

### Sato (Novo)
```
Porta serial: /dev/ttyUSBx  
Baud: 19200, 7 bits, paridade par, 1 stop bit
Leitura:
  readline()   → descarta primeira linha
  readline()   → segunda linha contém os dados
  Formato: "XXX NNNNN MM NNNNN MM ..."
  temperatura = int(data[1].replace(',','')) / 10
  umidade     = int(data[2]) / 10
```

### Sato (Antigo)
```
Porta serial: /dev/ttyUSBx
Baud: 9600, 8 bits, sem paridade, 1 stop bit
Leitura:
  readline()   → descarta primeira linha
  readline()   → segunda linha contém os dados
  Formato: mesmo do Sato Novo
  temperatura = int(data[1].replace(',','')) / 10
  umidade     = int(data[2]) / 10
```

### HygroPalm (não implementado, referência em examples/TermHigrPi.py)
```
Porta serial: /dev/ttyUSBx
Baud: 19200, 7 bits, paridade par, 1 stop bit
Leitura:
  write(querystring + '\r')
  read(50)
  Resposta: '{u00RDD UUUU.UU;TTTT.TT;----.--;----.--;#6\r'
  temperatura = data_array[1]
  umidade     = data_array[0]
```

## Estrutura de Arquivos

```
checagem_termohigrometros/
├── backend/
│   ├── __init__.py          # pacote
│   ├── app.py               # Flask app + rotas API
│   ├── instruments.py       # classes Instrument, Fluke1502A, Sato, SatoOld
│   └── serial_utils.py      # funções de detecção de portas
├── frontend/
│   └── index.html           # SPA com interface completa
├── examples/                # códigos originais de referência
│   ├── termometros.py       # Fluke 1502A reference
│   └── TermHigrPi.py        # Sato/HygroPalm reference
├── run.py                   # entry point
├── requirements.txt         # flask, pyserial, flask-cors
├── README.md                # documentação do projeto
└── KB.md                    # este arquivo
```

## Decisões de Design

1. **Flask** em vez de FastAPI: mais simples, menos dependências
2. **SPA vanilla JS** em vez de framework: zero build step, leve
3. **Sem banco de dados**: configuração em memória (assignments dict), sem persistência por enquanto
4. **Monitoramento com thread**: thread separada com loop sleep, sem bloqueio do event loop Flask
5. **Protocolos fiéis aos exemplos**: mantidos baud rates, paridades e comandos exatamente como nos arquivos de referência

## Como Adicionar um Novo Instrumento

1. Criar classe em `backend/instruments.py` herdando de `Instrument`
2. Implementar `init(ser)` e `read(port, timeout)`
3. Registrar em `INSTRUMENT_TYPES` dict
4. Adicionar opção no `<select>` do `frontend/index.html`

## Comandos Úteis

```bash
# Ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependências
pip install -r requirements.txt

# Executar
python run.py

# Listar portas seriais (diagnóstico)
python -c "import serial.tools.list_ports; [print(p) for p in serial.tools.list_ports.comports()]"
```
