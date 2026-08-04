# Checagem de Termohigrômetros

Software para checagem intermediária de termohigrômetros controlados via USB Serial.

## Requisitos

- Python 3.10+
- Linux (testado em Ubuntu/Debian)
- pyserial, flask, flask-cors

## Instalação

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Execução

```bash
./venv/bin/python run.py
```

A interface web estará disponível em `http://localhost:5000`.

## Estrutura do Projeto

```
.
├── backend/
│   ├── __init__.py
│   ├── app.py              # API Flask
│   ├── instruments.py      # Drivers dos instrumentos
│   └── serial_utils.py     # Detecção de portas USB serial
├── frontend/
│   └── index.html          # Interface web
├── examples/               # Códigos de referência
│   ├── termometros.py      # Fluke 1502A (serial/GPIB)
│   └── TermHigrPi.py       # Sato, Sato Old, HygroPalm, DHT22, BME280
├── run.py                  # Entry point
└── requirements.txt
```

## Instrumentos Suportados

| Instrumento | Tipo     | Baud | Databits/Paridade | Comando       | Medições          |
|-------------|----------|------|-------------------|---------------|-------------------|
| Fluke 1502A | Termômetro de referência | 2400 | 8N1 | `F` | Temperatura |
| Sato Novo   | Termohigrômetro | 19200 | 7E1 | Leitura contínua (readline) | Temperatura, Umidade |
| Sato Antigo | Termohigrômetro | 9600  | 8N1 | Leitura contínua (readline) | Temperatura, Umidade |

### Protocolos

#### Fluke 1502A
- **Inicialização**: envia `SA=0\r\n` (desabilita envio automático), depois `DU=H\r\n` (modo half-duplex)
- **Leitura**: envia `F\r\n`, lê resposta com a temperatura

#### Sato / Sato Old
- **Leitura**: descarta primeira linha, faz parse da segunda linha
- **Formato dos dados**: campos separados por espaço, temperatura no índice 1 (valor inteiro / 10), umidade no índice 2 (valor inteiro / 10)

## API REST

| Método | Rota                    | Descrição                                      |
|--------|-------------------------|------------------------------------------------|
| GET    | `/api/ports?all=0|1`   | Lista portas seriais USB detectadas            |
| GET    | `/api/instrument_types` | Lista tipos de instrumento suportados          |
| POST   | `/api/assign`           | Atribui tipo de instrumento a uma porta        |
| POST   | `/api/read`             | Lê dados do instrumento na porta configurada   |
| GET    | `/api/config`           | Lista configurações atuais (porta x tipo)      |
| POST   | `/api/monitor/start`    | Inicia monitoramento contínuo                  |
| POST   | `/api/monitor/stop`     | Para monitoramento contínuo                    |
| GET    | `/api/monitor/status`   | Status do monitoramento                        |

## Interface Web

A interface exibe:
- Lista de portas USB serial detectadas no sistema
- Dropdown para selecionar o tipo de instrumento (Fluke 1502A, Sato Novo, Sato Antigo)
- Botão "Ler" para leitura pontual
- Modo de monitoramento contínuo com intervalo configurável
- Exibição de temperatura e umidade em tempo real
- Checkbox "Todas" para exibir também portas não-USB (ex: `/dev/ttyS*`)

## Licença

Baseado nos projetos [TermHigrPi](https://github.com/gmgeronymo/TermHigrPi.git).
