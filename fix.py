import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('72.61.149.231', username='dev', password='Sunshine123!@#')

commands = [
    'sudo grep -rn ForceCommand /etc/ssh/',
    'sudo cat /etc/passwd | grep dev',
    'sudo ls -la /usr/local/bin/cce-compose',
    "sudo bash -c 'echo -e \"#!/bin/bash\\nmkdir -p /opt/covered-call-engine\\ncd /opt/covered-call-engine\\ndocker compose \\$@\" > /usr/local/bin/cce-compose'",
    'sudo chmod +x /usr/local/bin/cce-compose',
    'sudo cat /usr/local/bin/cce-compose',
]

for cmd in commands:
    stdin, stdout, stderr = client.exec_command(cmd)
    print('CMD:', cmd)
    print('OUT:', stdout.read().decode())
    print('ERR:', stderr.read().decode())
    print()

client.close()