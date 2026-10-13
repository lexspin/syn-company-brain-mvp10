"""One bounded JSON request contract for the local gateway and canonical server."""
import json
import math

def strict_json(body):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate JSON key.')
            result[key]=value
        return result
    def constant(_):raise ValueError('Non-finite JSON number.')
    def number(value):
        result=float(value)
        if not math.isfinite(result):raise ValueError('Non-finite JSON number.')
        return result
    try:
        return json.loads(body,object_pairs_hook=pairs,parse_constant=constant,parse_float=number)
    except (UnicodeError,RecursionError) as error:
        raise ValueError('Invalid or excessively nested JSON.') from error

def read_json_request(handler):
    lengths=handler.headers.get_all('Content-Length',[])
    if len(lengths)!=1 or handler.headers.get('Transfer-Encoding'):
        raise ValueError('Use one Content-Length without Transfer-Encoding.')
    length=int(lengths[0])
    if not 0 < length <= 200000:raise ValueError('Invalid request size.')
    timeout=handler.connection.gettimeout()
    try:
        handler.connection.settimeout(10)
        body=handler.rfile.read(length)
    except TimeoutError as error:
        raise ValueError('Request body timed out.') from error
    finally:
        handler.connection.settimeout(timeout)
    if len(body)!=length:raise ValueError('Incomplete request.')
    return body,strict_json(body)
