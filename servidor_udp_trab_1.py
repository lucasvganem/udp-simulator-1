from socket import *

def get_file():
        serverSocket.sendto(b"GET acionado", clientAddress)

def retrieve_data():
        serverSocket.sendto(b"RETR acionado", clientAddress)

serverPort = 12000
serverSocket = socket(AF_INET, SOCK_DGRAM)
serverSocket.bind(('', serverPort))
print("Servidor pronto\n")
while True:
    message, clientAddress = serverSocket.recvfrom(2048)
    print(clientAddress)
        
    if not message:
        continue
    text = message.decode(errors="ignore").strip()
    if text.startswith("GET "):
        get_file()
    elif text.startswith("RETR "):
        retrieve_data()
    else:        
        serverSocket.sendto(b"ERR 400 Unknown command", clientAddress)

    