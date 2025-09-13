from socket import *
import os

def get_file(text):
    serverSocket.sendto(b"GET acionado", clientAddress)
    arquivo = text[4:]
    directory_path = "/home/aluno/Downloads"

    if arquivo in os.listdir(directory_path):
        print(f"'{arquivo}' found in '{directory_path}'")
        with open(directory_path + "/" + arquivo, "rb") as arquivo_envio:
            data = arquivo_envio.read()
            serverSocket.sendto(data, clientAddress)
    else:
        print(f"'{arquivo}' not found in '{directory_path}'")
 

def retrieve_data():
    serverSocket.sendto(b"RETR acionado", clientAddress)

serverPort = 12000
serverSocket = socket(AF_INET, SOCK_DGRAM)
serverSocket.bind(('', serverPort))
print("Servidor pronto\n")

while True:
    message, clientAddress = serverSocket.recvfrom(2048)
    if not message:
        continue
    text = message.decode(errors="ignore").strip()
    if text.startswith("GET "):
        get_file(text)
    elif text.startswith("RETR "):
        retrieve_data()
    else:        
        serverSocket.sendto(b"ERR 400 Unknown command", clientAddress)

    