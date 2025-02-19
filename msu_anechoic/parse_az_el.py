import re

from msu_anechoic import AzEl

azimuth_elevation_regex = re.compile(r"Pos\s*=\s*El:\s*(?P<elevation>[-\d\.]+)\s*,\s*Az:\s*(?P<azimuth>[-\d\.]+)")
"""Should match a string like `"Pos= El: -0.03 , Az: -0.03\\r\\n"`"""

def parse_az_el(data: bytes) -> AzEl | None:
    """Parse azimuth and elevation from a byte string.
    
    Will return the most recent data in the byte string. Assumes that the data is in the format
    `b'Pos= El: -0.03 , Az: -0.03\\r\\n'`, although the regex is permissive about whitespace and
    number formatting.
    """

    # Split data into individual lines so that a corrupt line
    # doesn't cause the whole parse to fail.
    lines = data.split(b"\n")

    # Iterate over lines in reverse order so that we get the most recent data.
    for line in lines[ : : -1]:
        # Convert as ASCII. This will fail if RS-232 data was corrupted.
        try:
            string = line.decode(encoding="ascii")
        except UnicodeDecodeError:
            continue
        
        # Try to match the regex. If it doesn't match, continue.
        # Every line should match, unless it is corrupted or truncated.
        match = azimuth_elevation_regex.search(string)
        if not match:
            continue

        # At this point, we have a match. Parse it
        groupdict = match.groupdict()
        azimuth_string = groupdict["azimuth"]
        elevation_string = groupdict["elevation"]

        # There are things that match the regex that are not valid floats, like "123.456" or 98-76".
        # So put them in a try/except.
        try:
            rv = AzEl(azimuth=float(azimuth_string), elevation=float(elevation_string))
            return rv
        except ValueError:
            continue

    # If we get here, we didn't find any valid data.
    return None


if __name__ == "__main__":
    from textwrap import dedent
    text = """
    Pos= El: -0.01 , Az: -0.01\r
    Pos= El: -0.02 , Az: -0.02\r
    Pos= El: -0.03 , Az: -0.03\r
    Pos= El: -0.04 , Az: -0.04\r
    Pos= El: -0.05 , Az: -0.05\r
    Pos= El: -0.06 , A
    """

    print(text)

    bytes_ = dedent(text).encode(encoding="ascii")
    print(bytes_)

    for index, line in enumerate(bytes_.split(b"\n")):
        print(index, line)

    # exit()

    print(parse_az_el(bytes_))  # Should print AzEl(azimuth=-0.05, elevation=-0.06)

    exit()
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

        # print(parse_az_el(serial_port.read(1000)))