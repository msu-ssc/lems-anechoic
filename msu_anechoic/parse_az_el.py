import re

from msu_anechoic import AzEl

regex = re.compile(r"Pos\s*=\s*El:\s*(?P<elevation>[-\d\.]+)\s*,\s*Az:\s*(?P<azimuth>[-\d\.]+)")

def parse_az_el(az_el_bytes: bytes) -> AzEl | None:
    """Parse azimuth and elevation from a byte string."""
    try:
        az_el_str = az_el_bytes.decode(encoding="ascii")
    except UnicodeDecodeError:
        return None
    # match = re.match(r"POS:([0-9.]+),([0-9.]+);", az_el_str)
    matches = [match for match in regex.finditer(az_el_str) if match]
    if not matches:
        return None
    
    last_match = matches[-1]
    groupdict = last_match.groupdict()
    az_str = groupdict["azimuth"]   
    el_str = groupdict["elevation"]
    # az_str, el_str = match.groups()
    return AzEl(azimuth=float(az_str), elevation=float(el_str))


if __name__ == "__main__":
    from textwrap import dedent
    text = """
    Pos= El: -0.01 , Az: -0.01
    Pos= El: -0.02 , Az: -0.02
    Pos= El: -0.03 , Az: -0.03
    Pos= El: -0.04 , Az: -0.04
    Pos= El: -0.05 , Az: -0.05
    Pos= El: -0.06 , A
    """

    print(text)

    bytes_ = dedent(text).encode(encoding="ascii")
    print(bytes_)

    print(parse_az_el(bytes_))  # Should print AzEl(azimuth=-0.05, elevation=-0.06)

    COMPORT = "COM5"

    import serial

    serial_port = serial.Serial(COMPORT)

    loop_counter = 0
    successful_reads = 0
    successful_parses = 0
    import time
    while True:
        time.sleep(0.200)
        loop_counter += 1
        print(f"Waiting for data... {loop_counter=} {successful_reads=} {successful_parses=}")
        try:
            data = serial_port.read(1000)
            if not data:
                print("No data, but no error")
                continue
            successful_reads += 1
            print(f"Read {len(data)} bytes")

            
            az_el = parse_az_el(data)
            if az_el:
                successful_parses += 1
                print(f"Parsed: {az_el} from {data[-50 : ]}")
            else:
                print(f"Failed to parse data: {data[-50 : ]}")
        except Exception as exc:
            print(f"Failed to read data: {exc}")
            continue

        print(parse_az_el(serial_port.read(1000)))