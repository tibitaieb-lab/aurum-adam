"""Diagnostic Python guard; no OS sandbox or hostile-code isolation is claimed."""
import sys


def install():
    def guard(event, args):
        if event in {'socket.connect', 'socket.connect_ex', 'socket.sendto', 'socket.getaddrinfo',
                     'socket.gethostbyname', 'socket.gethostbyname_ex', 'subprocess.Popen', 'os.system'}:
            raise RuntimeError('ADAM_PUBLIC_OFFLINE_TRANSPORT_FORBIDDEN')
    sys.addaudithook(guard)
