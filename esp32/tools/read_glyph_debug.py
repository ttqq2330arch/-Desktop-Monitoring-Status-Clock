import serial, time, sys

PORT = "COM6"
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=0.2)
time.sleep(0.3)
ser.reset_input_buffer()

def pump(seconds):
    end = time.time() + seconds
    out = []
    while time.time() < end:
        line = ser.readline()
        if line:
            try:
                out.append(line.decode("utf-8", "replace").rstrip())
            except Exception:
                pass
    return out

print("=== boot phase (device defaults) ===")
for l in pump(4):
    if l.strip():
        print(l)

print("=== send {\"do\":0,\"ds\":190} ===")
ser.write(b'{"do":0,"ds":190}\n')
ser.flush()
for l in pump(4):
    if l.strip():
        print(l)

ser.close()
print("=== done ===")
