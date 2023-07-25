import json
import websockets
import asyncio
import os
import datetime
import random
import time 
import shutil


global CO2, TVOC, PM25, TEMP, HUMID, LIGHT, SERVER_STATUS, SENSOR_STATUS, SERIAL_WATCHDOG
CO2 = TVOC = PM25 = TEMP = HUMID = LIGHT = 0
SERVER_STATUS = True
SENSOR_STATUS = False
SERIAL_WATCHDOG = 0


VERSION = '4.0'




try:
    import serial_asyncio
    print('serial_asyncio import succeed!')
    
except Exception as e:
    print('This system has no serial_asyncio module..')
    print('Installing serial_asyncio module..')
    os.system('pip3 install pyserial-asyncio')
    time.sleep(5)
    

f = open('/home/pi/Desktop/settings.txt', 'r')
setting_id = ''
for line in f:
    d = line.split(':')
    if d[0] == 'DEVICE_ID':
        setting_id = d[1]
        setting_id = setting_id.replace(' ', '')
        setting_id = setting_id.replace('\n', '')
f.close()

uri = 'wss://admin.azmo.kr/azmo_ws?%s' % (setting_id)

f = open('/etc/xdg/lxsession/LXDE-pi/autostart','r')
data = ''
isChanged = False
for line in f:
    if 'atmo' in line:
        line = line.replace('atmo', 'azmo')
        isChanged = True
    if 'v3' in line:
        line = line.replace('v3', 'v1')
        isChanged = True

    if 'azmo' in line:
        id = line.split('/')[1].replace('\n','')
        if setting_id != id:
            isChanged = True
        
        data += line.split('/')[0] + '/' + setting_id + '\n'
    else:
        data += line

f.close()

if isChanged:
    f = open('/etc/xdg/lxsession/LXDE-pi/autostart','w')
    f.write(data)
    f.close()
    os.system('shutdown -r now')

class InputChunkProtocol(asyncio.Protocol):
    def __init__(self):
        self.line = ''
        
    def connection_made(self, transport):
        self.transport = transport
    
    def data_received(self, data):
        global CO2, TVOC, PM25, TEMP, HUMID, LIGHT, SERVER_STATUS, SENSOR_STATUS, SERIAL_WATCHDOG
        
        if len(data) > 0:
            self.line += str(data, 'utf-8')
            
            SENSOR_STATUS = True
            SERIAL_WATCHDOG = time.time()
                        
        if ('{' in self.line and '}' in self.line) and (self.line.find('{') < self.line.find('}')):
            line = self.line[self.line.find('{'):self.line.find('}')+1]
            self.line = ''
            

            print('[Sensor Data]', line)
            try:
                if len(line) > 0:
                    d = json.loads(line)
                    
                    CO2 = int(d['CO2'])
                    TVOC = int(d['TVOC'])
                    PM25 = int(d['PM25'])
                    TEMP = float(d['TEMP'])
                    HUMID = float(d['HUMID'])
                    LIGHT = int(d['LIGHT'])
                    
            except Exception as e:
                # SERVER_STATUS = False
                print('Serial Error:', e)
        elif ('{' in self.line and '}' in self.line) and (self.line.find('{') > self.line.find('}')):
            self.line = self.line[self.line.find('{'):]
        
        self.pause_reading()
        
    def pause_reading(self):
        self.transport.pause_reading()
        
    def resume_reading(self):
        self.transport.resume_reading()
        
async def reader():
    global SERVER_STATUS
    
    serialPath = ''
    for i in range(100):
        if os.path.exists('/dev/ttyUSB%d'%i):
            serialPath = '/dev/ttyUSB%d'%i
            print(serialPath)
            break
        
    transport, protocol = await serial_asyncio.create_serial_connection(loop, InputChunkProtocol, serialPath, baudrate=115200)
    
    while True:
        if not SERVER_STATUS: break
        if not SENSOR_STATUS: break
        
        await asyncio.sleep(1)
        try:
            protocol.resume_reading()
            
        except Exception as e:
            # SERVER_STATUS = False
            print('Serial Reader Error:', e)
            
    raise RuntimeError('Serial Read Error')    

    
async def send_sensor_data(ws):
    global CO2, TVOC, PM25, TEMP, HUMID, LIGHT, SERVER_STATUS, SENSOR_STATUS, SERIAL_WATCHDOG

    DB_time_check = 0
    WEB_time_check = 0
    relay_time_check = 0
    ping_pong_time_check = 0
    
    while True:
        await asyncio.sleep(0)
        if not SERVER_STATUS: break
        if not SENSOR_STATUS: break
        try:
            if time.time() - SERIAL_WATCHDOG > 10.0:
                SENSOR_STATUS = False
                break

            if SENSOR_STATUS:
                if int(time.time()) - DB_time_check > 60 * 30:   # DB update per every 10 mins
                    DB_time_check = int(time.time())
                    params = {
                        "METHOD": "DBINIT",
                        "CO2": CO2,
                        "TVOC": TVOC,
                        "PM25": PM25,
                        "TEMP": TEMP,
                        "HUMID": HUMID,
                        "LIGHT": LIGHT
                    }
                    pData = json.dumps(params)
                    print('[DB PUSH]', pData)
                    await ws.send(pData)
                    
                if int(time.time()) - WEB_time_check > 60:   # web update per every 60 sec
                    WEB_time_check = int(time.time())
                    params = {
                        "METHOD": "SEND_F",
                        "CO2": CO2,
                        "TVOC": TVOC,
                        "PM25": PM25,
                        "TEMP": TEMP,
                        "HUMID": HUMID,
                        "LIGHT": LIGHT,
                        "WATER1": 0,
                        "WATER2": 0,
                        "WATER3": 0
                    }

                    pData = json.dumps(params)
                    print('[WEB PUSH]', pData)
                    await ws.send(pData)
            else:
                if int(time.time()) - WEB_time_check > 5:   # DO NOT CHANGE THE VALUE
                    WEB_time_check = int(time.time())
                    print('Sensor Status False')
               
            
            if int(time.time()) - ping_pong_time_check > 20:
                ping_pong_time_check = int(time.time())
                params = {
                    "METHOD": "PING"
                }

                pData = json.dumps(params)
                print('[SEND PING]', pData)
                await ws.send(pData)
                
        except Exception as e:
            SERVER_STATUS = False
            print('Sender Error', e)
    

async def recv_handler(ws):
    global SERVER_STATUS, SENSOR_STATUS
    
    while True:
        await asyncio.sleep(0)
        if not SERVER_STATUS: break
        if not SENSOR_STATUS: break
        try:
            data = await ws.recv()
            d = json.loads(data)
            print('recieved:', d)
            
            if 'TIMESTAMP' in d:
                time_cmd = "sudo date -s '%s'" % d['TIMESTAMP']
                os.system(time_cmd)
            
            if d['METHOD'] == 'TOTAL_STATUS':
                params = {
                    "METHOD": "TOTAL_STATUS",
                    "DEVICE_ID": setting_id,
                    "SENSOR_STATUS": SENSOR_STATUS,
                    "VERSION": VERSION
                }
                pData = json.dumps(params)
                await ws.send(pData)

            elif d['METHOD'] == 'R_START':
                params = {
                    "METHOD": "R_START",
                    "RESULT": True
                }
                pData = json.dumps(params)
                await ws.send(pData)
                await asyncio.sleep(5)
                os.system('shutdown -r now')
            
            elif d['METHOD'] == 'OTA':
                os.system('wget -P /home/pi/ https://raw.githubusercontent.com/picshbj/ATMOV3/main/main.py')
                
                path_src = '/home/pi/main.py'
                path_dest = '/home/pi/Documents/main.py'

                if os.path.isfile(path_src):
                    shutil.move(path_src, path_dest)
                
                await asyncio.sleep(10)

                params = {
                    "METHOD": "OTA",
                    "RESULT": True
                }
                pData = json.dumps(params)
                await ws.send(pData)

                os.system('shutdown -r now')
                    

        except Exception as e:
            SERVER_STATUS = False
            print('Recieve Error', e)
            
            

async def main():
    global SERVER_STATUS
    
    while True:
        print('Creating a new websockets..')
        SERVER_STATUS = True
        
        try:
            async with websockets.connect(uri) as ws:
                await asyncio.gather(
                    send_sensor_data(ws),
                    recv_handler(ws),
                    reader()
                )
        except Exception as e:
            print('Main Error:', e)
        await asyncio.sleep(1)

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
loop.close()
