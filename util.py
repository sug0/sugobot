import re

# parse a nick from host
def parse_nick(host):
    return host[:host.find('!')]

# regular expressions
regex = [(re.compile(r), rr) for (r, rr) in [
    (r'\*\*([^*]+)\*\*', r'%c\1%c' % ('\x02', '\x0f')), # bold
    (r'__([^_]+)__', r'%c\1%c' % ('\x1f', '\x0f')),     # underline
    (r'\*([^*]+)\*', r'%c\1%c' % ('\x1d', '\x0f'))      # italic
]]

def rp(s):
    for (r, rr) in regex:
        s = r.sub(rr, s)
    return s

# temperature unit converters
def K2C(k):
    return k - 273.15

def K2F(k):
    return (k * 9)/5 - 459.67

# database shit
def _create_database_service(db, service):
    try:
        db[service]
    except KeyError:
        db[service] = {}

def create_database_services(db, services):
    [_create_database_service(db, s) for s in services]
