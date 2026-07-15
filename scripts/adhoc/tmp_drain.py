import sys
sys.path.insert(0, '.')
from connectors.relay_client import drain_queue
n = drain_queue()
print(f'Procesados: {n}')
